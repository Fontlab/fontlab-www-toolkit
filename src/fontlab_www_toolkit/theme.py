"""Load shared theme assets into final HTML without reserializing Webflow pages."""

# this_file: src/fontlab_www_toolkit/theme.py
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


class HeadBoundary(HTMLParser):
    """Record the real closing head token, ignoring raw script/comment content."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=False)
        self.position: tuple[int, int] | None = None
        self.feed(html)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head" and self.position is None:
            self.position = self.getpos()


def asset_tag(url: str) -> str:
    """Parse a stylesheet/script URL into its HTML load instruction."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or any(c in url for c in "<>\"'\n\r"):
        raise ValueError(f"Theme assets require an HTTPS CSS or JS URL: {url!r}")
    if parsed.path.endswith(".css"):
        return f'<link rel="stylesheet" href="{escape(url, quote=True)}">'
    if parsed.path.endswith(".js"):
        return f'<script src="{escape(url, quote=True)}" defer data-cfasync="false"></script>'
    raise ValueError(f"Unsupported theme asset: {url!r}")


def inject_theme_assets(html: str, assets: list[str]) -> str:
    """Idempotently add missing assets; preserve body bytes and HTML fragments."""
    tags = {url: asset_tag(url) for url in assets}
    position = HeadBoundary(html).position if tags else None
    if position is None:
        return html
    line, column = position
    offset = sum(len(part) + 1 for part in html.split("\n")[: line - 1]) + column
    soup = BeautifulSoup(html, "html.parser")
    existing = {tag.get("href") for tag in soup.find_all("link", rel="stylesheet")}
    existing.update(tag.get("src") for tag in soup.find_all("script"))
    missing = [tag for url, tag in tags.items() if url not in existing]
    if not missing:
        return html
    return html[:offset] + "\n".join(missing) + "\n" + html[offset:]


def theme_publish_tree(directory: Path, assets: list[str]) -> None:
    """Apply assets after all overlays, including static and cached HTML pages."""
    if not isinstance(assets, list) or not all(isinstance(url, str) for url in assets):
        raise ValueError("theme_assets must be a list of HTTPS CSS/JS URLs")
    for url in assets:
        asset_tag(url)
    if not assets:
        return
    for path in directory.rglob("*.html"):
        before = path.read_text(encoding="utf-8")
        after = inject_theme_assets(before, assets)
        if before != after:
            path.write_text(after, encoding="utf-8")
