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

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from markdownify import ATX, markdownify


@dataclass(frozen=True)
class WebflowPage:
    """A Markdown placeholder linked to a Webflow import URL."""

    markdown_path: Path
    public_path: str
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
    webflow_cache: Path
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
            webflow_cache=repo / "wf_cache",
            build_docs=repo / "build_docs",
            public=repo / "public",
            old_pages_config=repo / "src_docs" / "old-pages.yml",
        )


class SiteBuilder:
    """High-level operations used by local scripts and the PHP admin."""

    frontmatter_key: ClassVar[str] = "webflow-import-url"

    def __init__(self, paths: BuildPaths) -> None:
        self.paths = paths

    def load_old_pages(self) -> OldPageMapping | None:
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

    def discover_webflow_pages(self) -> list[WebflowPage]:
        pages: list[WebflowPage] = []
        if not self.paths.markdown.exists():
            return pages
        for markdown_path in sorted(self.paths.markdown.rglob("*.md")):
            meta = parse_frontmatter(markdown_path.read_text(encoding="utf-8"))
            import_url = meta.get(self.frontmatter_key)
            if not import_url:
                continue
            public_path = markdown_to_public_path(markdown_path, self.paths.markdown)
            pages.append(
                WebflowPage(
                    markdown_path=markdown_path,
                    public_path=public_path,
                    import_url=import_url,
                    cache_path=self.paths.webflow_cache / public_path.strip("/") / "index.html",
                )
            )
        return pages

    def pull_webflow(self) -> list[Path]:
        written: list[Path] = []
        for page in self.discover_webflow_pages():
            html = fetch_text(page.import_url)
            page.cache_path.parent.mkdir(parents=True, exist_ok=True)
            page.cache_path.write_text(html, encoding="utf-8")
            written.append(page.cache_path)
        return written

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
            target.write_text(convert_old_html(source, title_from_slug(markdown_name)), encoding="utf-8")
            written.append(target)
        return written

    def build(self, *, pull_webflow: bool = True) -> None:
        if pull_webflow:
            self.pull_webflow()
        self.paths.build_docs.mkdir(parents=True, exist_ok=True)
        self.run_static_builder()
        overlay_directory(self.paths.webflow_cache, self.paths.build_docs)
        overlay_directory(self.paths.static_docs, self.paths.build_docs)
        replace_directory(self.paths.build_docs, self.paths.public)

    def run_static_builder(self) -> None:
        config = self.paths.src_docs / "mkdocs.yml"
        if not config.exists():
            raise FileNotFoundError(f"Missing site config: {config}")
        command = [resolve_executable("properdocs"), "build", "--config-file", str(config), "--clean"]
        try:
            run(command, self.paths.root)
        except FileNotFoundError:
            run([sys.executable, "-m", "mkdocs", "build", "--config-file", str(config), "--clean"], self.paths.root)

    def clean(self) -> None:
        for path in (self.paths.build_docs, self.paths.public):
            if path.exists():
                shutil.rmtree(path)


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return metadata


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


def markdown_to_public_path(markdown_path: Path, markdown_root: Path) -> str:
    relative = markdown_path.relative_to(markdown_root).with_suffix("")
    if relative.name == "index":
        parts = relative.parts[:-1]
    else:
        parts = relative.parts
    return "/" + "/".join(parts) + "/"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "fontlab_www_toolkit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def convert_old_html(source: Path, title: str) -> str:
    html = source.read_text(encoding="utf-8", errors="replace")
    body = extract_old_page_content(remove_html_blocks(extract_body(html), ["script", "style", "noscript", "svg"]))
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
    run([uv, "pip", "install", "--python", str(venv_python(env_path)), "-e", "."], root, env=uv_environment())


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
