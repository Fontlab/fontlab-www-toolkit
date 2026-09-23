"""Verify shared theme injection after Webflow/static overlays."""

# this_file: tests/test_theme.py
import json
from pathlib import Path

import pytest

from fontlab_www_toolkit.builder import BuildPaths, SiteBuilder
from fontlab_www_toolkit.theme import inject_theme_assets, theme_publish_tree

ASSETS = [
    "https://i.fontlab.com/fltheme26/1.0.0/components.css",
    "https://i.fontlab.com/fltheme26/1.0.0/theme.js",
]


def test_inject_theme_assets_when_webflow_html_then_preserves_body_and_is_idempotent():
    html = '<!doctype html><html><head><title>Webflow</title></head><body data-wf-page="x"><script>const x = "<&>";</script></body></html>'
    result = inject_theme_assets(html, ASSETS)
    assert result[result.index("<body") :] == html[html.index("<body") :], (
        "Webflow body must remain byte-identical"
    )
    assert 'href="' + ASSETS[0] + '"' in result
    assert 'src="' + ASSETS[1] + '" defer data-cfasync="false"' in result
    assert inject_theme_assets(result, ASSETS) == result, (
        "Repeated builds must not duplicate assets"
    )


def test_inject_theme_assets_when_existing_asset_then_adds_only_missing():
    html = f'<html><head><link href="{ASSETS[0]}" rel="stylesheet"></head><body></body></html>'
    result = inject_theme_assets(html, ASSETS)
    assert result.count(ASSETS[0]) == 1
    assert result.count(ASSETS[1]) == 1


def test_inject_theme_assets_when_empty_then_leaves_html_unchanged():
    assert inject_theme_assets("fragment", []) == "fragment"


@pytest.mark.parametrize(
    "asset",
    [
        "javascript:alert(1).js",
        "//example.com/x.css",
        "https://example.com/x.exe",
        'https://example.com/".js',
    ],
)
def test_inject_theme_assets_when_invalid_url_then_fails(asset):
    with pytest.raises(ValueError):
        inject_theme_assets("<head></head>", [asset])


def test_theme_publish_tree_when_overlaid_files_then_updates_each_html(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    for path in [tmp_path / "index.html", tmp_path / "sub/index.html"]:
        path.write_text("<html><head></head><body>Final overlay</body></html>")
    (tmp_path / "asset.txt").write_text("unchanged")
    theme_publish_tree(tmp_path, ASSETS)
    assert all(ASSETS[0] in p.read_text() for p in tmp_path.rglob("*.html"))
    assert (tmp_path / "asset.txt").read_text() == "unchanged"


@pytest.mark.parametrize(
    "content", ['<script>const snippet = "</head>";</script>', "<!-- </head> -->"]
)
def test_inject_theme_assets_when_raw_content_then_skips_false_head_boundary(content):
    html = f"<html><head>{content}</head><body>ok</body></html>"
    result = inject_theme_assets(html, ASSETS)
    assert f"<head>{content}" in result, "Raw script/comment bytes must remain intact"
    assert result.index(ASSETS[0]) > result.index(content) + len(content)


def test_inject_theme_assets_when_fragment_then_leaves_include_unchanged():
    assert (
        inject_theme_assets("<div>Server-side include</div>", ASSETS)
        == "<div>Server-side include</div>"
    )


def test_build_when_static_overlay_replaces_webflow_then_themes_final_content(
    tmp_path: Path, monkeypatch
):
    paths = BuildPaths.from_root(tmp_path)
    for folder in [paths.webflow_cache, paths.static_docs, paths.build_docs]:
        folder.mkdir(parents=True)
    (tmp_path / "fontlab-www-toolkit.json").write_text(json.dumps({"theme_assets": ASSETS}))
    for folder, body in [
        (paths.build_docs, "Markdown"),
        (paths.webflow_cache, "Webflow"),
        (paths.static_docs, "Static overlay"),
    ]:
        (folder / "index.html").write_text(f"<html><head></head><body>{body}</body></html>")
    builder = SiteBuilder(paths)
    monkeypatch.setattr(builder, "run_static_builder", lambda: None)
    builder.build(pull_webflow=False)
    final = (paths.public / "index.html").read_text()
    assert "Static overlay" in final, "Last overlay must retain precedence"
    assert all(url in final for url in ASSETS), "Final published HTML must load shared assets"
