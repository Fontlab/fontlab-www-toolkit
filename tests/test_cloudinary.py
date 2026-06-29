"""Tests for Cloudinary URL mapping and responsive-image processing."""

# this_file: tests/test_cloudinary.py

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from fontlab_www_toolkit.builder import (
    BuildPaths,
    SiteBuilder,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _builder() -> SiteBuilder:
    """Minimal SiteBuilder — no config, no filesystem side-effects."""
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
    return SiteBuilder(paths)


_SIMPLE_IMG_HTML = """
<html>
  <body>
    <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />
  </body>
</html>
"""

_CL_MAP = {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"}


def _conf(extra: dict | None = None) -> dict:
    base: dict = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern"},
    }
    if extra:
        base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Inline page-level config override
# ---------------------------------------------------------------------------


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
    # legacy methodology must inject the cloudinary-core script
    assert "cloudinary-core" in processed
    assert "cloudinary.Cloudinary.new({cloud_name: 'custom_cloud'});" in processed


# ---------------------------------------------------------------------------
# URL mapping and responsive treatment
# ---------------------------------------------------------------------------


def test_cloudinary_url_mapping_and_replacement() -> None:
    html = """
    <html>
      <body>
        <img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg"
             srcset="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg 2x" />
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
            "https://i.fontlab.com": "i",
        },
        "cl_trans": "c_limit,w_auto/f_auto,q_auto/",
        "cl_responsive": {"cl_trans_thumb": "c_limit,w_100/f_auto/", "methodology": "modern"},
    }
    processed = _builder().process_html_cloudinary(html, cloudinary_conf)

    # img → responsive class, split src/data-src, srcset cleared
    assert "cld-responsive" in processed
    assert (
        'data-src="https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/vw/photo.jpg"'
        in processed
    )
    assert (
        'src="https://res.cloudinary.com/testcloud/image/upload/c_limit,w_100/f_auto/vw/photo.jpg"'
        in processed
    )
    assert "srcset" not in processed

    # CSS background-image mapped
    assert (
        "background-image: url('https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/v/bg.png')"
        in processed
    )

    # PDF link untouched
    assert 'href="https://i.fontlab.com/doc.pdf"' in processed


def test_cloudinary_svg_uses_simple_static_url() -> None:
    html = (
        "<html><body>"
        '<img id="svg" src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/x.svg">'
        '<img id="png" src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/y.png">'
        '<div style="background-image:url(https://cdn.prod.website-files.com/67c7070e70765599c7796390/bg.svg)"></div>'
        "</body></html>"
    )
    conf = {
        "cl_cloud": "fontlab",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_trans": "c_limit,w_auto/f_auto,q_auto,dpr_auto/",
        "cl_responsive": {"methodology": "modern", "placeholder": "blur"},
    }
    out = _builder().process_html_cloudinary(html, conf)
    soup = BeautifulSoup(out, "html.parser")

    svg = soup.find(id="svg")
    # SVG: simplified f_svg,q_auto URL — no responsive class or data-src
    assert svg["src"] == "https://res.cloudinary.com/fontlab/image/upload/f_svg,q_auto/vw/x.svg"
    assert svg.get("class") is None
    assert svg.get("data-src") is None

    # Raster gets the full responsive treatment
    png = soup.find(id="png")
    assert "cld-responsive" in (png.get("class") or [])
    assert "w_auto" in png["data-src"]

    # CSS SVG reference simplified too
    assert "url(https://res.cloudinary.com/fontlab/image/upload/f_svg,q_auto/vw/bg.svg)" in out


def test_cloudinary_opt_out_attribute_skips_responsive() -> None:
    html = (
        "<html><body>"
        '<img id="out" data-cld-responsive="false" '
        'src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/logo.png">'
        "</body></html>"
    )
    conf = {
        "cl_cloud": "fontlab",
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_trans": "c_limit,w_auto/f_auto,q_auto,dpr_auto/",
        "cl_trans_static": "f_auto,q_auto",
        "cl_responsive": {"methodology": "modern"},
    }
    out = _builder().process_html_cloudinary(html, conf)
    img = BeautifulSoup(out, "html.parser").find(id="out")
    # Static URL only — no responsive class, no data-src, no w_auto
    assert img["src"] == (
        "https://res.cloudinary.com/fontlab/image/upload/f_auto,q_auto/vw/logo.png"
    )
    assert img.get("class") is None
    assert img.get("data-src") is None
    assert "w_auto" not in img["src"]


# ---------------------------------------------------------------------------
# Methodology: legacy vs modern
# ---------------------------------------------------------------------------


def test_cloudinary_responsive_legacy_methodology() -> None:
    cloudinary_conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {
            "methodology": "legacy",
            "cl_core_js": "https://custom.cdn/cloudinary-core.js",
        },
    }
    processed = _builder().process_html_cloudinary(_SIMPLE_IMG_HTML, cloudinary_conf)

    assert (
        '<script src="https://custom.cdn/cloudinary-core.js" type="text/javascript"></script>'
        in processed
    )
    assert "var cl = cloudinary.Cloudinary.new({cloud_name: 'testcloud'});" in processed
    assert "cl.responsive();" in processed


def test_cloudinary_responsive_modern_methodology() -> None:
    cloudinary_conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern"},
    }
    processed = _builder().process_html_cloudinary(_SIMPLE_IMG_HTML, cloudinary_conf)

    assert "ResizeObserver" in processed
    assert "cld-responsive" in processed
    assert "cloudinary-core" not in processed


def test_responsive_script_does_not_clobber_opacity() -> None:
    """Responsive load-in must use ``filter`` (blur) only — not inline ``opacity``."""
    html = (
        "<html><body>"
        '<img src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/photo.jpg" />'
        "</body></html>"
    )
    for lazyload in ("observer", "native"):
        conf = _conf({"cl_responsive": {"methodology": "modern", "lazyload": lazyload}})
        processed = _builder().process_html_cloudinary(html, conf)
        assert "style.opacity" not in processed, lazyload
        assert "opacity 0.4s" not in processed, lazyload
        assert "blur(4px)" in processed, lazyload


# ---------------------------------------------------------------------------
# Lazy-load options
# ---------------------------------------------------------------------------


def test_cloudinary_lazyload_options() -> None:
    b = _builder()

    # lazyload=True → IntersectionObserver + loading=lazy
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern", "lazyload": True},
    }
    processed = b.process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    assert 'loading="lazy"' in processed
    assert "IntersectionObserver" in processed

    # lazyload="native" → loading=lazy, no IntersectionObserver
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern", "lazyload": "native"},
    }
    processed = b.process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    assert 'loading="lazy"' in processed
    assert "IntersectionObserver" not in processed
    assert "ResizeObserver" in processed

    # lazyload="observer" → IntersectionObserver
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern", "lazyload": "observer"},
    }
    processed = b.process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    assert 'loading="lazy"' in processed
    assert "IntersectionObserver" in processed

    # lazyload=False → no lazy attrs
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern", "lazyload": False},
    }
    processed = b.process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    assert 'loading="lazy"' not in processed
    assert "IntersectionObserver" not in processed
    assert "ResizeObserver" in processed


# ---------------------------------------------------------------------------
# Placeholder options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "placeholder,expected_fragment",
    [
        ("blur", "e_blur:2000,f_auto,q_auto:low"),
        ("pixelate", "e_pixelate:100,f_auto,q_auto:low"),
        ("vectorize", "e_vectorize,f_auto,q_auto:low"),
        ("predominant", "c_fill,w_1,h_1/f_auto,q_auto:low"),
        ("predominant-color", "c_fill,w_1,h_1/f_auto,q_auto:low"),
        ("custom-trans-string", "custom-trans-string"),
    ],
)
def test_cloudinary_placeholder_named_options(placeholder: str, expected_fragment: str) -> None:
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern", "placeholder": placeholder},
    }
    processed = _builder().process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    assert expected_fragment in processed


def test_cloudinary_placeholder_false_uses_blank_gif() -> None:
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {"methodology": "modern", "placeholder": False},
    }
    processed = _builder().process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    assert (
        'src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"'
        in processed
    )


# ---------------------------------------------------------------------------
# Accessibility options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "accessibility,expected_trans",
    [
        ("colorblind", "e_assist_colorblind"),
        ("monochrome", "e_grayscale"),
        ("darkmode", "e_brightness_hsb:-30"),
        ("brightmode", "e_brightness_hsb:30"),
        ("custom-acc-effect", "custom-acc-effect"),
    ],
)
def test_cloudinary_accessibility_options(accessibility: str, expected_trans: str) -> None:
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": _CL_MAP,
        "cl_responsive": {
            "methodology": "modern",
            "placeholder": "blur",
            "accessibility": accessibility,
        },
    }
    processed = _builder().process_html_cloudinary(_SIMPLE_IMG_HTML, conf)
    # Effect applied to both high-quality data-src and the placeholder src
    assert f"/{expected_trans}/vw/photo.jpg" in processed
    blur_prefix = "e_blur:2000,f_auto,q_auto:low"
    assert f"{blur_prefix}/{expected_trans}/vw/photo.jpg" in processed


# ---------------------------------------------------------------------------
# Asset exclusions
# ---------------------------------------------------------------------------


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
        "cl_map": {"https://cdn.prod.website-files.com/67c7070e70765599c7796390": "vw"},
        "cl_trans": "c_limit,w_auto/f_auto,q_auto/",
    }
    processed = _builder().process_html_cloudinary(html, conf)

    # CSS, JS, font, PDF, ZIP URLs must remain untouched
    assert (
        'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/css/vexy.webflow.css"'
        in processed
    )
    assert (
        'src="https://cdn.prod.website-files.com/67c7070e70765599c7796390/js/webflow.js"'
        in processed
    )
    assert (
        'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/manifest.json"'
        in processed
    )
    assert (
        "url('https://cdn.prod.website-files.com/67c7070e70765599c7796390/fonts/test.woff2')"
        in processed
    )
    assert 'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/doc.pdf"' in processed
    assert (
        'href="https://cdn.prod.website-files.com/67c7070e70765599c7796390/archive.zip"'
        in processed
    )

    # Image URLs must be replaced
    assert (
        "url('https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/vw/images/bg.png')"
        in processed
    )
    assert (
        'src="https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/vw/images/photo.jpg"'
        in processed
    )


def test_cloudinary_excludes_nested_fetch_urls() -> None:
    html = """
    <html>
      <body>
        <video poster="https://res.cloudinary.com/testcloud/image/fetch/q_60/f_auto/https://i.vexy.art/vl/websiteart/poster.png"></video>
        <img src="https://i.vexy.art/vl/normal.png" />
      </body>
    </html>
    """
    conf = {
        "cl_cloud": "testcloud",
        "cl_map": {"https://i.vexy.art": "v"},
        "cl_trans": "c_limit,w_auto/f_auto,q_auto/",
    }
    processed = _builder().process_html_cloudinary(html, conf)

    # Nested URL inside a fetch/ transform must not be double-mapped
    assert (
        'poster="https://res.cloudinary.com/testcloud/image/fetch/q_60/f_auto/https://i.vexy.art/vl/websiteart/poster.png"'
        in processed
    )
    # Normal image URL must be replaced
    assert (
        'src="https://res.cloudinary.com/testcloud/image/upload/c_limit,w_auto/f_auto,q_auto/v/vl/normal.png"'
        in processed
    )
