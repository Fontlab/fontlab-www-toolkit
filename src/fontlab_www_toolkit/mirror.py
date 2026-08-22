"""Mirror a static site folder over HTTP from a ``manifest.json``.

The producer (e.g. ``github.com/fontlab/tth-debugger`` CI) publishes a folder
plus a manifest describing every file in it::

    {
      "schema":  "fontlab-site-manifest/1",
      "name":    "tth-debugger",
      "version": "0.1.0",
      "commit":  "<git sha>",
      "builtAt": "2026-08-22T15:26:19Z",
      "baseUrl": "https://fontlab.dev/tth-debugger/alpha-sdx992/",
      "entry":   "index.html",
      "files":   [{"path": "assets/x.js", "size": 123, "sha256": "…", "type": "…"}]
    }

:func:`mirror` downloads every listed file into a temporary sibling of
``dest``, verifies size + SHA-256, then swaps the folder in atomically. Files
already present in ``dest`` with a matching hash are reused instead of
re-downloaded. Only the standard library is used so this runs inside the
minimal admin venv on shared hosting.
"""

# this_file: src/fontlab_www_toolkit/mirror.py

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "fontlab-site-manifest/1"
MANIFEST_NAME = "manifest.json"
USER_AGENT = "fontlab-www-toolkit/mirror"
_SIDECARS = ("files.txt", "SHA256SUMS")
DIR_MODE = 0o755
FILE_MODE = 0o644


# Cloudflare (fronting fontlab.dev) appends scripts to every text/html
# response: the bot-detection / JS-detection challenge (`__CF$cv$params`,
# `/cdn-cgi/challenge-platform/...`) and the Web Analytics beacon
# (`static.cloudflareinsights.com/beacon.min.js`). They are not part of the
# published file, so strip them before verifying the hash.
_SCRIPT_TAG = re.compile(rb"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_CDN_MARKERS = (b"__CF$cv$params", b"/cdn-cgi/", b"cloudflareinsights.com")
_HTML_SUFFIXES = (".html", ".htm")


class MirrorError(RuntimeError):
    """Manifest invalid, download failed, or a file failed verification."""


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    commit: str
    built_at: str
    base_url: str
    files: tuple[ManifestFile, ...]
    raw: dict = field(repr=False, compare=False)


@dataclass
class MirrorResult:
    dest: Path
    manifest: Manifest
    downloaded: int = 0
    reused: int = 0
    bytes_downloaded: int = 0
    changed: bool = True


def parse_manifest(data: dict, manifest_url: str = "") -> Manifest:
    """Validate a decoded manifest. Raises :class:`MirrorError` on any problem."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise MirrorError(
            f"unsupported manifest schema: {data.get('schema') if isinstance(data, dict) else data!r}"
        )
    files_raw = data.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise MirrorError("manifest lists no files")
    files: list[ManifestFile] = []
    seen: set[str] = set()
    for entry in files_raw:
        if not isinstance(entry, dict):
            raise MirrorError(f"bad file entry: {entry!r}")
        path = str(entry.get("path", ""))
        _check_relative_path(path)
        if path in seen:
            raise MirrorError(f"duplicate path in manifest: {path}")
        seen.add(path)
        size = entry.get("size")
        sha = str(entry.get("sha256", "")).lower()
        if not isinstance(size, int) or size < 0:
            raise MirrorError(f"bad size for {path}: {size!r}")
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise MirrorError(f"bad sha256 for {path}: {sha!r}")
        files.append(ManifestFile(path=path, size=size, sha256=sha))
    base_url = str(data.get("baseUrl") or "")
    if not base_url and manifest_url:
        base_url = manifest_url.rsplit("/", 1)[0] + "/"
    if not base_url.endswith("/"):
        base_url += "/"
    return Manifest(
        name=str(data.get("name", "")),
        version=str(data.get("version", "")),
        commit=str(data.get("commit", "")),
        built_at=str(data.get("builtAt", "")),
        base_url=base_url,
        files=tuple(files),
        raw=data,
    )


def _check_relative_path(path: str) -> None:
    if not path or path.startswith(("/", "\\")) or "\\" in path:
        raise MirrorError(f"unsafe path in manifest: {path!r}")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise MirrorError(f"unsafe path in manifest: {path!r}")
    if posixpath.normpath(path) != path:
        raise MirrorError(f"unsafe path in manifest: {path!r}")


def strip_cdn_injection(blob: bytes) -> bytes:
    """Remove CDN-injected scripts (Cloudflare challenge/JS-detection) from HTML."""
    return _SCRIPT_TAG.sub(
        lambda m: b"" if any(k in m.group(0) for k in _CDN_MARKERS) else m.group(0), blob
    )


def verify_blob(f: ManifestFile, blob: bytes) -> bytes:
    """Return ``blob`` (possibly cleaned of CDN injection) if it matches ``f``.

    Raises :class:`MirrorError` on size or hash mismatch.
    """
    candidates = [blob]
    if f.path.lower().endswith(_HTML_SUFFIXES):
        cleaned = strip_cdn_injection(blob)
        if cleaned != blob:
            candidates.insert(0, cleaned)
    for cand in candidates:
        if len(cand) == f.size and hashlib.sha256(cand).hexdigest() == f.sha256:
            return cand
    if len(blob) != f.size:
        raise MirrorError(f"size mismatch for {f.path}: expected {f.size}, got {len(blob)}")
    raise MirrorError(f"sha256 mismatch for {f.path}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_bytes(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only by contract
            return resp.read()
    except urllib.error.HTTPError as e:
        raise MirrorError(f"HTTP {e.code} fetching {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MirrorError(f"failed to fetch {url}: {e}") from e


def fetch_manifest(manifest_url: str, timeout: float = 60.0) -> Manifest:
    """Download and validate ``manifest.json`` from ``manifest_url``."""
    if not manifest_url.startswith("https://"):
        raise MirrorError("manifest_url must be https://")
    try:
        data = json.loads(fetch_bytes(manifest_url, timeout).decode("utf-8"))
    except ValueError as e:
        raise MirrorError(f"manifest is not valid JSON: {e}") from e
    return parse_manifest(data, manifest_url)


def mirror(
    manifest_url: str,
    dest: Path,
    *,
    dry_run: bool = False,
    timeout: float = 60.0,
    log: Callable[[str], None] = print,
    fetch: Callable[[str, float], bytes] = fetch_bytes,
) -> MirrorResult:
    """Mirror the folder described by ``manifest_url`` into ``dest``.

    ``dest`` is replaced atomically (rename) once every file has been
    downloaded and verified. Nothing in ``dest`` is touched on failure.
    """
    dest = Path(dest)
    manifest = fetch_manifest(manifest_url, timeout)
    log(
        f"manifest: {manifest.name} {manifest.version} "
        f"commit={manifest.commit[:7] or '?'} built={manifest.built_at or '?'} "
        f"files={len(manifest.files)}"
    )
    result = MirrorResult(dest=dest, manifest=manifest)

    current = _current_state(dest)
    wanted = {f.path: f.sha256 for f in manifest.files}
    if current == wanted and not dry_run:
        log(f"{dest} already matches manifest — nothing to do")
        result.reused = len(manifest.files)
        result.changed = False
        _write_manifest_copy(dest, manifest)
        return result

    if dry_run:
        for f in manifest.files:
            state = "reuse" if current.get(f.path) == f.sha256 else "download"
            log(f"[dry-run] {state:8} {f.path} ({f.size} B)")
        result.changed = current != wanted
        return result

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_root = Path(tempfile.mkdtemp(prefix=f".{dest.name}.tmp-", dir=dest.parent))
    try:
        # mkdtemp() creates 0700 and shared hosts often run with umask 077;
        # the web server must be able to traverse and read the result.
        os.chmod(tmp_root, DIR_MODE)
        for f in manifest.files:
            target = tmp_root / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            _chmod_dirs_upto(target.parent, tmp_root)
            existing = dest / f.path
            if current.get(f.path) == f.sha256 and existing.is_file():
                shutil.copy2(existing, target)
                result.reused += 1
                continue
            url = urllib.parse.urljoin(manifest.base_url, urllib.parse.quote(f.path))
            blob = verify_blob(f, fetch(url, timeout))
            target.write_bytes(blob)
            result.downloaded += 1
            result.bytes_downloaded += len(blob)
            log(f"fetched  {f.path} ({len(blob)} B)")
        for name in _SIDECARS:
            if name in wanted:
                continue
            try:
                (tmp_root / name).write_bytes(
                    fetch(urllib.parse.urljoin(manifest.base_url, name), timeout)
                )
            except MirrorError:
                pass
        _write_manifest_copy(tmp_root, manifest)
        _fix_modes(tmp_root)
        _swap_in(tmp_root, dest)
    except BaseException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    log(
        f"mirrored {len(manifest.files)} files into {dest} ({result.downloaded} downloaded, {result.reused} reused)"
    )
    return result


def _current_state(dest: Path) -> dict[str, str]:
    """Map relative path → sha256 for regular files currently in ``dest``."""
    if not dest.is_dir():
        return {}
    state: dict[str, str] = {}
    for root, _dirs, files in os.walk(dest):
        for name in files:
            p = Path(root) / name
            rel = p.relative_to(dest).as_posix()
            if rel == MANIFEST_NAME or rel in _SIDECARS:
                continue
            state[rel] = _sha256_file(p)
    return state


def _chmod_dirs_upto(d: Path, stop: Path) -> None:
    while d != stop and stop in d.parents:
        os.chmod(d, DIR_MODE)
        d = d.parent


def _fix_modes(root: Path) -> None:
    """World-readable files and traversable dirs, whatever the umask was."""
    os.chmod(root, DIR_MODE)
    for r, dirs, files in os.walk(root):
        for n in dirs:
            os.chmod(Path(r) / n, DIR_MODE)
        for n in files:
            os.chmod(Path(r) / n, FILE_MODE)


def _write_manifest_copy(folder: Path, manifest: Manifest) -> None:
    (folder / MANIFEST_NAME).write_text(json.dumps(manifest.raw, indent=2) + "\n", encoding="utf-8")


def _swap_in(tmp_root: Path, dest: Path) -> None:
    old = dest.with_name(f".{dest.name}.old-{os.getpid()}")
    if dest.exists():
        os.rename(dest, old)
    try:
        os.rename(tmp_root, dest)
    except OSError:
        if old.exists():
            os.rename(old, dest)
        raise
    shutil.rmtree(old, ignore_errors=True)


def manifest_paths(manifest: Manifest) -> Iterable[str]:
    return (f.path for f in manifest.files)
