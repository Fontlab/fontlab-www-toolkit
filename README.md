
# fontlab-www-toolkit

Shared **ProperDocs + MaterialX** site builder and deploy helpers used by the
FontLab web properties (`www.fontlab.com`, `www.vexy.art`, and the
`api.fontlab.com/www-admin/` PHP UI).

## Install

```bash
uv add fontlab-www-toolkit          # in a project
uvx fontlab-www-toolkit --help      # one-shot
pip install fontlab-www-toolkit
```

## CLI

Three equivalent ways to invoke it:

```bash
fontlab-www-toolkit COMMAND        # console script (works under uvx too)
fontlab-build       COMMAND        # backwards-compat alias
python -m fontlab_www_toolkit COMMAND
```

Commands:

| Command | Effect |
|---|---|
| `build [--skip_webflow] [--update_stubs]` | Pull Webflow stubs, build with MkDocs/ProperDocs, overlay `wf_cache/` + `static_docs/`, publish to `public/`. |
| `pull-webflow [--update_stubs]` | Refresh `wf_cache/` only. |
| `convert-old` | Regenerate OLD pages from `src_docs/old-pages.yml`. |
| `clean` | Delete `build_docs/` and `public/`. |
| `setup [--venv PATH] [--clear]` | Create / refresh a uv venv for the admin pipeline. |
| `mirror --manifest_url URL --dest DIR [--dry_run]` | Mirror a static site folder over HTTPS from its `manifest.json` (size + SHA-256 verified, atomic folder swap). |
| `version` | Print the installed version. |

All commands accept `--root PATH`; default is the current working directory.

## Mirroring a published static site

Some properties are not built by this toolkit but by their own CI — e.g. the
TTH Debugger, whose GitHub Actions build lands in
`https://fontlab.dev/tth-debugger/alpha-sdx992/`. Such a build exposes a
`manifest.json` (`schema: fontlab-site-manifest/1`) listing every file with
`path`, `size`, `sha256`, `type` (HTML entries may add `sha256Normalized`, the hash with ASCII whitespace removed), plus `name`, `version`, `commit`, `builtAt`,
`baseUrl`, `entry`. `mirror` consumes that:

```bash
fontlab-www-toolkit mirror \
  --manifest_url https://fontlab.dev/tth-debugger/alpha-sdx992/manifest.json \
  --dest /path/to/live/studio.fontlab.com/public/tth-debugger
```

Files already present with a matching hash are reused; everything else is
downloaded, verified, and the folder is swapped in with a rename so the live
site never sees a half-written tree. Cloudflare's injected bot-detection
`<script>` in HTML responses is stripped before verification. The manifest is
saved into the destination as `manifest.json` for provenance. Standard library
only — no extra dependencies in the admin venv.

## Site repo layout it expects

```
site/
├── src_docs/
│   ├── mkdocs.yml
│   ├── md/                   # Markdown sources (+ Webflow stubs via frontmatter)
│   └── old-pages.yml         # OPTIONAL — one-time HTML → MD conversions
├── static_docs/              # Copied verbatim over build_docs/ during overlay
├── wf_cache/                 # Generated — Webflow snapshots
├── build_docs/               # Generated — MkDocs output
└── public/                   # Generated — final publish tree
```

A Webflow stub is any Markdown file with frontmatter:

```yaml
---
title: Page
webflow-import-url: https://example.webflow.io/page
---
```

### Refreshing stub bodies (`--update_stubs`)

Normally only `wf_cache/` is refreshed; the stub Markdown body stays as a
placeholder (the cached HTML overlays it at build time). Pass `--update_stubs`
to `pull-webflow` or `build` to also rewrite each stub's **body** from the
freshly cached HTML, while preserving the stub's **frontmatter** verbatim:

```bash
fontlab-www-toolkit pull-webflow --update_stubs
```

For each stub it strips non-prose noise (`<script>`/`<style>`/`<noscript>` and
hidden Webflow *Windflow* plugin metadata), serves the cleaned cached HTML over
a loopback HTTP server, and runs [`url22md`](https://github.com/twardoch/url22md)
to extract Markdown. This requires the `url22md` CLI on `PATH` (or set
`url22md_bin` in config); it is an external runtime tool, not a packaged
dependency.

## Configuration

You can customize the builder's behavior using a JSON configuration file (by default `fontlab-www-toolkit.json` in the root directory, or passed via `--config` CLI option). Alternatively, individual pages can specify page-specific overrides inside the input HTML:

```html
<head>
  <script id="fontlab-toolkit-config" type="application/json">
  {
    "cloudinary": {
      "cl_responsive": {
        "methodology": "legacy"
      }
    }
  }
  </script>
</head>
```

### Global Overrides

The following settings can be overridden in the root configuration object:

* **`frontmatter_key`** (string): The YAML frontmatter key used to identify Webflow URLs. Defaults to `"webflow-import-url"`.
* **`webflow_badge_hide_css`** (string): CSS injected to hide the Webflow badge.
* **`old_pages_config`** (string): Path to the legacy pages mapping file. Defaults to `"src_docs/old-pages.yml"`.
* **`mkdocs_command`** (string | array): The custom build command for MkDocs/ProperDocs. Can include the `{config_file}` placeholder.
* **`user_agent`** (string): Custom User-Agent header used when pulling Webflow pages. Defaults to `"fontlab_www_toolkit"`.
* **`split_google_fonts`** (bool): When true (default), split a multi-family `fonts.googleapis.com/css2?family=A&family=B&…` link into one `?family=X&display=swap` link per family. This keeps web fonts loading even if a downstream step truncates the served URL at the first `&` (otherwise only the first family loads and the rest fall back to a system font).
* **`url22md_bin`** (string): Path to the `url22md` executable used by `--update_stubs`. Defaults to whatever is found on `PATH`.
* **`url22md_tool`** (int | null): Forces a specific `url22md` extraction engine (`1`=trafilatura, `3`=readability, …). Defaults to `1` for offline, deterministic extraction; set to `null` to let url22md run its full fallback chain (may reach cloud tools).
* **`url22md_timeout`** (int): Per-page extraction timeout in seconds. Defaults to `60`.

### Cloudinary Options

The `cloudinary` block allows automatic mapping of image URLs to Cloudinary and setup of responsive client-side loading:

```json
{
  "cloudinary": {
    "cl_cloud": "mycloud",
    "cl_map": {
      "https://cdn.example-files.com/assets": "assets_prefix",
      "https://images.example.com": "images_prefix"
    },
    "cl_trans": "c_limit,w_auto/f_auto,q_auto,dpr_auto/",
    "cl_responsive": {
      "cl_trans_thumb": "c_limit,w_128/f_auto,q_1/",
      "cl_core_js": "https://unpkg.com/cloudinary-core@latest",
      "methodology": "modern"
    }
  }
}
```

* **`cl_cloud`**: Cloudinary cloud name.
* **`cl_map`**: Map of source URL prefixes to Cloudinary upload folder prefixes. Any matching image URLs found in attributes (like `src`, `href`, `style` background-image) will be replaced.
* **`cl_trans`**: The default Cloudinary image transformation string.
* **`cl_responsive`**: (Optional) Enables responsive client-side images:
  * Adds `class="cld-responsive"` to matching `<img>` elements.
  * Sets the `src` attribute to a thumbnail transformation (using `cl_trans_thumb`).
  * Sets the `data-src` attribute to the main transformation (using `cl_trans`).
  * Clears `srcset` to avoid browser conflict.
  * Injects responsive initialization scripts before the closing `</body>` tag:
    * **`methodology: "modern"`** (Recommended): Injects a lightweight vanilla JS script using `ResizeObserver` to update image source dynamically, avoiding heavy external library dependencies.
    * **`methodology: "legacy"`**: Injects the `cloudinary-core` library (`cl_core_js`) and invokes `cl.responsive()`.

## Deploy helpers (library use)

```python
from pathlib import Path
from fontlab_www_toolkit import DeployTarget, run_full_deploy

target = DeployTarget(
    site_root=Path("/path/to/site"),
    site_label="www.example.com",
    local_source=Path("/path/to/site/public"),
    backup_dest=Path("/path/to/web-fontlab/src/ionos/live/example.com/public"),
    remote_path="live/example.com/public",
)
run_full_deploy(target, commit_message="Deploy www.example.com")
```

Mirrors the local backup, rsyncs to the remote, commits both the site repo and
(if present) the `web-fontlab/` mirror repo.

## Develop

```bash
git clone git@github.com:Fontlab/fontlab-www-toolkit.git
cd fontlab-www-toolkit
uv sync --group dev
uv run ruff check src/ tests/      # lint
uv run mypy src/fontlab_www_toolkit/  # typecheck
uv run pytest -q                   # test
```

Version comes from git tags via `hatch-vcs`. Tag with semver (`v1.2.3`) to bump.

See [CHANGELOG.md](CHANGELOG.md) for release history and [src_docs/](src_docs/) for
full documentation covering the four-layer build flow, Webflow stub format,
`wf_cache/` layout, and `www-admin` integration.

## Publish

```bash
./publish.sh   # uvx hatch clean ; uvx gitnextver ; uv build ; uv publish
```

Requires `UV_PUBLISH_TOKEN` (PyPI token) in the environment.
