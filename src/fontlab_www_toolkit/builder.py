"""Build, conversion, and cache orchestration for FontLab web properties.

Generalised from the original www.fontlab.com builder so a single package can
build every site that follows the FontLab build convention (``src_docs/`` +
``static_docs/`` + Webflow stubs + optional one-time HTML→MD conversion).

Per-site config lives in ``src_docs/old-pages.yml`` (a flat key:value YAML
subset) and may declare:

  old_public: relative/path/to/legacy/public
  pages:
    cookies.md: cookies/index.html
    privacy.md: privacy/index.html
"""

# this_file: src/fontlab_www_toolkit/builder.py

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import shlex
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from bs4 import BeautifulSoup
from markdownify import ATX, markdownify


@dataclass(frozen=True)
class WebflowPage:
    """A Markdown placeholder linked to a Webflow import URL."""

    markdown_path: Path
    public_path: str
    import_url: str
    cache_path: Path


@dataclass(frozen=True)
class OldPageMapping:
    """One-time HTML→Markdown conversion config for a site."""

    old_public: Path
    pages: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildPaths:
    """Repository paths used by the builder."""

    root: Path
    src_docs: Path
    markdown: Path
    static_docs: Path
    webflow_cache: Path
    build_docs: Path
    public: Path
    old_pages_config: Path

    @classmethod
    def from_root(cls, root: Path) -> BuildPaths:
        repo = root.resolve()
        return cls(
            root=repo,
            src_docs=repo / "src_docs",
            markdown=repo / "src_docs" / "md",
            static_docs=repo / "static_docs",
            webflow_cache=repo / "wf_cache",
            build_docs=repo / "build_docs",
            public=repo / "public",
            old_pages_config=repo / "src_docs" / "old-pages.yml",
        )


class SiteBuilder:
    """High-level operations used by local scripts and the PHP admin."""

    frontmatter_key: ClassVar[str] = "webflow-import-url"

    def __init__(self, paths: BuildPaths, config_path: str | Path | None = None) -> None:
        self.paths = paths
        self.config = {}
        if config_path:
            config_p = Path(config_path)
            if not config_p.exists():
                raise FileNotFoundError(f"Configuration file not found: {config_p}")
            self.config = json.loads(config_p.read_text(encoding="utf-8"))
        else:
            default_config = self.paths.root / "fontlab-www-toolkit.json"
            if default_config.exists():
                self.config = json.loads(default_config.read_text(encoding="utf-8"))

    def load_old_pages(self) -> OldPageMapping | None:
        config_path_str = self.config.get("old_pages_config")
        if config_path_str:
            config = (self.paths.root / config_path_str).resolve()
        else:
            config = self.paths.old_pages_config

        if not config.exists():
            return None
        data = parse_flat_yaml(config.read_text(encoding="utf-8"))
        old_public_raw = data.get("__old_public__", "")
        pages = {k: v for k, v in data.items() if not k.startswith("__")}
        if not old_public_raw or not pages:
            return None
        old_public = (self.paths.root / old_public_raw).resolve()
        return OldPageMapping(old_public=old_public, pages=pages)

    def discover_webflow_pages(self) -> list[WebflowPage]:
        pages: list[WebflowPage] = []
        if not self.paths.markdown.exists():
            return pages
        frontmatter_key = self.config.get("frontmatter_key", self.frontmatter_key)
        for markdown_path in sorted(self.paths.markdown.rglob("*.md")):
            meta = parse_frontmatter(markdown_path.read_text(encoding="utf-8"))
            import_url = meta.get(frontmatter_key)
            if not import_url:
                continue
            public_path = markdown_to_public_path(markdown_path, self.paths.markdown)
            pages.append(
                WebflowPage(
                    markdown_path=markdown_path,
                    public_path=public_path,
                    import_url=import_url,
                    cache_path=self.paths.webflow_cache / public_path.strip("/") / "index.html",
                )
            )
        return pages

    def process_page_html(self, html: str) -> str:
        # 1. Parse inline config from HTML if present
        page_config = {}
        try:
            soup_temp = BeautifulSoup(html, "html.parser")
            script = soup_temp.find("script", id="fontlab-toolkit-config", type="application/json")
            if script and script.string:
                page_config = json.loads(script.string.strip())
        except Exception:
            pass

        # 2. Merge configs: page_config overrides self.config
        effective_config = {}
        effective_config.update(self.config)
        if "cloudinary" in self.config and "cloudinary" in page_config:
            merged_cloudinary = {}
            merged_cloudinary.update(self.config["cloudinary"])
            merged_cloudinary.update(page_config["cloudinary"])
            effective_config["cloudinary"] = merged_cloudinary
        elif "cloudinary" in page_config:
            effective_config["cloudinary"] = page_config["cloudinary"]

        for k, v in page_config.items():
            if k != "cloudinary":
                effective_config[k] = v

        # 3. Clean Webflow HTML badge and inject hiding CSS
        hide_css = effective_config.get("webflow_badge_hide_css", WEBFLOW_BADGE_HIDE_CSS)
        html = inject_badge_hiding_css(strip_webflow_badge(html), hide_css=hide_css)

        # 4. Split multi-family Google Fonts links into one link per family, so a
        #    downstream step that truncates the URL at the first '&' can't drop
        #    fonts (a single ?family=X load still works without &display=swap).
        if effective_config.get("split_google_fonts", True):
            html = split_google_fonts_links(html)

        # 5. Cloudinary replacements & responsive images
        cloudinary_conf = effective_config.get("cloudinary")
        if cloudinary_conf:
            html = self.process_html_cloudinary(html, cloudinary_conf)

        return html

    def process_html_cloudinary(self, html: str, cloudinary_conf: dict) -> str:
        cl_cloud = cloudinary_conf.get("cl_cloud", "fontlab")
        cl_map = cloudinary_conf.get("cl_map", {})
        if not cl_map:
            return html

        cl_trans = cloudinary_conf.get("cl_trans", "c_limit,w_auto/f_auto,q_auto,dpr_auto/")

        # SVG images skip the responsive width chain entirely — vector art has no
        # pixel width to optimise, so `w_auto`/`dpr_auto` are meaningless. They get
        # a minimal `f_svg,q_auto` transform instead. `cl_trans_static` is the
        # non-responsive fallback used for images the author opts out of the
        # responsive script (see ``data-cld-responsive="false"`` below).
        cl_trans_svg = cloudinary_conf.get("cl_trans_svg", "f_svg,q_auto")
        cl_trans_static = cloudinary_conf.get("cl_trans_static", "f_auto,q_auto")

        cl_responsive = cloudinary_conf.get("cl_responsive")
        cl_responsive_enabled = bool(cl_responsive)
        if cl_responsive_enabled and not isinstance(cl_responsive, dict):
            cl_responsive = {}

        if cl_responsive_enabled:
            cl_trans_thumb = cl_responsive.get("cl_trans_thumb", "c_limit,w_128/f_auto,q_1/")
            methodology = cl_responsive.get("methodology", "modern")
        else:
            cl_trans_thumb = ""
            methodology = ""

        # Extract lazyload, placeholder, and accessibility settings
        lazyload = (
            cl_responsive.get("lazyload")
            if cl_responsive_enabled
            else cloudinary_conf.get("lazyload")
        )
        placeholder = (
            cl_responsive.get("placeholder")
            if cl_responsive_enabled
            else cloudinary_conf.get("placeholder")
        )
        accessibility = (
            cl_responsive.get("accessibility")
            if cl_responsive_enabled
            else cloudinary_conf.get("accessibility")
        )

        # Determine effective lazyload setting
        effective_lazyload = "false"
        if lazyload is True:
            effective_lazyload = "observer" if methodology == "modern" else "native"
        elif isinstance(lazyload, str):
            effective_lazyload = lazyload.lower()

        # Determine effective placeholder setting
        placeholder_mapping = {
            "blur": "e_blur:2000,f_auto,q_auto:low",
            "pixelate": "e_pixelate:100,f_auto,q_auto:low",
            "vectorize": "e_vectorize,f_auto,q_auto:low",
            "predominant": "c_fill,w_1,h_1/f_auto,q_auto:low",
            "predominant-color": "c_fill,w_1,h_1/f_auto,q_auto:low",
        }

        placeholder_trans = ""
        use_blank_placeholder = False

        if placeholder is False:
            use_blank_placeholder = True
        elif isinstance(placeholder, str):
            placeholder_trans = placeholder_mapping.get(placeholder.lower(), placeholder)
        else:
            placeholder_trans = cl_trans_thumb if cl_trans_thumb else "c_limit,w_128/f_auto,q_1/"

        # Determine effective accessibility setting
        accessibility_mapping = {
            "colorblind": "e_assist_colorblind",
            "monochrome": "e_grayscale",
            "darkmode": "e_brightness_hsb:-30",
            "brightmode": "e_brightness_hsb:30",
        }
        accessibility_trans = ""
        if isinstance(accessibility, str):
            accessibility_trans = accessibility_mapping.get(accessibility.lower(), accessibility)

        # Prepare accessibility suffix
        acc_suffix = ""
        if accessibility_trans:
            acc_suffix = accessibility_trans
            if not acc_suffix.endswith("/"):
                acc_suffix += "/"

        # Construct effective transformations
        effective_cl_trans = cl_trans
        if acc_suffix:
            if not effective_cl_trans.endswith("/"):
                effective_cl_trans += "/"
            effective_cl_trans += acc_suffix

        effective_placeholder_trans = placeholder_trans
        if acc_suffix and effective_placeholder_trans:
            if not effective_placeholder_trans.endswith("/"):
                effective_placeholder_trans += "/"
            effective_placeholder_trans += acc_suffix

        soup = BeautifulSoup(html, "html.parser")

        # Iterate over all tags in the document (except script)
        for tag in soup.find_all(True):
            if tag.name == "script":
                continue

            # 1. Process <img> tags specifically if responsive is enabled
            if tag.name == "img" and tag.get("src"):
                src_val = tag["src"]
                matched_prefix = None
                for prefix in cl_map:
                    if src_val.startswith(prefix):
                        matched_prefix = prefix
                        break

                if matched_prefix:
                    # SVGs, images opted out via data-cld-responsive="false", and
                    # all images when responsive mode is off get a plain static
                    # URL and stay out of the responsive class/script: the script
                    # only ever touches img.cld-responsive, so omitting the class
                    # is the compliant way to exclude an image.
                    is_svg = is_svg_url(src_val)
                    opt_out = (
                        str(tag.get("data-cld-responsive", "")).strip().lower() == "false"
                    )
                    if is_svg or opt_out or not cl_responsive_enabled:
                        static_trans = (
                            cl_trans_svg
                            if is_svg
                            else cl_trans_static
                            if opt_out
                            else effective_cl_trans
                        )
                        tag["src"] = map_cloudinary_url(
                            src_val, cl_cloud, cl_map, static_trans, svg_trans=cl_trans_svg
                        )
                        if tag.get("srcset"):
                            del tag["srcset"]
                        if effective_lazyload in ("true", "native", "observer"):
                            tag["loading"] = "lazy"
                        continue

                    # Clear srcset to avoid conflict
                    if tag.get("srcset"):
                        del tag["srcset"]
                    # Add class cld-responsive
                    classes = tag.get("class", [])
                    if isinstance(classes, str):
                        classes = classes.split()
                    if "cld-responsive" not in classes:
                        classes.append("cld-responsive")
                    tag["class"] = " ".join(classes)

                    # Set data-src and src
                    tag["data-src"] = map_cloudinary_url(
                        src_val, cl_cloud, cl_map, effective_cl_trans
                    )
                    if use_blank_placeholder:
                        tag["src"] = (
                            "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
                        )
                    else:
                        tag["src"] = map_cloudinary_url(
                            src_val, cl_cloud, cl_map, effective_placeholder_trans
                        )

                    if effective_lazyload in ("true", "native", "observer"):
                        tag["loading"] = "lazy"
                    continue

            # 2. For all tags (including img if not already processed above),
            # process all attributes to map any matching URLs
            for attr in list(tag.attrs.keys()):
                if tag.name == "img" and attr in ("src", "data-src"):
                    continue
                val = tag[attr]
                if isinstance(val, str):
                    new_val = val
                    for prefix, map_val in cl_map.items():
                        if prefix in new_val:
                            new_val = replace_urls_in_text(
                                new_val, prefix, map_val, cl_cloud, effective_cl_trans,
                                svg_trans=cl_trans_svg,
                            )
                    tag[attr] = new_val

            # 3. If tag is a style tag, replace matches in its text content
            if tag.name == "style" and tag.string:
                new_css = tag.string
                for prefix, map_val in cl_map.items():
                    if prefix in new_css:
                        new_css = replace_urls_in_text(
                            new_css, prefix, map_val, cl_cloud, effective_cl_trans,
                            svg_trans=cl_trans_svg,
                        )
                tag.string = new_css

        # 4. Inject responsive script if enabled
        if cl_responsive_enabled:
            body = soup.find("body")
            if not body:
                body = soup

            if methodology == "legacy":
                core_js_url = cl_responsive.get(
                    "cl_core_js", "https://unpkg.com/cloudinary-core@latest"
                )
                lib_script = soup.new_tag("script", src=core_js_url, type="text/javascript")
                body.append(lib_script)

                init_script = soup.new_tag("script", type="text/javascript")
                init_script.string = (
                    f"\nvar cl = cloudinary.Cloudinary.new({{cloud_name: '{cl_cloud}'}});\n"
                    "cl.responsive();\n"
                )
                body.append(init_script)
            else:
                custom_js = cl_responsive.get("cl_custom_js")
                if custom_js:
                    if custom_js.strip().startswith("<script"):
                        custom_soup = BeautifulSoup(custom_js, "html.parser")
                        for sub_tag in custom_soup.contents:
                            body.append(sub_tag)
                    else:
                        custom_script = soup.new_tag("script", type="text/javascript")
                        custom_script.string = f"\n{custom_js}\n"
                        body.append(custom_script)
                else:
                    modern_script = soup.new_tag("script", type="text/javascript")
                    if effective_lazyload == "observer":
                        modern_script.string = (
                            "\n(function() {\n"
                            "  function initResponsive() {\n"
                            "    const resizeObserver = new ResizeObserver(entries => {\n"
                            "      for (let entry of entries) {\n"
                            "        const img = entry.target;\n"
                            "        const width = img.clientWidth || (img.parentElement ? img.parentElement.clientWidth : 0);\n"
                            "        if (width > 0) {\n"
                            "          const dpr = window.devicePixelRatio || 1;\n"
                            "          const targetWidth = Math.ceil((width * dpr) / 100) * 100;\n"
                            "          const dataSrc = img.getAttribute('data-src');\n"
                            "          if (dataSrc) {\n"
                            "            const newSrc = dataSrc.replace('w_auto', 'w_' + targetWidth);\n"
                            "            if (img.getAttribute('src') !== newSrc) {\n"
                            "              img.style.transition = 'filter 0.4s ease-in-out, opacity 0.4s ease-in-out';\n"
                            "              img.style.filter = 'blur(4px)';\n"
                            "              img.style.opacity = '0.8';\n"
                            "              const handleLoad = () => {\n"
                            "                img.style.filter = 'none';\n"
                            "                img.style.opacity = '1';\n"
                            "                img.removeEventListener('load', handleLoad);\n"
                            "              };\n"
                            "              img.addEventListener('load', handleLoad);\n"
                            "              img.setAttribute('src', newSrc);\n"
                            "              if (img.complete) {\n"
                            "                handleLoad();\n"
                            "              }\n"
                            "            }\n"
                            "          }\n"
                            "        }\n"
                            "      }\n"
                            "    });\n"
                            "    const intersectionObserver = new IntersectionObserver((entries, observer) => {\n"
                            "      for (let entry of entries) {\n"
                            "        if (entry.isIntersecting) {\n"
                            "          const img = entry.target;\n"
                            "          observer.unobserve(img);\n"
                            "          resizeObserver.observe(img);\n"
                            "        }\n"
                            "      }\n"
                            "    }, { rootMargin: '50px' });\n"
                            "    document.querySelectorAll('img.cld-responsive').forEach(img => {\n"
                            "      intersectionObserver.observe(img);\n"
                            "    });\n"
                            "  }\n"
                            "  if (document.readyState === 'loading') {\n"
                            "    document.addEventListener('DOMContentLoaded', initResponsive);\n"
                            "  } else {\n"
                            "    initResponsive();\n"
                            "  }\n"
                            "})();\n"
                        )
                    else:
                        modern_script.string = (
                            "\n(function() {\n"
                            "  function initResponsive() {\n"
                            "    const observer = new ResizeObserver(entries => {\n"
                            "      for (let entry of entries) {\n"
                            "        const img = entry.target;\n"
                            "        const width = img.clientWidth || (img.parentElement ? img.parentElement.clientWidth : 0);\n"
                            "        if (width > 0) {\n"
                            "          const dpr = window.devicePixelRatio || 1;\n"
                            "          const targetWidth = Math.ceil((width * dpr) / 100) * 100;\n"
                            "          const dataSrc = img.getAttribute('data-src');\n"
                            "          if (dataSrc) {\n"
                            "            const newSrc = dataSrc.replace('w_auto', 'w_' + targetWidth);\n"
                            "            if (img.getAttribute('src') !== newSrc) {\n"
                            "              img.style.transition = 'filter 0.4s ease-in-out, opacity 0.4s ease-in-out';\n"
                            "              img.style.filter = 'blur(4px)';\n"
                            "              img.style.opacity = '0.8';\n"
                            "              const handleLoad = () => {\n"
                            "                img.style.filter = 'none';\n"
                            "                img.style.opacity = '1';\n"
                            "                img.removeEventListener('load', handleLoad);\n"
                            "              };\n"
                            "              img.addEventListener('load', handleLoad);\n"
                            "              img.setAttribute('src', newSrc);\n"
                            "              if (img.complete) {\n"
                            "                handleLoad();\n"
                            "              }\n"
                            "            }\n"
                            "          }\n"
                            "        }\n"
                            "      }\n"
                            "    });\n"
                            "    document.querySelectorAll('img.cld-responsive').forEach(img => {\n"
                            "      observer.observe(img);\n"
                            "    });\n"
                            "  }\n"
                            "  if (document.readyState === 'loading') {\n"
                            "    document.addEventListener('DOMContentLoaded', initResponsive);\n"
                            "  } else {\n"
                            "    initResponsive();\n"
                            "  }\n"
                            "})();\n"
                        )
                    body.append(modern_script)

        return str(soup)

    def pull_webflow(self, *, update_stubs: bool = False) -> list[Path]:
        written: list[Path] = []
        user_agent = self.config.get("user_agent", "fontlab_www_toolkit")
        for page in self.discover_webflow_pages():
            html = self.process_page_html(fetch_text(page.import_url, user_agent=user_agent))
            page.cache_path.parent.mkdir(parents=True, exist_ok=True)
            page.cache_path.write_text(html, encoding="utf-8")
            written.append(page.cache_path)
            if update_stubs:
                self.update_stub(page)
                written.append(page.markdown_path)
        return written

    def update_stub(self, page: WebflowPage) -> None:
        """Rewrite a stub: keep its original frontmatter, replace the body with
        the Markdown extracted from the *cached* Webflow HTML via url22md.

        The original Markdown body is discarded entirely; only the frontmatter
        block is preserved verbatim.
        """
        original = page.markdown_path.read_text(encoding="utf-8")
        frontmatter, _ = split_frontmatter(original)
        body = extract_markdown_via_url22md(
            page.cache_path,
            tool=self.config.get("url22md_tool", 1),
            bin_path=self.config.get("url22md_bin"),
            timeout=int(self.config.get("url22md_timeout", 60)),
        ).strip()
        prefix = f"---\n{frontmatter}\n---\n\n" if frontmatter is not None else ""
        page.markdown_path.write_text(f"{prefix}{body}\n", encoding="utf-8")

    def convert_old_pages(self) -> list[Path]:
        mapping = self.load_old_pages()
        if mapping is None:
            return []
        written: list[Path] = []
        for markdown_name, old_relative in mapping.pages.items():
            source = mapping.old_public / old_relative
            if not source.exists():
                raise FileNotFoundError(f"Missing old page source: {source}")
            target = self.paths.markdown / markdown_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                convert_old_html(source, title_from_slug(markdown_name)), encoding="utf-8"
            )
            written.append(target)
        return written

    def build(self, *, pull_webflow: bool = True, update_stubs: bool = False) -> None:
        if pull_webflow:
            self.pull_webflow(update_stubs=update_stubs)
        self.paths.build_docs.mkdir(parents=True, exist_ok=True)
        self.run_static_builder()
        overlay_directory(self.paths.webflow_cache, self.paths.build_docs)
        overlay_directory(self.paths.static_docs, self.paths.build_docs)
        replace_directory(self.paths.build_docs, self.paths.public)

    def run_static_builder(self) -> None:
        config_file = self.paths.src_docs / "mkdocs.yml"
        if not config_file.exists():
            raise FileNotFoundError(f"Missing site config: {config_file}")

        custom_cmd = self.config.get("mkdocs_command")
        if custom_cmd:
            if isinstance(custom_cmd, str):
                cmd_str = custom_cmd.format(config_file=str(config_file))
                cmd = shlex.split(cmd_str)
            else:
                cmd = [str(arg).format(config_file=str(config_file)) for arg in custom_cmd]
            run(cmd, self.paths.root)
        else:
            command = [
                resolve_executable("properdocs"),
                "build",
                "--config-file",
                str(config_file),
                "--clean",
            ]
            try:
                run(command, self.paths.root)
            except FileNotFoundError:
                run(
                    [
                        sys.executable,
                        "-m",
                        "mkdocs",
                        "build",
                        "--config-file",
                        str(config_file),
                        "--clean",
                    ],
                    self.paths.root,
                )

    def clean(self) -> None:
        for path in (self.paths.build_docs, self.paths.public):
            if path.exists():
                shutil.rmtree(path)


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return metadata


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split Markdown into ``(frontmatter_inner, body)``.

    ``frontmatter_inner`` is the raw text between the opening ``---`` and the
    closing ``---`` (delimiters excluded), preserved verbatim so order,
    comments, and quoting survive a round-trip. Returns ``(None, text)`` when no
    frontmatter block is present.
    """
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    frontmatter = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    return frontmatter, body


def extract_markdown_via_url22md(
    cache_path: Path,
    *,
    tool: int | None = 1,
    bin_path: str | None = None,
    timeout: int = 60,
) -> str:
    """Extract Markdown from a locally cached HTML file using ``url22md``.

    ``url22md`` only accepts HTTP(S) URLs, so the cached file's directory is
    served over a short-lived loopback HTTP server and the tool is pointed at
    it. ``tool`` forces a specific extraction engine (default ``1`` =
    trafilatura) to keep extraction offline and deterministic; pass ``None`` to
    let url22md run its full fallback chain (which may reach cloud tools).
    """
    binary = bin_path or shutil.which("url22md")
    if not binary:
        raise FileNotFoundError(
            "url22md executable not found; install it or set 'url22md_bin' in config"
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Serve a noise-stripped copy so extractors don't capture inline JS/CSS
        # or hidden Webflow "Windflow" plugin metadata (which stores the
        # Tailwind config as visible div text) as page "prose".
        cleaned = strip_extraction_noise(cache_path.read_text(encoding="utf-8"))
        served = tmp_dir / "page.html"
        served.write_text(cleaned, encoding="utf-8")
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        handler = functools.partial(_QuietHTTPRequestHandler, directory=str(tmp_dir))
        with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                url = f"http://127.0.0.1:{port}/{served.name}"
                command = [binary, "--url", url, "--output_dir", str(out_dir), "--Force", "True"]
                if tool is not None:
                    command += ["--tool", str(tool)]
                run([*command, "--Timeout", str(timeout)], tmp_dir)
            finally:
                httpd.shutdown()
        produced = sorted(out_dir.glob("*.md"))
        if not produced:
            raise RuntimeError(f"url22md produced no Markdown for {cache_path}")
        return produced[0].read_text(encoding="utf-8")


class _QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """``SimpleHTTPRequestHandler`` that does not log requests to stderr."""

    def log_message(self, *args: object) -> None:  # noqa: D102
        return


def parse_flat_yaml(text: str) -> dict[str, str]:
    """Parse a flat-key YAML subset used by old-pages.yml.

    Supported:
      old_public: path/here
      pages:
        cookies.md: cookies/index.html
        terms.md: terms/index.html

    The ``old_public`` value is stored under the reserved key
    ``__old_public__`` in the returned dict; entries inside ``pages:`` are
    stored at the top level.
    """
    result: dict[str, str] = {}
    in_pages = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(" ") or raw.startswith("\t"):
            if not in_pages:
                continue
            line = raw.strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("\"'")
            continue
        in_pages = False
        line = raw.strip()
        if line == "pages:":
            in_pages = True
            continue
        if line.startswith("old_public:"):
            _, value = line.split(":", 1)
            result["__old_public__"] = value.strip().strip("\"'")
    return result


def markdown_to_public_path(markdown_path: Path, markdown_root: Path) -> str:
    relative = markdown_path.relative_to(markdown_root).with_suffix("")
    if relative.name == "index":
        parts = relative.parts[:-1]
    else:
        parts = relative.parts
    return "/" + "/".join(parts) + "/"


def fetch_text(url: str, user_agent: str = "fontlab_www_toolkit") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


# The "Made in Webflow" attribution badge Webflow injects into exported pages.
# We are legally entitled to remove it on paid plans; do so in two ways so it is
# gone both at processing time and as a defensive runtime fallback.
WEBFLOW_BADGE_ANCHOR_RE = re.compile(
    r"<a\b[^>]*\bclass=\"[^\"]*\bw-webflow-badge\b[^\"]*\"[^>]*>.*?</a>",
    re.IGNORECASE | re.DOTALL,
)
WEBFLOW_BADGE_HIDE_CSS = "<style>.w-webflow-badge{display:none !important;}</style>"


def strip_webflow_badge(html: str) -> str:
    """Remove the ``a.w-webflow-badge`` element from the DOM (approach 2)."""
    return WEBFLOW_BADGE_ANCHOR_RE.sub("", html)


def inject_badge_hiding_css(html: str, hide_css: str = WEBFLOW_BADGE_HIDE_CSS) -> str:
    """Add CSS that hides ``.w-webflow-badge`` (approach 1).

    Injected once before ``</head>`` (or prepended when there is no head) so the
    badge stays hidden even if a future export nests it somewhere we don't strip.
    """
    if hide_css in html:
        return html
    match = re.search(r"</head>", html, re.IGNORECASE)
    if match:
        return html[: match.start()] + hide_css + html[match.start() :]
    return hide_css + html


def clean_webflow_html(html: str) -> str:
    """Apply both badge-removal approaches to a fetched Webflow page."""
    return inject_badge_hiding_css(strip_webflow_badge(html))


def is_image_or_allowed_media(url: str) -> bool:
    # Strip query parameters and fragment identifier
    path = url.split("?")[0].split("#")[0].lower()
    allowed_extensions = {
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".svg",
        ".gif",
        ".avif",
        ".ico",
        ".heic",
        ".heif",
        ".tiff",
        ".bmp",
        # Videos
        ".mp4",
        ".webm",
        ".ogv",
        ".mov",
        # Audio
        ".mp3",
        ".wav",
        ".ogg",
        ".aac",
        ".flac",
        ".m4a",
    }
    return any(path.endswith(ext) for ext in allowed_extensions)


def is_svg_url(url: str) -> bool:
    """True if ``url``'s path (ignoring query/fragment) ends in ``.svg``."""
    path = url.split("?", 1)[0].split("#", 1)[0]
    return path.lower().endswith(".svg")


def map_cloudinary_url(
    url: str,
    cl_cloud: str,
    cl_map: dict[str, str],
    cl_trans: str,
    svg_trans: str | None = None,
) -> str:
    for prefix, map_val in cl_map.items():
        if url.startswith(prefix):
            if not is_image_or_allowed_media(url):
                return url
            rest = url[len(prefix) :].lstrip("/")
            trans = svg_trans if (svg_trans and is_svg_url(url)) else cl_trans
            if trans and not trans.endswith("/"):
                trans += "/"
            return f"https://res.cloudinary.com/{cl_cloud}/image/upload/{trans}{map_val}/{rest}"
    return url


def replace_urls_in_text(
    text: str,
    prefix: str,
    map_val: str,
    cl_cloud: str,
    cl_trans: str,
    svg_trans: str | None = None,
) -> str:
    escaped_prefix = re.escape(prefix)
    pattern = re.compile(escaped_prefix + r"[^\s\"'\)\>]*")

    def replacer(match):
        url = match.group(0)
        # Check if the matched URL is nested inside a Cloudinary fetch URL
        start = match.start()
        before = text[max(0, start - 150) : start]
        if "res.cloudinary.com" in before:
            last_idx = before.rfind("res.cloudinary.com")
            middle = before[last_idx:]
            if not any(char in middle for char in (" ", '"', "'", ")", ">", "<", "\n", "\t")):
                return url

        if not is_image_or_allowed_media(url):
            return url
        rest = url[len(prefix) :].lstrip("/")
        trans = svg_trans if (svg_trans and is_svg_url(url)) else cl_trans
        if trans and not trans.endswith("/"):
            trans += "/"
        return f"https://res.cloudinary.com/{cl_cloud}/image/upload/{trans}{map_val}/{rest}"

    return pattern.sub(replacer, text)


def convert_old_html(source: Path, title: str) -> str:
    html = source.read_text(encoding="utf-8", errors="replace")
    body = extract_old_page_content(
        remove_html_blocks(extract_body(html), ["script", "style", "noscript", "svg"])
    )
    markdown = markdownify(
        body,
        heading_style=ATX,
        strip=["script", "style", "noscript", "svg"],
    ).strip()
    return f"---\ntitle: {title}\nsource-html: {display_path(source)}\n---\n\n{markdown}\n"


def extract_body(html: str) -> str:
    lower = html.lower()
    start = lower.find("<body")
    if start == -1:
        return html
    start = html.find(">", start)
    end = lower.rfind("</body>")
    if start == -1:
        return html
    if end == -1:
        end = len(html)
    return html[start + 1 : end]


def extract_old_page_content(html: str) -> str:
    return extract_first_tag(html, "main") or extract_first_tag(html, "article") or html


def extract_first_tag(html: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def split_google_fonts_links(html: str) -> str:
    """Split a multi-family Google Fonts ``<link>`` into one link per family.

    Webflow emits a single ``fonts.googleapis.com/css2?family=A&family=B&…``
    link. If a downstream step truncates the served URL at the first ``&`` (as
    seen on the deployed site, where only the first family survives), every other
    family silently falls back to a system serif. Emitting a separate
    ``?family=X&display=swap`` link per family removes the long ``&family=``
    chain; even if ``&display=swap`` is later dropped, ``?family=X`` still loads.

    No-op when there are no multi-family Google Fonts links.
    """
    if "fonts.googleapis.com/css2" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    # Collect targets in a first pass *before* mutating, because ``decompose``
    # nulls a tag's ``.attrs`` (bs4 >=4.13) — and decomposing one link can clear
    # the ``.attrs`` of a sibling link still held in the live ResultSet, so
    # reading ``link["href"]`` mid-loop would raise once two links are split.
    targets = []
    for link in soup.find_all("link", href=True):
        href = link.get("href")
        if not href or "fonts.googleapis.com/css2" not in href or "family=" not in href:
            continue
        base, _, query = href.partition("?")
        params = query.split("&")
        families = [p for p in params if p.startswith("family=")]
        if len(families) < 2:
            continue
        extras = [p for p in params if p and not p.startswith("family=")]
        suffix = ("&" + "&".join(extras)) if extras else ""
        targets.append((link, base, families, suffix))
    for link, base, families, suffix in targets:
        for family in families:
            new = soup.new_tag("link", rel="stylesheet", href=f"{base}?{family}{suffix}")
            link.insert_before(new)
        link.decompose()
    return str(soup) if targets else html


def strip_extraction_noise(html: str) -> str:
    """Remove non-prose nodes before Markdown extraction.

    Drops ``<script>``/``<style>``/``<noscript>`` and any element carrying a
    ``windflow-*`` attribute. The latter targets the Webflow *Windflow* plugin's
    hidden metadata file (``<div class="…-windflow-file" windflow-meta="true">``),
    which stores a full Tailwind config as ``display:none`` div text that
    extractors otherwise mistake for the page body.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(True):
        if any(str(attr).startswith("windflow-") for attr in (tag.attrs or {})):
            tag.decompose()
    return str(soup)


def remove_html_blocks(html: str, tags: list[str]) -> str:
    cleaned = html
    for tag in tags:
        pattern = re.compile(rf"<{tag}\b[^>]*>.*?</{tag}>", re.IGNORECASE | re.DOTALL)
        cleaned = pattern.sub("", cleaned)
    return cleaned


def title_from_slug(markdown_name: str) -> str:
    slug = Path(markdown_name).stem
    initialisms = {"eula": "EULA"}
    if slug in initialisms:
        return initialisms[slug]
    return slug.replace("-", " ").title()


def display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def overlay_directory(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    for item in source.rglob("*"):
        target = destination / item.relative_to(source)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def replace_directory(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True, env=env)


def resolve_executable(name: str) -> str:
    local = Path(sys.executable).resolve().parent / name
    if local.exists():
        return str(local)
    return name


def setup_environment(root: Path, venv: Path | None = None, *, clear: bool = False) -> None:
    uv = find_uv()
    env_path = venv or root / ".venv"
    python = venv_python(env_path)
    if clear or not python.exists():
        command = [uv, "venv", str(env_path), "--python", "3.12"]
        if clear:
            command.append("--clear")
        run(command, root, env=uv_environment())
    run(
        [uv, "pip", "install", "--python", str(venv_python(env_path)), "-e", "."],
        root,
        env=uv_environment(),
    )


def venv_python(venv: Path) -> Path:
    unix_python = venv / "bin" / "python"
    if unix_python.exists():
        return unix_python
    return venv / "Scripts" / "python.exe"


def find_uv() -> str:
    configured = os.environ.get("UV_BIN")
    if configured:
        return os.path.expanduser(configured)
    found = shutil.which("uv")
    if found:
        return found
    home_uv = Path.home() / ".local/bin/uv"
    if home_uv.exists():
        return str(home_uv)
    return "uv"


def uv_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("RAYON_NUM_THREADS", "1")
    env.setdefault("UV_CONCURRENT_BUILDS", "1")
    env.setdefault("UV_CONCURRENT_DOWNLOADS", "1")
    env.setdefault("UV_CONCURRENT_INSTALLS", "1")
    return env
