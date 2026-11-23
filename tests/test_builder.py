"""Core tests for the shared FontLab site builder."""

# this_file: tests/test_builder.py

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from vexy_mkdocs_page_import import cache_path

from fontlab_www_toolkit.builder import (
    BuildPaths,
    SiteBuilder,
    WebflowPage,
    convert_old_html,
    extract_markdown_via_url22md,
    extract_old_page_content,
    find_uv,
    overlay_directory,
    parse_flat_yaml,
    publish_directory,
    remove_html_blocks,
    replace_directory,
)

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
    url = "https://x.test/lines"
    frontmatter = (
        f'\ufeff---\r\n# preserve me\r\ntitle: "Vexy Lines"\r\nimport-url: {url}\r\n---  \r\n'
    )
    stub.write_bytes((frontmatter + "\r\nPlaceholder body.\r\n").encode())
    cache = cache_path(tmp_path / "wf_cache", url)
    cache.parent.mkdir()
    cache.write_text("<html><body><h1>Lines</h1></body></html>", encoding="utf-8")

    page = WebflowPage(
        markdown_path=stub,
        import_url="https://x.test/lines",
        cache_path=cache,
    )
    builder = SiteBuilder(BuildPaths.from_root(tmp_path))
    monkeypatch.setattr(
        "fontlab_www_toolkit.builder.extract_markdown_via_url22md",
        lambda *a, **k: "# Lines\n\nExtracted from cache.",
    )
    builder.update_stub(page)

    assert (
        stub.read_bytes() == (frontmatter + "\r\n# Lines\r\n\r\nExtracted from cache.\r\n").encode()
    )


def test_url22md_default_tool_when_unset_then_strict_local_engine() -> None:
    from fontlab_www_toolkit.builder import URL22MD_LOCAL_TOOL

    # Engines 2 and 4 are the only url22md engines with no browser or cloud fallback.
    assert URL22MD_LOCAL_TOOL in {2, 4}, "default url22md engine must not fall back to Playwright"


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
    # Engine 4 is strict readability: local, with no browser or cloud fallback.
    markdown = extract_markdown_via_url22md(cache.read_text(), tool=4, timeout=30)
    assert "Hello" in markdown


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_config_loading_from_file_and_root(tmp_path: Path) -> None:
    # Explicit config path
    config_file = tmp_path / "custom-config.json"
    config_file.write_text('{"url22md_bin": "custom_bin"}', encoding="utf-8")
    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)
    assert builder.config == {"url22md_bin": "custom_bin"}

    # Default config from root
    root_config = tmp_path / "fontlab-www-toolkit.json"
    root_config.write_text('{"url22md_bin": "root_bin"}', encoding="utf-8")
    builder_default = SiteBuilder(paths)
    assert builder_default.config == {"url22md_bin": "root_bin"}


def test_configurable_settings_overrides(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"frontmatter_key": "custom-import-url", "cloudinary": {}, "old_pages_config": "custom-old-pages.yml"}',
        encoding="utf-8",
    )
    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)
    assert len(caplog.records) == 2
    assert "page-import.webflow.cloudinary in src_docs/mkdocs.yml" in caplog.text
    assert "frontmatter_key is ignored" in caplog.text

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
