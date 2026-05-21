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


def test_config_loading_from_file_and_root(tmp_path: Path) -> None:
    # 1. Test explicit config path loading
    config_file = tmp_path / "custom-config.json"
    config_file.write_text('{"user_agent": "custom_agent"}', encoding="utf-8")
    paths = BuildPaths.from_root(tmp_path)
    
    builder = SiteBuilder(paths, config_path=config_file)
    assert builder.config == {"user_agent": "custom_agent"}
    
    # 2. Test default config from root
    root_config = tmp_path / "fontlab-www-toolkit.json"
    root_config.write_text('{"user_agent": "root_agent"}', encoding="utf-8")
    
    builder_default = SiteBuilder(paths)
    assert builder_default.config == {"user_agent": "root_agent"}


def test_page_specific_config_parsing_from_html() -> None:
    html = """
    <html>
      <head>
        <script id="fontlab-toolkit-config" type="application/json">
        {
          "cloudinary": {
            "cl_cloud": "custom_cloud",
            "cl_map": {
              "https://example.com": "ex"
            },
            "cl_responsive": {
              "methodology": "legacy"
            }
          }
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    paths = BuildPaths(
        root=Path("."),
        src_docs=Path("."),
        markdown=Path("."),
        static_docs=Path("."),
        webflow_cache=Path("."),
        build_docs=Path("."),
        public=Path("."),
        old_pages_config=Path("."),
    )
    builder = SiteBuilder(paths)
    processed = builder.process_page_html(html)
    # The processed html should contain the legacy script tags since methodology was overridden to legacy in the page config
    assert "cloudinary-core" in processed
    assert "cloudinary.Cloudinary.new({cloud_name: 'custom_cloud'});" in processed


def test_cloudinary_url_mapping_and_replacement() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" srcset="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg 2x" />
        <div style="background-image: url('https://i.vexy.art/bg.png');"></div>
        <a href="https://i.fontlab.com/doc.pdf">Link</a>
      </body>
    </html>
    """
    cloudinary_conf = {
        "cl_cloud": "testcloud",
        "cl_map": {
            "https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw",
            "https://i.vexy.art": "v",
            "https://i.fontlab.com": "i"
        },
        "cl_trans": "c_limit,w_auto/f_auto,q_auto/",
        "cl_responsive": {
            "cl_trans_thumb": "c_limit,w_100/f_auto/",
            "methodology": "modern"
        }
    }
    paths = BuildPaths(
        root=Path("."), src_docs=Path("."), markdown=Path("."), static_docs=Path("."),
        webflow_cache=Path("."), build_docs=Path("."), public=Path("."), old_pages_config=Path(".")
    )
    builder = SiteBuilder(paths)
    processed = builder.process_html_cloudinary(html, cloudinary_conf)
    
    # img tag should have class cld-responsive, src mapped to thumbnail, data-src mapped to cl_trans, and srcset cleared
    assert "cld-responsive" in processed
    assert "data-src=\"https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/vw/photo.jpg\"" in processed
    assert "src=\"https://res.cloudinary.com/testcloud/image/upload/c_limit,w_100/f_auto/vw/photo.jpg\"" in processed
    assert "srcset" not in processed
    
    # Div style background url should be mapped with normal transformation
    assert "background-image: url('https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/v/bg.png')" in processed
    
    # anchor tag href with non-media (pdf) should remain untouched
    assert "href=\"https://i.fontlab.com/doc.pdf\"" in processed


def test_cloudinary_responsive_legacy_methodology() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />
      </body>
    </html>
    """
    cloudinary_conf = {
        "cl_cloud": "testcloud",
        "cl_map": {
            "https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"
        },
        "cl_responsive": {
            "methodology": "legacy",
            "cl_core_js": "https://custom.cdn/cloudinary-core.js"
        }
    }
    paths = BuildPaths(
        root=Path("."), src_docs=Path("."), markdown=Path("."), static_docs=Path("."),
        webflow_cache=Path("."), build_docs=Path("."), public=Path("."), old_pages_config=Path(".")
    )
    builder = SiteBuilder(paths)
    processed = builder.process_html_cloudinary(html, cloudinary_conf)
    
    # Should include legacy script injection
    assert "<script src=\"https://custom.cdn/cloudinary-core.js\" type=\"text/javascript\"></script>" in processed
    assert "var cl = cloudinary.Cloudinary.new({cloud_name: 'testcloud'});" in processed
    assert "cl.responsive();" in processed


def test_cloudinary_responsive_modern_methodology() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />
      </body>
    </html>
    """
    cloudinary_conf = {
        "cl_cloud": "testcloud",
        "cl_map": {
            "https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"
        },
        "cl_responsive": {
            "methodology": "modern"
        }
    }
    paths = BuildPaths(
        root=Path("."), src_docs=Path("."), markdown=Path("."), static_docs=Path("."),
        webflow_cache=Path("."), build_docs=Path("."), public=Path("."), old_pages_config=Path(".")
    )
    builder = SiteBuilder(paths)
    processed = builder.process_html_cloudinary(html, cloudinary_conf)
    
    # Should include ResizeObserver script injection
    assert "ResizeObserver" in processed
    assert "cld-responsive" in processed
    # But NOT the legacy script or cloudinary-core reference
    assert "cloudinary-core" not in processed


def test_configurable_settings_overrides(tmp_path: Path) -> None:
    # Test frontmatter key and old pages config path overrides
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"frontmatter_key": "custom-import-url", "old_pages_config": "custom-old-pages.yml"}',
        encoding="utf-8"
    )
    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)
    
    # Check frontmatter key
    markdown_dir = tmp_path / "src_docs/md"
    markdown_dir.mkdir(parents=True)
    (markdown_dir / "page.md").write_text(
        "---\ntitle: Page\ncustom-import-url: https://example.test/import\n---\n# Content\n",
        encoding="utf-8"
    )
    pages = builder.discover_webflow_pages()
    assert len(pages) == 1
    assert pages[0].import_url == "https://example.test/import"
    
    # Check old pages config path
    (tmp_path / "custom-old-pages.yml").write_text(
        "old_public: legacy-dir\npages:\n  about.md: about.html\n",
        encoding="utf-8"
    )
    mapping = builder.load_old_pages()
    assert mapping is not None
    assert mapping.old_public == (tmp_path / "legacy-dir").resolve()
    assert mapping.pages == {"about.md": "about.html"}


def test_mkdocs_command_override(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"mkdocs_command": "echo build {config_file}"}',
        encoding="utf-8"
    )
    
    # Setup mock src_docs/mkdocs.yml so run_static_builder doesn't raise FileNotFoundError
    src_docs = tmp_path / "src_docs"
    src_docs.mkdir()
    (src_docs / "mkdocs.yml").write_text("site_name: Test", encoding="utf-8")
    
    paths = BuildPaths.from_root(tmp_path)
    builder = SiteBuilder(paths, config_path=config_file)
    builder.run_static_builder()


def test_cloudinary_lazyload_options() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />
      </body>
    </html>
    """
    
    # 1. lazyload=True (equivalent to "observer" when methodology is "modern")
    conf_observer = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "lazyload": True}
    }
    builder = SiteBuilder(BuildPaths(Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path(".")))
    processed = builder.process_html_cloudinary(html, conf_observer)
    assert 'loading="lazy"' in processed
    assert "IntersectionObserver" in processed
    
    # 2. lazyload="native"
    conf_native = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "lazyload": "native"}
    }
    processed = builder.process_html_cloudinary(html, conf_native)
    assert 'loading="lazy"' in processed
    assert "IntersectionObserver" not in processed
    assert "ResizeObserver" in processed

    # 3. lazyload="observer"
    conf_obs_str = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "lazyload": "observer"}
    }
    processed = builder.process_html_cloudinary(html, conf_obs_str)
    assert 'loading="lazy"' in processed
    assert "IntersectionObserver" in processed

    # 4. lazyload=False
    conf_false = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "lazyload": False}
    }
    processed = builder.process_html_cloudinary(html, conf_false)
    assert 'loading="lazy"' not in processed
    assert "IntersectionObserver" not in processed
    assert "ResizeObserver" in processed


def test_cloudinary_placeholder_options() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />
      </body>
    </html>
    """
    builder = SiteBuilder(BuildPaths(Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path(".")))
    
    # 1. placeholder="blur" -> e_blur:2000,f_auto,q_auto:low
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": "blur"}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "e_blur:2000,f_auto,q_auto:low" in processed

    # 2. placeholder="pixelate" -> e_pixelate:100,f_auto,q_auto:low
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": "pixelate"}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "e_pixelate:100,f_auto,q_auto:low" in processed

    # 3. placeholder="vectorize" -> e_vectorize,f_auto,q_auto:low
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": "vectorize"}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "e_vectorize,f_auto,q_auto:low" in processed

    # 4. placeholder="predominant" -> c_fill,w_1,h_1/f_auto,q_auto:low
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": "predominant"}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "c_fill,w_1,h_1/f_auto,q_auto:low" in processed

    # 5. placeholder="predominant-color" -> c_fill,w_1,h_1/f_auto,q_auto:low
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": "predominant-color"}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "c_fill,w_1,h_1/f_auto,q_auto:low" in processed

    # 6. placeholder="custom-trans-string" -> custom-trans-string
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": "custom-trans-string"}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "custom-trans-string" in processed

    # 7. placeholder=False -> blank GIF
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {"methodology": "modern", "placeholder": False}
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert 'src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"' in processed


def test_cloudinary_accessibility_options() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />
      </body>
    </html>
    """
    builder = SiteBuilder(BuildPaths(Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path(".")))

    # 1. accessibility="colorblind" -> e_assist_colorblind
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {
            "methodology": "modern",
            "placeholder": "blur",
            "accessibility": "colorblind"
        }
    }
    processed = builder.process_html_cloudinary(html, conf)
    # Accessibility effect must be applied to both high-quality source (data-src) and placeholder (src)
    assert "/e_assist_colorblind/vw/photo.jpg" in processed
    assert "e_blur:2000,f_auto,q_auto:low/e_assist_colorblind/vw/photo.jpg" in processed

    # 2. accessibility="monochrome" -> e_grayscale
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {
            "methodology": "modern",
            "placeholder": "blur",
            "accessibility": "monochrome"
        }
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "/e_grayscale/vw/photo.jpg" in processed
    assert "e_blur:2000,f_auto,q_auto:low/e_grayscale/vw/photo.jpg" in processed

    # 3. accessibility="darkmode" -> e_brightness_hsb:-30
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {
            "methodology": "modern",
            "placeholder": "blur",
            "accessibility": "darkmode"
        }
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "/e_brightness_hsb:-30/vw/photo.jpg" in processed
    assert "e_blur:2000,f_auto,q_auto:low/e_brightness_hsb:-30/vw/photo.jpg" in processed

    # 4. accessibility="brightmode" -> e_brightness_hsb:30
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {
            "methodology": "modern",
            "placeholder": "blur",
            "accessibility": "brightmode"
        }
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "/e_brightness_hsb:30/vw/photo.jpg" in processed
    assert "e_blur:2000,f_auto,q_auto:low/e_brightness_hsb:30/vw/photo.jpg" in processed

    # 5. accessibility="custom-acc-effect"
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_responsive": {
            "methodology": "modern",
            "placeholder": "blur",
            "accessibility": "custom-acc-effect"
        }
    }
    processed = builder.process_html_cloudinary(html, conf)
    assert "/custom-acc-effect/vw/photo.jpg" in processed
    assert "e_blur:2000,f_auto,q_auto:low/custom-acc-effect/vw/photo.jpg" in processed


def test_cloudinary_excludes_non_media_assets() -> None:
    html = """
    <html>
      <head>
        <link rel="stylesheet" href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/css/vexy.webflow.css" />
        <script src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/js/webflow.js"></script>
        <link rel="manifest" href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/manifest.json" />
        <style>
          @font-face {
            font-family: 'Test';
            src: url('https://cdn.prod.website-files.com/67c7070e70765599c7796390/fonts/test.woff2') format('woff2');
          }
          .bg {
            background-image: url('https://cdn.prod.website-files.com/67c7070e70765599c7796390/images/bg.png');
          }
        </style>
      </head>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/images/photo.jpg" />
        <a href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/doc.pdf">PDF</a>
        <a href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/archive.zip">ZIP</a>
      </body>
    </html>
    """
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {
            "https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"
        },
        "cl_trans": "c_limit,w_auto/f_auto,q_auto/"
    }
    builder = SiteBuilder(BuildPaths(Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path("."), Path(".")))
    processed = builder.process_html_cloudinary(html, conf)
    
    # CSS link, JS script, font woff2, pdf, and zip urls must remain untouched
    assert 'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/css/vexy.webflow.css"' in processed
    assert 'src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/js/webflow.js"' in processed
    assert 'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/manifest.json"' in processed
    assert "url('https://cdn.prod.website-files.com/67c7070e70765599c7796390/fonts/test.woff2')" in processed
    assert 'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/doc.pdf"' in processed
    assert 'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/archive.zip"' in processed

    # Images must be replaced
    assert "url('https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/vw/images/bg.png')" in processed
    assert 'src="https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/vw/images/photo.jpg"' in processed


