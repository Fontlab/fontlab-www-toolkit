"""Build a hybrid site through the toolkit and the installed page-import plugin."""

# this_file: tests/test_page_import.py

import json
import subprocess
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
from vexy_mkdocs_page_import import cache_path, read_cached

from fontlab_www_toolkit.builder import BuildPaths, SiteBuilder

HTML = "<html><head></head><body>Source from origin</body></html>"
ASSETS = ["https://example.org/fly.css", "https://example.org/fly.js"]


@pytest.fixture
def site(tmp_path: Path) -> Iterator[tuple[BuildPaths, str, list[str]]]:
    requests: list[str] = []

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(HTML.encode())

    with HTTPServer(("127.0.0.1", 0), Origin) as server:
        paths = BuildPaths.from_root(tmp_path)
        url = f"http://127.0.0.1:{server.server_port}/source"
        paths.markdown.mkdir(parents=True)
        (paths.src_docs / "mkdocs.yml").write_text(
            "site_name: Fixture\ntheme: materialx\ndocs_dir: md\nsite_dir: ../build_docs\n"
            "plugins:\n  - search\n  - page-import:\n"
            "      offline: !ENV [PAGE_IMPORT_OFFLINE, false]\n"
            "      on_offline_miss: !ENV [PAGE_IMPORT_ON_MISS, error]\n"
            "      cache_dir: ../wf_cache\n      webflow:\n        cloudinary: {}\n"
        )
        (paths.markdown / "index.md").write_text("# Normal page\n")
        (paths.markdown / "imported.md").write_text(f"---\nimport-url: {url}\n---\n# Stub body\n")
        (paths.markdown / "asset.txt").write_text("Original")
        paths.static_docs.mkdir()
        (paths.static_docs / "asset.txt").write_text("Static override")
        (tmp_path / "fontlab-www-toolkit.json").write_text(json.dumps({"theme_assets": ASSETS}))
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield paths, url, requests
        finally:
            server.shutdown()
            thread.join()


def test_build_imports_then_overlays_and_themes(site, monkeypatch):
    paths, _, requests = site
    monkeypatch.setenv("PAGE_IMPORT_OFFLINE", "true")
    legacy = paths.root / "wf_cache/imported/index.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("Legacy path-keyed import")
    SiteBuilder(paths).build()
    assert requests == ["/source"]
    page = (paths.public / "imported/index.html").read_text()
    assert page.endswith("<body>Source from origin</body></html>")
    assert all(page.count(asset) == 1 for asset in ASSETS)
    assert "Normal page" in (paths.public / "index.html").read_text()
    assert (paths.public / "asset.txt").read_text() == "Static override"


def test_skip_webflow_keeps_stub_on_empty_cache_without_network(site, monkeypatch):
    paths, _, requests = site
    monkeypatch.setenv("PAGE_IMPORT_ON_MISS", "error")
    subprocess.run(
        [sys.executable, "-m", "fontlab_www_toolkit", "build", "--skip_webflow"],
        cwd=paths.root,
        check=True,
    )
    assert requests == []
    assert "Stub body" in (paths.public / "imported/index.html").read_text()
    assert not (paths.root / "wf_cache").exists()


def test_pull_refreshes_custom_cache_for_both_url_keys_without_building(site):
    paths, url, requests = site
    config = paths.src_docs / "mkdocs.yml"
    config.write_text(
        config.read_text()
        .replace("../wf_cache", "cache\n      refresh: false")
        .replace("  - search", "  - site-only-plugin")
    )
    (paths.markdown / "webflow.md").write_text(
        f'\ufeff---\nwebflow-import-url: "{url}/wf" # URL\n---\n'
    )
    (paths.markdown / "local.md").write_text("---\ncopy-file: exported.html\n---\n")
    (paths.markdown / "custom.md").write_text(f"---\ncustom-import-url: {url}/unused\n---\n")
    cache = paths.src_docs / "cache"
    cache.mkdir()
    cache_path(cache, url).write_text("previous import")

    result = subprocess.run(
        [sys.executable, "-m", "fontlab_www_toolkit", "pull-webflow"],
        cwd=paths.root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [
        str(cache_path(cache, source).relative_to(paths.root)) for source in [url, url + "/wf"]
    ]
    assert requests == ["/source", "/source/wf"]
    assert read_cached(cache, url) == HTML
    assert read_cached(cache, url + "/wf") == HTML
    assert not paths.build_docs.exists()
    assert not paths.public.exists()


def test_build_update_stubs_indexes_cached_text_and_fetches_only_once(site, monkeypatch):
    paths, url, requests = site
    stub = paths.markdown / "imported.md"
    prefix = stub.read_text().split("# Stub body")[0]

    def extract(html, **kwargs):
        assert html == HTML
        return "Extracted searchable text"

    monkeypatch.setattr("fontlab_www_toolkit.builder.extract_markdown_via_url22md", extract)
    builder = SiteBuilder(paths)
    builder.build(update_stubs=True)
    assert stub.read_text() == prefix + "\nExtracted searchable text\n"
    assert "Extracted searchable text" in (paths.public / "search/search_index.json").read_text()

    original = prefix + "\nOffline edit\n"
    stub.write_text(original)
    builder.build(pull_webflow=False, update_stubs=True)
    assert stub.read_text() == original
    assert requests == ["/source"]
    assert read_cached(paths.root / "wf_cache", url) == HTML
    assert "Source from origin" in (paths.public / "imported/index.html").read_text()


@pytest.mark.parametrize("command", ["build", "pull-webflow"])
@pytest.mark.parametrize("key", ["import-url", "webflow-import-url", "copy-file"])
def test_missing_plugin_names_first_import_stub_and_migration(site, command, key):
    paths, url, requests = site
    config = paths.src_docs / "mkdocs.yml"
    config.write_text(
        config.read_text().split("  - page-import:")[0].replace("docs_dir: md", "docs_dir: pages")
    )
    docs = paths.markdown.rename(paths.src_docs / "pages")
    first = docs / "guide" / "first.markdown"
    first.parent.mkdir()
    first.write_text(f"---\n{key}: {url}\n---\n")

    result = subprocess.run(
        [sys.executable, "-m", "fontlab_www_toolkit", command],
        cwd=paths.root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "guide/first.markdown" in result.stderr
    assert "mkdocs.yml" in result.stderr and "page-import" in result.stderr
    assert "README.md#migrate-a-site-to-page-import" in result.stderr
    assert requests == []
    assert not paths.public.exists()


def test_missing_plugin_without_import_stubs_allows_both_commands(site):
    paths, _, requests = site
    config = paths.src_docs / "mkdocs.yml"
    config.write_text(config.read_text().split("plugins:")[0])
    (paths.markdown / "imported.md").write_text(
        "# Examples\n\nimport-url: is a front-matter key.\n"
    )
    builder = SiteBuilder(paths)
    assert builder.pull_webflow() == []
    builder.build()
    assert "Examples" in (paths.public / "imported/index.html").read_text()
    assert requests == []


def test_pull_webflow_logs_disabled_plugin_and_fetches_nothing(site):
    paths, _, requests = site
    config = paths.src_docs / "mkdocs.yml"
    config.write_text(
        config.read_text().replace("  - page-import:", "  - page-import:\n      enabled: false")
    )
    result = subprocess.run(
        [sys.executable, "-m", "fontlab_www_toolkit", "pull-webflow", "--update_stubs"],
        cwd=paths.root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stderr.splitlines() == ["page-import is disabled. Skipping pull-webflow."]
    assert requests == []
    assert not (paths.root / "wf_cache").exists()
