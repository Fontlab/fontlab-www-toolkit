"""Tests for the shared FontLab site builder."""

# this_file: tests/test_builder.py

from __future__ import annotations

from pathlib import Path

from fontlab_www_toolkit.builder import (
    BuildPaths,
    SiteBuilder,
    clean_webflow_html,
    convert_old_html,
    extract_old_page_content,
    find_uv,
    inject_badge_hiding_css,
    markdown_to_public_path,
    overlay_directory,
    parse_flat_yaml,
    parse_frontmatter,
    remove_html_blocks,
    replace_directory,
    strip_webflow_badge,
)

BADGE_HTML = (
    '<a class="w-webflow-badge" href="https://webflow.com?utm_campaign=brandjs">'
    '<img src="https://d3e54v103j8qbb.cloudfront.net/img/webflow-badge-icon-d2.89e12c322e.svg" '
    'alt="" style="margin-right: 4px; width: 26px;">'
    '<img src="https://d3e54v103j8qbb.cloudfront.net/img/webflow-badge-text-d2.c82cec3b78.svg" '
    'alt="Made in Webflow"></a>'
)


def test_parse_frontmatter_when_webflow_url_present_then_returns_value() -> None:
    text = "---\ntitle: About\nwebflow-import-url: https://example.test/about\n---\n# About\n"
    result = parse_frontmatter(text)
    assert result["webflow-import-url"] == "https://example.test/about"


def test_markdown_to_public_path_when_nested_page_then_matches_site_url() -> None:
    root = Path("src_docs/md")
    page = root / "font-editor/fontlab.md"
    assert markdown_to_public_path(page, root) == "/font-editor/fontlab/"


def test_markdown_to_public_path_when_index_then_drops_index() -> None:
    root = Path("src_docs/md")
    assert markdown_to_public_path(root / "lines/index.md", root) == "/lines/"


def test_discover_webflow_pages_when_placeholder_exists_then_cache_path_matches(tmp_path: Path) -> None:
    markdown = tmp_path / "src_docs/md/font-converter"
    markdown.mkdir(parents=True)
    (markdown / "transtype.md").write_text(
        "---\ntitle: TransType\nwebflow-import-url: https://example.test/transtype\n---\n# T\n",
        encoding="utf-8",
    )
    paths = BuildPaths.from_root(tmp_path)
    pages = SiteBuilder(paths).discover_webflow_pages()
    assert len(pages) == 1
    assert pages[0].cache_path == tmp_path / "wf_cache/font-converter/transtype/index.html"


def test_parse_flat_yaml_when_old_pages_config_then_returns_mapping() -> None:
    text = (
        "old_public: private/legacy/public\n"
        "pages:\n"
        "  cookies.md: cookies/index.html\n"
        "  terms.md: terms/index.html\n"
    )
    result = parse_flat_yaml(text)
    assert result["__old_public__"] == "private/legacy/public"
    assert result["cookies.md"] == "cookies/index.html"
    assert result["terms.md"] == "terms/index.html"


def test_load_old_pages_when_config_present_then_resolves_paths(tmp_path: Path) -> None:
    src = tmp_path / "src_docs"
    src.mkdir()
    (src / "old-pages.yml").write_text(
        "old_public: legacy/public\npages:\n  cookies.md: cookies/index.html\n",
        encoding="utf-8",
    )
    paths = BuildPaths.from_root(tmp_path)
    mapping = SiteBuilder(paths).load_old_pages()
    assert mapping is not None
    assert mapping.old_public == (tmp_path / "legacy/public").resolve()
    assert mapping.pages == {"cookies.md": "cookies/index.html"}


def test_extract_old_page_content_when_main_tag_then_returns_main() -> None:
    html = "<main><p>Body</p></main><footer>x</footer>"
    assert extract_old_page_content(html).strip() == "<p>Body</p>"


def test_remove_html_blocks_when_script_present_then_strips_it() -> None:
    html = "<p>keep</p><script>bad()</script><p>also</p>"
    assert "<script>" not in remove_html_blocks(html, ["script"])


def test_overlay_and_replace_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (src / "sub/file.txt").write_text("hi")
    dst.mkdir()
    overlay_directory(src, dst)
    assert (dst / "sub/file.txt").read_text() == "hi"

    src2 = tmp_path / "src2"
    src2.mkdir()
    (src2 / "x.txt").write_text("y")
    replace_directory(src2, dst)
    assert (dst / "x.txt").read_text() == "y"
    assert not (dst / "sub").exists()


def test_convert_old_html_when_real_page_then_returns_markdown(tmp_path: Path) -> None:
    src = tmp_path / "page.html"
    src.write_text("<html><body><main><h1>Hi</h1><p>Para</p></main></body></html>")
    out = convert_old_html(src, "Hi")
    assert "title: Hi" in out
    assert "# Hi" in out
    assert "Para" in out


def test_find_uv_when_called_then_returns_string() -> None:
    assert isinstance(find_uv(), str)


def test_strip_webflow_badge_when_badge_present_then_removes_anchor() -> None:
    html = f"<body><p>keep</p>{BADGE_HTML}</body>"
    cleaned = strip_webflow_badge(html)
    assert "w-webflow-badge" not in cleaned
    assert "<p>keep</p>" in cleaned


def test_inject_badge_hiding_css_when_head_present_then_inserts_once() -> None:
    html = "<html><head><title>x</title></head><body></body></html>"
    once = inject_badge_hiding_css(html)
    assert ".w-webflow-badge{display:none !important;}" in once
    assert once.lower().index("<style>") < once.lower().index("</head>")
    # Idempotent: a second pass must not duplicate the rule.
    assert inject_badge_hiding_css(once) == once


def test_inject_badge_hiding_css_when_no_head_then_prepends() -> None:
    html = "<div>only body</div>"
    assert inject_badge_hiding_css(html).startswith("<style>")


def test_clean_webflow_html_applies_both_approaches() -> None:
    html = f"<html><head></head><body>{BADGE_HTML}</body></html>"
    cleaned = clean_webflow_html(html)
    assert "w-webflow-badge" not in cleaned.replace(".w-webflow-badge{display:none !important;}", "")
    assert ".w-webflow-badge{display:none !important;}" in cleaned
