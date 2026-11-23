"""Build, conversion, and cache orchestration for FontLab web properties.

Generalised from the original www.fontlab.com builder so a single package can
build every site that follows the FontLab build convention (``src_docs/`` +
``static_docs/`` + Webflow stubs + optional one-time HTML→MD conversion).

Per-site config lives in ``src_docs/old-pages.yml`` (a flat key:value YAML
subset) and may declare:

  old_public: relative/path/to/legacy/public
  pages:
    cookies.md: cookies/index.html
    privacy.md: privacy/index.html
"""

# this_file: src/fontlab_www_toolkit/builder.py

from __future__ import annotations

import functools
import http.server
import json
import logging
import os
import re
import shlex
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import ATX, markdownify
from mkdocs.config.config_options import Plugins
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.utils import is_markdown_file
from mkdocs.utils.meta import get_data
from vexy_mkdocs_page_import import cache_path, import_keys, read_cached, refresh_cache

from .theme import theme_publish_tree


@dataclass(frozen=True)
class WebflowPage:
    """A Markdown placeholder linked to a Webflow import URL."""

    markdown_path: Path
    import_url: str
    cache_path: Path


@dataclass(frozen=True)
class OldPageMapping:
    """One-time HTML→Markdown conversion config for a site."""

    old_public: Path
    pages: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildPaths:
    """Repository paths used by the builder."""

    root: Path
    src_docs: Path
    markdown: Path
    static_docs: Path
    build_docs: Path
    public: Path
    old_pages_config: Path

    @classmethod
    def from_root(cls, root: Path) -> BuildPaths:
        repo = root.resolve()
        return cls(
            root=repo,
            src_docs=repo / "src_docs",
            markdown=repo / "src_docs" / "md",
            static_docs=repo / "static_docs",
            build_docs=repo / "build_docs",
            public=repo / "public",
            old_pages_config=repo / "src_docs" / "old-pages.yml",
        )


class SiteBuilder:
    """High-level operations used by local scripts and the PHP admin."""

    def __init__(self, paths: BuildPaths, config_path: str | Path | None = None) -> None:
        self.paths = paths
        self.config = {}
        if config_path:
            config_p = Path(config_path)
            if not config_p.exists():
                raise FileNotFoundError(f"Configuration file not found: {config_p}")
            self.config = json.loads(config_p.read_text(encoding="utf-8"))
        else:
            default_config = self.paths.root / "fontlab-www-toolkit.json"
            if default_config.exists():
                self.config = json.loads(default_config.read_text(encoding="utf-8"))

        log = logging.getLogger(__name__)
        if "cloudinary" in self.config:
            log.warning("Move cloudinary to page-import.webflow.cloudinary in src_docs/mkdocs.yml")
        if "frontmatter_key" in self.config:
            log.warning("frontmatter_key is ignored. Use the fixed page-import front-matter keys.")

    def load_old_pages(self) -> OldPageMapping | None:
        config_path_str = self.config.get("old_pages_config")
        if config_path_str:
            config = (self.paths.root / config_path_str).resolve()
        else:
            config = self.paths.old_pages_config

        if not config.exists():
            return None
        data = parse_flat_yaml(config.read_text(encoding="utf-8"))
        old_public_raw = data.get("__old_public__", "")
        pages = {k: v for k, v in data.items() if not k.startswith("__")}
        if not old_public_raw or not pages:
            return None
        old_public = (self.paths.root / old_public_raw).resolve()
        return OldPageMapping(old_public=old_public, pages=pages)

    def pull_webflow(self, *, update_stubs: bool = False) -> list[Path]:
        """Refresh the plugin's source cache without running a static build."""
        return self._sync_url_stubs(refresh=True, update_stubs=update_stubs)

    def _sync_url_stubs(self, *, refresh: bool, update_stubs: bool) -> list[Path]:
        docs, selected = _page_import_entries(self.paths.src_docs / "mkdocs.yml")
        plugin = Plugins().validate(selected).get("page-import")
        if plugin is None:
            if selected and refresh:
                logging.getLogger(__name__).warning(
                    "page-import is disabled. Skipping pull-webflow."
                )
            return []
        options = plugin.config
        cache_dir = (self.paths.src_docs / options.cache_dir).resolve()
        written: list[Path] = []
        for path in sorted(docs.rglob("*.md")):
            _, meta = get_data(path.read_text(encoding="utf-8-sig"))
            try:
                source = import_keys(meta)
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            if source is None or source[0] == "copy-file":
                continue
            url = source[1]
            cached = cache_path(cache_dir, url)
            if refresh:
                try:
                    refresh_cache(
                        url, cache_dir, timeout=options.timeout, max_bytes=options.max_bytes
                    )
                except (OSError, ValueError) as exc:
                    raise RuntimeError(f"Failed to refresh {path}: {exc}") from exc
                written.append(cached)
            if update_stubs:
                page = WebflowPage(path, url, cached)
                if self.update_stub(page):
                    written.append(path)
        return written

    def update_stub(self, page: WebflowPage) -> bool:
        """Replace the stub body when cached source HTML yields changed Markdown."""
        html = read_cached(page.cache_path.parent, page.import_url)
        if html is None:
            return False
        original = page.markdown_path.read_bytes().decode("utf-8")
        old_body, meta = get_data(original.removeprefix("\ufeff").replace("\r\n", "\n"))
        if not import_keys(meta):
            raise ValueError(f"{page.markdown_path}: missing import front matter")
        # Slice the original lines so comments, quotes and CRLF survive exactly.
        lines = original.splitlines(keepends=True)
        header = "".join(lines[: len(lines) - len(old_body.splitlines())]).rstrip("\r\n")
        body = extract_markdown_via_url22md(
            html,
            tool=self.config.get("url22md_tool", URL22MD_LOCAL_TOOL),
            bin_path=self.config.get("url22md_bin"),
            timeout=int(self.config.get("url22md_timeout", 60)),
        ).strip()
        newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
        updated = header + newline * 2 + body.replace("\n", newline) + newline
        if updated == original:
            return False
        page.markdown_path.write_bytes(updated.encode("utf-8"))
        return True

    def convert_old_pages(self) -> list[Path]:
        mapping = self.load_old_pages()
        if mapping is None:
            return []
        written: list[Path] = []
        for markdown_name, old_relative in mapping.pages.items():
            source = mapping.old_public / old_relative
            if not source.exists():
                raise FileNotFoundError(f"Missing old page source: {source}")
            target = self.paths.markdown / markdown_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                convert_old_html(source, title_from_slug(markdown_name)), encoding="utf-8"
            )
            written.append(target)
        return written

    def build(self, *, pull_webflow: bool = True, update_stubs: bool = False) -> None:
        self.paths.build_docs.mkdir(parents=True, exist_ok=True)
        self.run_static_builder(offline=not pull_webflow)
        if pull_webflow and update_stubs and self._sync_url_stubs(refresh=False, update_stubs=True):
            # Re-index the rewritten Markdown using the HTML already fetched in the first pass.
            self.run_static_builder(offline=True)
        overlay_directory(self.paths.static_docs, self.paths.build_docs)
        theme_publish_tree(self.paths.build_docs, self.config.get("theme_assets", []))
        publish_directory(self.paths.build_docs, self.paths.public)

    def run_static_builder(self, *, offline: bool = False) -> None:
        config_file = self.paths.src_docs / "mkdocs.yml"
        if not config_file.exists():
            raise FileNotFoundError(f"Missing site config: {config_file}")

        _page_import_entries(config_file)
        env = {**os.environ, "PAGE_IMPORT_OFFLINE": "true" if offline else "false"}
        if offline:
            env["PAGE_IMPORT_ON_MISS"] = "keep"
        custom_cmd = self.config.get("mkdocs_command")
        if custom_cmd:
            if isinstance(custom_cmd, str):
                cmd_str = custom_cmd.format(config_file=str(config_file))
                cmd = shlex.split(cmd_str)
            else:
                cmd = [str(arg).format(config_file=str(config_file)) for arg in custom_cmd]
            run(cmd, self.paths.root, env=env)
        else:
            command = [
                resolve_executable("properdocs"),
                "build",
                "--config-file",
                str(config_file),
                "--clean",
            ]
            try:
                run(command, self.paths.root, env=env)
            except FileNotFoundError:
                run(
                    [
                        sys.executable,
                        "-m",
                        "mkdocs",
                        "build",
                        "--config-file",
                        str(config_file),
                        "--clean",
                    ],
                    self.paths.root,
                    env=env,
                )

    def clean(self) -> None:
        if self.paths.build_docs.exists():
            if self.paths.public.exists():
                for item in self.paths.build_docs.iterdir():
                    target = self.paths.public / item.name
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists():
                        target.unlink()
            shutil.rmtree(self.paths.build_docs)


def _page_import_entries(config_file: Path) -> tuple[Path, list]:
    """Read the import configuration and flag stubs that would silently render as Markdown."""
    site = MkDocsConfig(config_file_path=str(config_file))
    with config_file.open("rb") as stream:
        site.load_file(stream)
    entries = site["plugins"]
    if isinstance(entries, dict):
        entries = [{key: value} for key, value in entries.items()]
    selected = [
        entry
        for entry in entries
        if entry in ("page-import", "/page-import")
        or isinstance(entry, dict)
        and ("page-import" in entry or "/page-import" in entry)
    ]
    docs = config_file.parent / site.docs_dir
    if not selected:
        markdown = (p for p in docs.rglob("*") if is_markdown_file(p.name) and p.is_file())
        for path in sorted(markdown):
            _, meta = get_data(path.read_text(encoding="utf-8-sig"))
            if meta.keys() & {"import-url", "webflow-import-url", "copy-file"}:
                raise ValueError(
                    f"{path} declares an import, but {config_file} has no page-import entry. "
                    "See README.md#migrate-a-site-to-page-import."
                )
    return docs, selected


# url22md engine 2 is strict trafilatura: local, with no fallback. Engines 1 and 3
# fall back to 5 (Playwright, which launches headless Chromium) and then to cloud tools.
URL22MD_LOCAL_TOOL = 2


def extract_markdown_via_url22md(
    html: str,
    *,
    tool: int | None = URL22MD_LOCAL_TOOL,
    bin_path: str | None = None,
    timeout: int = 60,
) -> str:
    """Extract Markdown from cached source HTML using ``url22md``.

    ``url22md`` only accepts HTTP(S) URLs, so the cached file's directory is
    served over a short-lived loopback HTTP server and the tool is pointed at
    it. ``tool`` forces a specific extraction engine. The default,
    ``URL22MD_LOCAL_TOOL``, keeps extraction local and deterministic. Pass
    ``None`` to let url22md run its full fallback chain, which launches headless
    Chromium and may reach cloud tools.
    """
    binary = bin_path or shutil.which("url22md")
    if not binary:
        raise FileNotFoundError(
            "url22md executable not found; install it or set 'url22md_bin' in config"
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Serve a noise-stripped copy so extractors don't capture inline JS/CSS
        # or hidden Webflow "Windflow" plugin metadata (which stores the
        # Tailwind config as visible div text) as page "prose".
        cleaned = strip_extraction_noise(html)
        served = tmp_dir / "page.html"
        served.write_text(cleaned, encoding="utf-8")
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        handler = functools.partial(_QuietHTTPRequestHandler, directory=str(tmp_dir))
        with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                url = f"http://127.0.0.1:{port}/{served.name}"
                command = [binary, "--url", url, "--output_dir", str(out_dir), "--Force", "True"]
                if tool is not None:
                    command += ["--tool", str(tool)]
                run([*command, "--Timeout", str(timeout)], tmp_dir)
            finally:
                httpd.shutdown()
        produced = sorted(out_dir.glob("*.md"))
        if not produced:
            raise RuntimeError("url22md produced no Markdown for the cached page")
        return produced[0].read_text(encoding="utf-8")


class _QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """``SimpleHTTPRequestHandler`` that does not log requests to stderr."""

    def log_message(self, *args: object) -> None:  # noqa: D102
        return


def parse_flat_yaml(text: str) -> dict[str, str]:
    """Parse a flat-key YAML subset used by old-pages.yml.

    Supported:
      old_public: path/here
      pages:
        cookies.md: cookies/index.html
        terms.md: terms/index.html

    The ``old_public`` value is stored under the reserved key
    ``__old_public__`` in the returned dict; entries inside ``pages:`` are
    stored at the top level.
    """
    result: dict[str, str] = {}
    in_pages = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(" ") or raw.startswith("\t"):
            if not in_pages:
                continue
            line = raw.strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("\"'")
            continue
        in_pages = False
        line = raw.strip()
        if line == "pages:":
            in_pages = True
            continue
        if line.startswith("old_public:"):
            _, value = line.split(":", 1)
            result["__old_public__"] = value.strip().strip("\"'")
    return result


def convert_old_html(source: Path, title: str) -> str:
    html = source.read_text(encoding="utf-8", errors="replace")
    body = extract_old_page_content(
        remove_html_blocks(extract_body(html), ["script", "style", "noscript", "svg"])
    )
    markdown = markdownify(
        body,
        heading_style=ATX,
        strip=["script", "style", "noscript", "svg"],
    ).strip()
    return f"---\ntitle: {title}\nsource-html: {display_path(source)}\n---\n\n{markdown}\n"


def extract_body(html: str) -> str:
    lower = html.lower()
    start = lower.find("<body")
    if start == -1:
        return html
    start = html.find(">", start)
    end = lower.rfind("</body>")
    if start == -1:
        return html
    if end == -1:
        end = len(html)
    return html[start + 1 : end]


def extract_old_page_content(html: str) -> str:
    return extract_first_tag(html, "main") or extract_first_tag(html, "article") or html


def extract_first_tag(html: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def strip_extraction_noise(html: str) -> str:
    """Remove non-prose nodes before Markdown extraction.

    Drops ``<script>``/``<style>``/``<noscript>`` and any element carrying a
    ``windflow-*`` attribute. The latter targets the Webflow *Windflow* plugin's
    hidden metadata file (``<div class="…-windflow-file" windflow-meta="true">``),
    which stores a full Tailwind config as ``display:none`` div text that
    extractors otherwise mistake for the page body.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(True):
        if any(str(attr).startswith("windflow-") for attr in (tag.attrs or {})):
            tag.decompose()
    return str(soup)


def remove_html_blocks(html: str, tags: list[str]) -> str:
    cleaned = html
    for tag in tags:
        pattern = re.compile(rf"<{tag}\b[^>]*>.*?</{tag}>", re.IGNORECASE | re.DOTALL)
        cleaned = pattern.sub("", cleaned)
    return cleaned


def title_from_slug(markdown_name: str) -> str:
    slug = Path(markdown_name).stem
    initialisms = {"eula": "EULA"}
    if slug in initialisms:
        return initialisms[slug]
    return slug.replace("-", " ").title()


def display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def overlay_directory(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    for item in source.rglob("*"):
        target = destination / item.relative_to(source)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def publish_directory(source: Path, destination: Path) -> None:
    """Write ``source`` into ``destination``.

    Only names that exist in ``source`` are replaced. Anything else already
    in ``destination`` (hand-managed trees, leftover files) is left alone.
    """
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def replace_directory(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True, env=env)


def resolve_executable(name: str) -> str:
    local = Path(sys.executable).resolve().parent / name
    if local.exists():
        return str(local)
    return name


def setup_environment(root: Path, venv: Path | None = None, *, clear: bool = False) -> None:
    uv = find_uv()
    env_path = venv or root / ".venv"
    python = venv_python(env_path)
    if clear or not python.exists():
        command = [uv, "venv", str(env_path), "--python", "3.12"]
        if clear:
            command.append("--clear")
        run(command, root, env=uv_environment())
    run(
        [uv, "pip", "install", "--python", str(venv_python(env_path)), "-e", "."],
        root,
        env=uv_environment(),
    )


def venv_python(venv: Path) -> Path:
    unix_python = venv / "bin" / "python"
    if unix_python.exists():
        return unix_python
    return venv / "Scripts" / "python.exe"


def find_uv() -> str:
    configured = os.environ.get("UV_BIN")
    if configured:
        return os.path.expanduser(configured)
    found = shutil.which("uv")
    if found:
        return found
    home_uv = Path.home() / ".local/bin/uv"
    if home_uv.exists():
        return str(home_uv)
    return "uv"


def uv_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("RAYON_NUM_THREADS", "1")
    env.setdefault("UV_CONCURRENT_BUILDS", "1")
    env.setdefault("UV_CONCURRENT_DOWNLOADS", "1")
    env.setdefault("UV_CONCURRENT_INSTALLS", "1")
    return env
