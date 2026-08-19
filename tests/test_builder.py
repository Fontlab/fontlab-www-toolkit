"""Core tests for the shared FontLab site builder.

HTML-manipulation tests live in ``test_html_processing.py``.
Cloudinary tests live in ``test_cloudinary.py``.
markdownify fixture tests live in ``test_markdownify.py``.
"""

# this_file: tests/test_builder.py

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fontlab_www_toolkit.builder import (
    BuildPaths,
    SiteBuilder,
    WebflowPage,
    convert_old_html,
    extract_markdown_via_url22md,
    extract_old_page_content,
    find_uv,
    markdown_to_public_path,
    overlay_directory,
    parse_flat_yaml,
    parse_frontmatter,
    publish_directory,
    remove_html_blocks,
    replace_directory,
    split_frontmatter,
)

# ---------------------------------------------------------------------------
# Frontmatter + path helpers
# ---------------------------------------------------------------------------


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


def test_split_frontmatter_when_block_present_then_returns_inner_and_body() -> None:
    text = "---\ntitle: Vexy\nwebflow-import-url: https://x.test/\n---\n\nOld body\n"
    frontmatter, body = split_frontmatter(text)
    assert frontmatter == "title: Vexy\nwebflow-import-url: https://x.test/"
    assert body == "Old body\n"


def test_split_frontmatter_when_no_block_then_returns_none_and_text() -> None:
    text = "# Just a heading\n\nNo frontmatter here.\n"
    frontmatter, body = split_frontmatter(text)
    assert frontmatter is None
    assert body == text


def test_split_frontmatter_preserves_comments_and_quoting() -> None:
    text = '---\n# a comment\ntitle: "Quoted"\n---\nbody\n'
    frontmatter, _ = split_frontmatter(text)
    assert frontmatter == '# a comment\ntitle: "Quoted"'


# ---------------------------------------------------------------------------
# YAML + mapping helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def test_extract_old_page_content_when_main_tag_then_returns_main() -> None:
    html = "<main><p>Body</p></main><footer>x</footer>"
    assert extract_old_page_content(html).strip() == "<p>Body</p>"


def test_remove_html_blocks_when_script_present_then_strips_it() -> None:
    html = "<p>keep</p><script>bad()</script><p>also</p>"
    assert "<script>" not in remove_html_blocks(html, ["script"])


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


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


def test_publish_directory_only_replaces_names_in_source(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "index.html").write_text("new")
    (src / "lines").mkdir()
    (src / "lines" / "index.html").write_text("lines")
    (dst / "vextra" / "nano").mkdir(parents=True)
    (dst / "vextra" / "nano" / "index.html").write_text("hand-managed")
    (dst / "lines").mkdir(parents=True)
    (dst / "lines" / "old.html").write_text("stale")

    publish_directory(src, dst)

    assert (dst / "index.html").read_text() == "new"
    assert (dst / "lines" / "index.html").read_text() == "lines"
    assert not (dst / "lines" / "old.html").exists()
    assert (dst / "vextra" / "nano" / "index.html").read_text() == "hand-managed"


def test_clean_only_removes_names_from_build_docs(tmp_path: Path) -> None:
    (tmp_path / "src_docs" / "md").mkdir(parents=True)
    public = tmp_path / "public"
    (public / "vextra").mkdir(parents=True)
    (public / "vextra" / "keep.txt").write_text("ok")
    (public / "index.html").write_text("built")
    build = tmp_path / "build_docs"
    build.mkdir()
    (build / "index.html").write_text("built")

    SiteBuilder(BuildPaths.from_root(tmp_path)).clean()

    assert not build.exists()
    assert not (public / "index.html").exists()
    assert (public / "vextra" / "keep.txt").read_text() == "ok"


def test_convert_old_html_when_real_page_then_returns_markdown(tmp_path: Path) -> None:
    src = tmp_path / "page.html"
    src.write_text("<html><body><main><h1>Hi</h1><p>Para</p></main></body></html>")
    out = convert_old_html(src, "Hi")
    assert "title: Hi" in out
    assert "# Hi" in out
    assert "Para" in out


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def test_find_uv_when_called_then_returns_string() -> None:
    assert isinstance(find_uv(), str)


# ---------------------------------------------------------------------------
# Webflow page discovery
# ---------------------------------------------------------------------------


def test_discover_webflow_pages_when_placeholder_exists_then_cache_path_matches(
    tmp_path: Path,
) -> None:
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


def test_update_stub_keeps_frontmatter_and_replaces_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = tmp_path / "src_docs/md/lines/index.md"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "---\ntitle: Vexy Lines\nwebflow-import-url: https://x.test/lines\n---\n\nPlaceholder body.\n",
        encoding="utf-8",
    )
    cache = tmp_path / "wf_cache/lines/index.html"
    cache.parent.mkdir(parents=True)
    cache.write_text("<html><body><h1>Lines</h1></body></html>", encoding="utf-8")

    page = WebflowPage(
        markdown_path=stub,
        public_path="/lines/",
        import_url="https://x.test/lines",
        cache_path=cache,
    )
    builder = SiteBuilder(BuildPaths.from_root(tmp_path))
    monkeypatch.setattr(
        "fontlab_www_toolkit.builder.extract_markdown_via_url22md",
        lambda *a, **k: "# Lines\n\nExtracted from cache.",
    )
    builder.update_stub(page)

    result = stub.read_text(encoding="utf-8")
    assert result.startswith(
        "---\ntitle: Vexy Lines\nwebflow-import-url: https://x.test/lines\n---\n\n"
    )
    assert "Extracted from cache." in result
    assert "Placeholder body." not in result


@pytest.mark.skipif(shutil.which("url22md") is None, reason="url22md not installed")
def test_extract_markdown_via_url22md_when_real_binary_then_returns_markdown(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "index.html"
    cache.write_text(
        "<html><head><title>Doc</title></head><body><article>"
        "<h1>Hello</h1><p>This is a reasonably long paragraph of prose so that "
        "the readability extractor recognises it as the main article body.</p>"
        "</article></body></html>",
        encoding="utf-8",
    )
    markdown = extract_markdown_via_url22md(cache, tool=3, timeout=30)
    assert "Hello" in markdown


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_config_loading_from_file_and_root(tmp_path: Path) -> None:
    # Explicit config path
    config_file = tmp_path / "custom-config.json"
    config_file.write_text('{"user_agent": "custom_agent"}', encoding="utf-8")
    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)
    assert builder.config == {"user_agent": "custom_agent"}

    # Default config from root
    root_config = tmp_path / "fontlab-www-toolkit.json"
    root_config.write_text('{"user_agent": "root_agent"}', encoding="utf-8")
    builder_default = SiteBuilder(paths)
    assert builder_default.config == {"user_agent": "root_agent"}


def test_configurable_settings_overrides(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"frontmatter_key": "custom-import-url", "old_pages_config": "custom-old-pages.yml"}',
        encoding="utf-8",
    )
    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)

    markdown_dir = tmp_path / "src_docs/md"
    markdown_dir.mkdir(parents=True)
    (markdown_dir / "page.md").write_text(
        "---\ntitle: Page\ncustom-import-url: https://example.test/import\n---\n# Content\n",
        encoding="utf-8",
    )
    pages = builder.discover_webflow_pages()
    assert len(pages) == 1
    assert pages[0].import_url == "https://example.test/import"

    (tmp_path / "custom-old-pages.yml").write_text(
        "old_public: legacy-dir\npages:\n  about.md: about.html\n", encoding="utf-8"
    )
    mapping = builder.load_old_pages()
    assert mapping is not None
    assert mapping.old_public == (tmp_path / "legacy-dir").resolve()
    assert mapping.pages == {"about.md": "about.html"}


def test_mkdocs_command_override(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text('{"mkdocs_command": "echo build {config_file}"}', encoding="utf-8")

    src_docs = tmp_path / "src_docs"
    src_docs.mkdir()
    (src_docs / "mkdocs.yml").write_text("site_name: Test", encoding="utf-8")

    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)
    builder.run_static_builder()
