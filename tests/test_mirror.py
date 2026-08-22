# this_file: tests/test_mirror.py
"""Tests for fontlab_www_toolkit.mirror (manifest-driven HTTP mirroring)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fontlab_www_toolkit import mirror as m

BASE = "https://example.test/site/alpha/"


def _manifest(files: dict[str, bytes], **extra) -> dict:
    return {
        "schema": m.SCHEMA,
        "name": "demo",
        "version": "1.2.3",
        "commit": "abcdef0123456789",
        "builtAt": "2026-08-22T00:00:00Z",
        "baseUrl": BASE,
        "entry": "index.html",
        "files": [
            {"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest(), "type": "x"}
            for p, b in files.items()
        ],
        **extra,
    }


class FakeFetch:
    def __init__(self, files: dict[str, bytes], manifest: dict) -> None:
        self.files = files
        self.manifest = manifest
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        assert url.startswith(BASE), url
        rel = url[len(BASE) :]
        if rel == "manifest.json":
            return json.dumps(self.manifest).encode()
        if rel in self.files:
            return self.files[rel]
        raise m.MirrorError(f"HTTP 404 fetching {url}")


@pytest.fixture
def site() -> dict[str, bytes]:
    return {
        "index.html": b"<html>hi</html>",
        "assets/app.js": b"console.log(1)",
        ".htaccess": b"RewriteEngine On",
    }


def _patched_mirror(monkeypatch, fake: FakeFetch, dest: Path, **kw) -> m.MirrorResult:
    monkeypatch.setattr(m, "fetch_bytes", fake)
    return m.mirror(BASE + "manifest.json", dest, fetch=fake, log=lambda _s: None, **kw)


def test_mirror_when_fresh_dest_then_downloads_everything(tmp_path, monkeypatch, site):
    fake = FakeFetch(site, _manifest(site))
    dest = tmp_path / "out"
    res = _patched_mirror(monkeypatch, fake, dest)
    assert res.downloaded == 3 and res.reused == 0, res
    for p, b in site.items():
        assert (dest / p).read_bytes() == b, f"{p} content mismatch"
    saved = json.loads((dest / "manifest.json").read_text())
    assert saved["commit"] == "abcdef0123456789", "manifest copy must be written into dest"
    assert not list(tmp_path.glob(".out.tmp-*")), "temp dir must be cleaned up"


def test_mirror_when_unchanged_then_noop(tmp_path, monkeypatch, site):
    fake = FakeFetch(site, _manifest(site))
    dest = tmp_path / "out"
    _patched_mirror(monkeypatch, fake, dest)
    fake.calls.clear()
    res = _patched_mirror(monkeypatch, fake, dest)
    assert res.changed is False, "second run must detect no change"
    assert fake.calls == [BASE + "manifest.json"], "only the manifest should be fetched"


def test_mirror_when_one_file_changes_then_reuses_rest(tmp_path, monkeypatch, site):
    fake = FakeFetch(site, _manifest(site))
    dest = tmp_path / "out"
    _patched_mirror(monkeypatch, fake, dest)
    site2 = dict(site, **{"assets/app.js": b"console.log(2)"})
    fake = FakeFetch(site2, _manifest(site2))
    res = _patched_mirror(monkeypatch, fake, dest)
    assert res.downloaded == 1 and res.reused == 2, res
    assert (dest / "assets/app.js").read_bytes() == b"console.log(2)"


def test_mirror_when_sha_mismatch_then_dest_untouched(tmp_path, monkeypatch, site):
    fake = FakeFetch(site, _manifest(site))
    dest = tmp_path / "out"
    _patched_mirror(monkeypatch, fake, dest)
    bad = _manifest(site)
    bad["files"][0]["sha256"] = "0" * 64
    fake = FakeFetch(site, bad)
    with pytest.raises(m.MirrorError, match="sha256 mismatch"):
        _patched_mirror(monkeypatch, fake, dest)
    assert (dest / "index.html").read_bytes() == site["index.html"], (
        "old content must survive a failed run"
    )
    assert not list(tmp_path.glob(".out.tmp-*")), "temp dir must be cleaned up on failure"


def test_mirror_when_removed_file_then_it_disappears(tmp_path, monkeypatch, site):
    fake = FakeFetch(site, _manifest(site))
    dest = tmp_path / "out"
    _patched_mirror(monkeypatch, fake, dest)
    site2 = {k: v for k, v in site.items() if k != "assets/app.js"}
    fake = FakeFetch(site2, _manifest(site2))
    _patched_mirror(monkeypatch, fake, dest)
    assert not (dest / "assets/app.js").exists(), "files absent from the manifest must be removed"


def test_mirror_when_dry_run_then_no_writes(tmp_path, monkeypatch, site):
    fake = FakeFetch(site, _manifest(site))
    dest = tmp_path / "out"
    res = _patched_mirror(monkeypatch, fake, dest, dry_run=True)
    assert res.changed is True and not dest.exists()


@pytest.mark.parametrize("path", ["/etc/passwd", "../x", "a/../b", "a//b", "", "a\\b", "./a"])
def test_parse_manifest_when_unsafe_path_then_error(path):
    data = _manifest({"ok": b"x"})
    data["files"][0]["path"] = path
    with pytest.raises(m.MirrorError, match="unsafe path"):
        m.parse_manifest(data)


def test_parse_manifest_when_wrong_schema_then_error():
    data = _manifest({"ok": b"x"}, schema="other/9")
    with pytest.raises(m.MirrorError, match="schema"):
        m.parse_manifest(data)


def test_parse_manifest_when_no_files_then_error():
    with pytest.raises(m.MirrorError, match="no files"):
        m.parse_manifest({"schema": m.SCHEMA, "files": []})


def test_fetch_manifest_when_not_https_then_error():
    with pytest.raises(m.MirrorError, match="https"):
        m.fetch_manifest("http://example.test/manifest.json")


CF_SNIPPET = (
    b"<script>(function(){function c(){var b=a.contentDocument;}"
    b"d.innerHTML=\"window.__CF$cv$params={r:'abc',t:'MTc4'};a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';\""
    b"})();</script>"
)


def test_verify_blob_when_cloudflare_injected_html_then_stripped_and_accepted():
    original = b"<html><body>hi\n  </body>\n</html>\n"
    served = original.replace(b"</body>", CF_SNIPPET + b"</body>")
    f = m.ManifestFile("index.html", len(original), hashlib.sha256(original).hexdigest())
    assert m.verify_blob(f, served) == original, "CF injection must be stripped before hashing"


def test_verify_blob_when_non_html_mismatch_then_error():
    f = m.ManifestFile("a.js", 2, hashlib.sha256(b"ab").hexdigest())
    with pytest.raises(m.MirrorError, match="size mismatch"):
        m.verify_blob(f, b"abc")


def test_mirror_when_html_injected_then_dest_has_clean_file(tmp_path, monkeypatch, site):
    served = dict(
        site, **{"index.html": site["index.html"].replace(b"</html>", CF_SNIPPET + b"</html>")}
    )
    fake = FakeFetch(served, _manifest(site))
    dest = tmp_path / "out"
    _patched_mirror(monkeypatch, fake, dest)
    assert (dest / "index.html").read_bytes() == site["index.html"]


def test_mirror_when_umask_restrictive_then_web_readable_modes(tmp_path, monkeypatch, site):
    import os
    import stat

    old = os.umask(0o077)
    try:
        fake = FakeFetch(site, _manifest(site))
        dest = tmp_path / "out"
        _patched_mirror(monkeypatch, fake, dest)
    finally:
        os.umask(old)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755, (
        "dest dir must be traversable by the web server"
    )
    assert stat.S_IMODE((dest / "assets").stat().st_mode) == 0o755
    assert stat.S_IMODE((dest / "assets/app.js").stat().st_mode) == 0o644, (
        "files must be world-readable"
    )


def test_strip_cdn_injection_when_beacon_script_then_removed_but_app_scripts_kept():
    app = b'<script type="module" crossorigin src="./assets/index-abc.js"></script>'
    beacon = (
        b'<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/v123" '
        b'integrity="sha512-x" data-cf-beacon=\'{"rayId":"a","version":"2026.8.0","token":"t"}\' crossorigin="anonymous"></script>'
    )
    html = b"<html><head>" + app + b"</head><body>x" + beacon + b"</body></html>"
    assert m.strip_cdn_injection(html) == b"<html><head>" + app + b"</head><body>x</body></html>"
