"""Tests for HTML manipulation: badge removal, Google Fonts splitting, Rocket Loader opt-out."""

# this_file: tests/test_html_processing.py

from __future__ import annotations

import re
from pathlib import Path

from fontlab_www_toolkit.builder import (
    BuildPaths,
    SiteBuilder,
    clean_webflow_html,
    exempt_scripts_from_rocket_loader,
    inject_badge_hiding_css,
    split_google_fonts_links,
    strip_webflow_badge,
)

BADGE_HTML = (
    '<a class="w-webflow-badge" href="https://webflow.com?utm_campaign=brandjs">'
    '<img src="https://d3e54v103j8qbb.cloudfront.net/img/webflow-badge-icon-d2.89e12c322e.svg" '
    'alt="" style="margin-right: 4px; width: 26px;">'
    '<img src="https://d3e54v103j8qbb.cloudfront.net/img/webflow-badge-text-d2.c82cec3b78.svg" '
    'alt="Made in Webflow"></a>'
)


def _make_builder() -> SiteBuilder:
    """Minimal SiteBuilder with no config (no cloudinary, etc.)."""
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


# ---------------------------------------------------------------------------
# Webflow badge
# ---------------------------------------------------------------------------


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
    # Idempotent: a second pass must not duplicate the rule
    assert inject_badge_hiding_css(once) == once


def test_inject_badge_hiding_css_when_no_head_then_prepends() -> None:
    html = "<div>only body</div>"
    assert inject_badge_hiding_css(html).startswith("<style>")


def test_clean_webflow_html_applies_both_approaches() -> None:
    html = f"<html><head></head><body>{BADGE_HTML}</body></html>"
    cleaned = clean_webflow_html(html)
    # Badge DOM node removed AND CSS rule injected
    assert "w-webflow-badge" not in cleaned.replace(
        ".w-webflow-badge{display:none !important;}", ""
    )
    assert ".w-webflow-badge{display:none !important;}" in cleaned


# ---------------------------------------------------------------------------
# Google Fonts link splitting
# ---------------------------------------------------------------------------


def test_split_google_fonts_links_splits_multi_family() -> None:
    html = (
        '<head><link rel="stylesheet" href="https://fonts.googleapis.com/css2'
        '?family=Crimson+Pro:wght@400&amp;family=EB+Garamond&amp;display=swap">'
        "</head>"
    )
    out = split_google_fonts_links(html)
    assert out.count("fonts.googleapis.com/css2") == 2
    assert "family=Crimson+Pro:wght@400" in out
    assert "family=EB+Garamond" in out
    # Each resulting link must contain exactly one family parameter
    for link in re.findall(r"css2\?[^\"']*", out):
        assert link.count("family=") == 1
        assert "display=swap" in link


def test_split_google_fonts_links_handles_two_multi_family_links() -> None:
    # Regression: bs4 >=4.13 decompose() nulls a tag's .attrs and can crash a
    # sibling link still held in the live ResultSet.
    html = (
        "<head>"
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
        '?family=Alegreya&amp;family=Outfit&amp;display=swap">'
        '<link rel="stylesheet" href="/local.css">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
        '?family=Commissioner&amp;family=Ysabeau&amp;display=swap">'
        "</head>"
    )
    out = split_google_fonts_links(html)
    links = re.findall(r"css2\?[^\"']*", out)
    assert len(links) == 4
    for link in links:
        assert link.count("family=") == 1
    for family in ("Alegreya", "Outfit", "Commissioner", "Ysabeau"):
        assert f"family={family}" in out
    assert "/local.css" in out


def test_split_google_fonts_links_noop_when_single_family() -> None:
    html = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bona+Nova&amp;display=swap">'
    assert split_google_fonts_links(html) == html


def test_split_google_fonts_links_noop_when_no_google_fonts() -> None:
    html = "<head><link rel=stylesheet href='/style.css'></head>"
    assert split_google_fonts_links(html) == html


# ---------------------------------------------------------------------------
# Cloudflare Rocket Loader opt-out (data-cfasync)
# ---------------------------------------------------------------------------


def test_exempt_scripts_classic_inline_gets_cfasync() -> None:
    html = "<script>console.log('x')</script>"
    out = exempt_scripts_from_rocket_loader(html)
    assert 'data-cfasync="false"' in out


def test_exempt_scripts_module_gets_cfasync() -> None:
    html = '<script type="module" src="/a.js"></script>'
    out = exempt_scripts_from_rocket_loader(html)
    assert 'data-cfasync="false"' in out


def test_exempt_scripts_text_javascript_gets_cfasync() -> None:
    html = '<script type="text/javascript" src="/a.js"></script>'
    out = exempt_scripts_from_rocket_loader(html)
    assert 'data-cfasync="false"' in out


def test_exempt_scripts_application_json_untouched() -> None:
    html = '<script type="application/json">{"a":1}</script>'
    out = exempt_scripts_from_rocket_loader(html)
    assert "data-cfasync" not in out


def test_exempt_scripts_ld_json_untouched() -> None:
    html = '<script type="application/ld+json">{}</script>'
    out = exempt_scripts_from_rocket_loader(html)
    assert "data-cfasync" not in out


def test_exempt_scripts_idempotent_when_already_has_attr() -> None:
    html = '<script data-cfasync="false" src="/a.js"></script>'
    out = exempt_scripts_from_rocket_loader(html)
    assert out.count("data-cfasync") == 1


def test_exempt_scripts_no_scripts_returns_same_object() -> None:
    h = "<p>hi</p>"
    assert exempt_scripts_from_rocket_loader(h) is h


def test_exempt_scripts_mixed_counts_correctly() -> None:
    html = (
        "<script>a()</script>"
        '<script type="module">b()</script>'
        '<script type="application/json">{}</script>'
    )
    out = exempt_scripts_from_rocket_loader(html)
    assert out.count('data-cfasync="false"') == 2


# ---------------------------------------------------------------------------
# Integration through SiteBuilder.process_page_html
# ---------------------------------------------------------------------------


def test_process_page_html_rocket_loader_default_on() -> None:
    """Default config (rocket_loader_optout not set) must inject data-cfasync."""
    builder = _make_builder()
    html = '<html><head></head><body><script type="module">x()</script></body></html>'
    out = builder.process_page_html(html)
    assert 'data-cfasync="false"' in out


def test_process_page_html_rocket_loader_optout_false_skips_injection() -> None:
    """rocket_loader_optout=False must leave scripts untouched."""
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
    builder.config = {"rocket_loader_optout": False}
    html = '<html><head></head><body><script type="module">x()</script></body></html>'
    out = builder.process_page_html(html)
    assert "data-cfasync" not in out
