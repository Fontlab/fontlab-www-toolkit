<!-- this_file: README.md -->

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
| `build [--skip_webflow]` | Pull Webflow stubs, build with MkDocs/ProperDocs, overlay `wf_cache/` + `static_docs/`, publish to `public/`. |
| `pull-webflow` | Refresh `wf_cache/` only. |
| `convert-old` | Regenerate OLD pages from `src_docs/old-pages.yml`. |
| `clean` | Delete `build_docs/` and `public/`. |
| `setup [--venv PATH] [--clear]` | Create / refresh a uv venv for the admin pipeline. |
| `version` | Print the installed version. |

All commands accept `--root PATH`; default is the current working directory.

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
uv sync
uv run pytest -q
```

Version comes from git tags via `hatch-vcs`. Tag with semver (`v1.2.3`) to bump.

## Publish

```bash
./publish.sh   # uvx hatch clean ; uvx gitnextver ; uv build ; uv publish
```

Requires `UV_PUBLISH_TOKEN` (PyPI token) in the environment.
