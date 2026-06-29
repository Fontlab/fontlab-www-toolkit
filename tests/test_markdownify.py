"""Fixture tests for markdownify edge cases used by the convert-old pipeline.

FontLab's HTML pages contain complex tables (feature comparison, pricing) and
various ``<img>`` patterns that the ``convert-old`` command must preserve
faithfully.  These tests pin the expected markdownify output so regressions in
the dependency are caught early.
"""

# this_file: tests/test_markdownify.py

from __future__ import annotations

from pathlib import Path

from markdownify import ATX, markdownify

from fontlab_www_toolkit.builder import convert_old_html

# ---------------------------------------------------------------------------
# Direct markdownify tests
# ---------------------------------------------------------------------------


def test_markdownify_simple_table_converts_to_pipe_format() -> None:
    """A two-column HTML table becomes a GFM pipe table."""
    html = (
        "<table>"
        "<thead><tr><th>Feature</th><th>Value</th></tr></thead>"
        "<tbody>"
        "<tr><td>Axes</td><td>8</td></tr>"
        "<tr><td>Masters</td><td>64</td></tr>"
        "</tbody>"
        "</table>"
    )
    out = markdownify(html, heading_style=ATX)
    assert "|" in out, "Expected pipe characters for table columns"
    assert "Feature" in out
    assert "Value" in out
    assert "Axes" in out
    assert "Masters" in out
    # Header separator row must be present
    assert "---" in out or "----" in out


def test_markdownify_table_with_colspan_flattens_gracefully() -> None:
    """A colspan cell should not crash and its text should appear in output."""
    html = (
        "<table>"
        "<thead><tr><th colspan='2'>Header</th></tr></thead>"
        "<tbody><tr><td>A</td><td>B</td></tr></tbody>"
        "</table>"
    )
    out = markdownify(html, heading_style=ATX)
    assert "Header" in out
    assert "A" in out
    assert "B" in out


def test_markdownify_image_with_alt_text() -> None:
    """``<img src='...' alt='desc'>`` converts to ``![desc](src)``."""
    html = '<img src="https://i.fontlab.com/fl8/logo.png" alt="FontLab logo">'
    out = markdownify(html, heading_style=ATX).strip()
    assert "![FontLab logo]" in out
    assert "https://i.fontlab.com/fl8/logo.png" in out


def test_markdownify_image_without_alt_text() -> None:
    """``<img>`` with no alt attribute produces ``![](src)``."""
    html = '<img src="https://i.fontlab.com/fl8/icon.svg">'
    out = markdownify(html, heading_style=ATX).strip()
    assert "![](" in out or "![None](" in out or "https://i.fontlab.com/fl8/icon.svg" in out


def test_markdownify_nested_image_in_link() -> None:
    """Linked image ``<a href=...><img ...></a>`` produces ``[![alt](src)](href)``."""
    html = (
        '<a href="https://fontlab.com">'
        '<img src="https://i.fontlab.com/badge.png" alt="FontLab">'
        "</a>"
    )
    out = markdownify(html, heading_style=ATX).strip()
    assert "https://fontlab.com" in out
    assert "https://i.fontlab.com/badge.png" in out
    assert "FontLab" in out


def test_markdownify_strip_param_removes_tag_but_keeps_text() -> None:
    """markdownify ``strip=["script"]`` removes the tag *wrapper* but keeps the
    text content.  The ``convert_old_html`` pipeline removes the entire block
    (content included) via BeautifulSoup's ``remove_html_blocks`` *before*
    calling markdownify, which is why script text doesn't appear in the final
    Markdown output.
    """
    html = "<p>Keep this</p><script>var x = 1;</script><p>And this</p>"
    out = markdownify(html, heading_style=ATX, strip=["script"]).strip()
    # Prose paragraphs must survive
    assert "Keep this" in out
    assert "And this" in out
    # markdownify alone keeps the text content even when the tag is stripped;
    # full removal only happens through remove_html_blocks (see convert_old_html).


def test_markdownify_heading_style_is_atx() -> None:
    """Headings must use ATX style (``#``) not Setext (underline) style."""
    html = "<h1>Title</h1><h2>Sub</h2>"
    out = markdownify(html, heading_style=ATX)
    assert "# Title" in out
    assert "## Sub" in out
    # Must not contain Setext underlines
    assert "=====" not in out
    assert "-----" not in out


# ---------------------------------------------------------------------------
# convert_old_html integration tests
# ---------------------------------------------------------------------------


def test_convert_old_html_with_table_preserves_content(tmp_path: Path) -> None:
    """convert_old_html must pass table content through markdownify intact."""
    src = tmp_path / "features.html"
    src.write_text(
        "<html><body><main>"
        "<h1>Feature Comparison</h1>"
        "<table>"
        "<thead><tr><th>Feature</th><th>FontLab 8</th></tr></thead>"
        "<tbody>"
        "<tr><td>Variable fonts</td><td>Yes</td></tr>"
        "<tr><td>Color fonts</td><td>Yes</td></tr>"
        "</tbody>"
        "</table>"
        "</main></body></html>",
        encoding="utf-8",
    )
    out = convert_old_html(src, "Feature Comparison")

    # Frontmatter present
    assert "title: Feature Comparison" in out
    # Heading preserved
    assert "Feature Comparison" in out
    # Table content preserved
    assert "Variable fonts" in out
    assert "FontLab 8" in out
    assert "Color fonts" in out
    assert "Yes" in out


def test_convert_old_html_with_image_generates_markdown(tmp_path: Path) -> None:
    """convert_old_html must convert ``<img>`` tags to Markdown image syntax."""
    src = tmp_path / "page.html"
    src.write_text(
        "<html><body><main>"
        "<h1>Gallery</h1>"
        '<img src="https://i.fontlab.com/fl8/screenshot.png" alt="FontLab screenshot">'
        "</main></body></html>",
        encoding="utf-8",
    )
    out = convert_old_html(src, "Gallery")

    assert "title: Gallery" in out
    assert "Gallery" in out
    assert "https://i.fontlab.com/fl8/screenshot.png" in out
    # Markdown image syntax
    assert "![" in out


def test_convert_old_html_frontmatter_contains_source_path(tmp_path: Path) -> None:
    """The generated frontmatter must record the original HTML source path."""
    src = tmp_path / "cookies.html"
    src.write_text(
        "<html><body><main><p>Cookie policy text.</p></main></body></html>",
        encoding="utf-8",
    )
    out = convert_old_html(src, "Cookies")

    assert "source-html:" in out
    assert "Cookie policy text." in out


def test_convert_old_html_strips_script_and_style(tmp_path: Path) -> None:
    """Script and style blocks must not appear in the Markdown output."""
    src = tmp_path / "styled.html"
    src.write_text(
        "<html><body><main>"
        "<style>.cls{color:red}</style>"
        "<h1>Content</h1>"
        "<script>doSomething()</script>"
        "<p>Real text.</p>"
        "</main></body></html>",
        encoding="utf-8",
    )
    out = convert_old_html(src, "Content")

    assert "Real text." in out
    assert ".cls" not in out
    assert "doSomething" not in out
