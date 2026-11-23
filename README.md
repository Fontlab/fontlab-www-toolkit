<!-- this_file: README.md -->


# fontlab-www-toolkit

Shared **ProperDocs + MaterialX** site builder and deploy helpers used by the
FontLab web properties (`www.fontlab.com`, `www.vexy.art`, and the
`api.fontlab.com/www-admin/` PHP UI).

## Install

On the `fly-january` branch, run `uv sync` in this checkout. Until
`vexy-mkdocs-page-import` is on PyPI, uv installs it from the editable path in
`pyproject.toml`. On another machine, point that path at its local checkout.
Install the plugin in the environment that runs ProperDocs if the site uses a
custom build command.

## CLI

Three equivalent ways to invoke it:

```bash
fontlab-www-toolkit COMMAND        # installed console script
fontlab-build       COMMAND        # backwards-compat alias
python -m fontlab_www_toolkit COMMAND
```

Commands:

| Command | Effect |
|---|---|
| `build [--skip_webflow] [--update_stubs]` | Build with `page-import`, overlay `static_docs/`, inject theme assets and publish to `public/`. |
| `pull-webflow [--update_stubs]` | Refresh the URL cache without building. Optionally rewrite stub bodies. |
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
│   ├── md/                   # Markdown pages and import stubs
│   └── old-pages.yml         # Optional legacy HTML → Markdown mappings
├── static_docs/              # Overrides files at matching build paths
├── wf_cache/                 # Source HTML, one file per URL hash
├── build_docs/               # Generated site with overlays and theme assets
└── public/                   # Final local publish tree
```

ProperDocs renders Markdown for navigation and search. During that build,
`page-import` places imported HTML at each stub’s normal output path.
The toolkit then copies `static_docs/` over the result, injects configured
`theme_assets` into the final HTML, and copies the built names into `public/`.

## Migrate a site to page-import

1. Add `page-import` to the existing plugins in `src_docs/mkdocs.yml`. Keep
   `search` if the site indexes Markdown. Move the contents of the site's JSON
   `cloudinary` block under `webflow.cloudinary` in this configuration.

   ```yaml
   plugins:
     - search
     - page-import:
         offline: !ENV [PAGE_IMPORT_OFFLINE, false]
         on_offline_miss: !ENV [PAGE_IMPORT_ON_MISS, error]
         cache_dir: ../wf_cache
         webflow:
           cloudinary:
             cl_cloud: fontlab
             cl_map:
               "https://cdn.example.org/media": assets
   ```

   Use your existing Cloudinary values, or omit `cloudinary` if unused.
   Move `split_google_fonts` and `rocket_loader_optout` under `webflow` too.
   Rename `webflow_badge_hide_css` to `webflow.badge_hide_css`. The plugin
   supplies its own HTTP user agent.

2. Remove `cloudinary` and `frontmatter_key` from `fontlab-www-toolkit.json`.
   The toolkit warns about either setting. Replace any custom stub key with one
   of the plugin’s fixed keys. Choose `webflow-import-url` for Webflow
   processing, `import-url` for other remote HTML, or `copy-file` for a local
   export relative to the site configuration.

   ```yaml
   ---
   title: Product page
   webflow-import-url: https://example.webflow.io/product
   ---
   ```

3. Run `fontlab-www-toolkit pull-webflow` or an online `build` before the first
   offline build. The plugin reads raw source HTML from
   `wf_cache/<sha256-of-url>.html`. It ignores old
   `wf_cache/<public-path>/index.html` files. Webflow processing runs when the
   plugin renders the imported page, including on cache hits.

### Offline builds and stub bodies

`build --skip_webflow` sets `PAGE_IMPORT_OFFLINE=true` and
`PAGE_IMPORT_ON_MISS=keep` for the static build. The plugin uses cached URL
imports and keeps rendered Markdown on a miss. An ordinary build sets
`PAGE_IMPORT_OFFLINE=false` and respects the plugin’s `refresh` setting.
`pull-webflow` explicitly refreshes both URL import types.

Pass `--update_stubs` to `pull-webflow` or `build` to rewrite URL stub bodies
from cached HTML. The toolkit preserves the front matter, strips scripts,
styles and hidden Windflow metadata, and serves the cleaned HTML over loopback
to the external `url22md` executable. If a build changes a stub body, it
renders again from cache so the published search index contains the new text.
As before, `--skip_webflow` also skips the optional stub rewrite.

### Toolkit configuration

Set these options in `fontlab-www-toolkit.json` at the site root or pass
`--config PATH` to `build` or `pull-webflow`.

| Setting | Effect |
|---|---|
| `theme_assets` | Ordered list of HTTPS CSS and JavaScript URLs. Missing asset tags are added after the static overlay. |
| `mkdocs_command` | Custom build command (string or list). Use `{config_file}` for the site configuration path. |
| `old_pages_config` | Legacy HTML conversion mapping. Defaults to `src_docs/old-pages.yml`. |
| `url22md_bin` | Extraction executable. Defaults to `url22md` on `PATH`. |
| `url22md_tool` | Extraction engine. Defaults to `1` for local extraction. A value of `null` allows the tool's full fallback chain, including cloud tools. |
| `url22md_timeout` | Extraction timeout in seconds. Defaults to `60`. |

Sites on the fly-january theme use these assets for imported pages:

```json
{
  "theme_assets": [
    "https://fontlab.dev/fontlab-www-docstheme/fly/latest/fly.css",
    "https://fontlab.dev/fontlab-www-docstheme/fly/latest/fly.js"
  ]
}
```

Imported Webflow pages carry their own global header and footer. For Markdown
pages, set `extra.fly.chrome` in `mkdocs.yml` to `fontlab`, `vexy`, or `none`.

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

<!-- shared-theme-integration:start -->
## Shared FontLab theme integration

This repository is part of the FontLab theme 2026 rollout: shared hybrid-site build pipeline.
[THEME.md](THEME.md) documents its source/output boundaries, configuration,
publication route, control ownership, shared visual changes and verification.
Use the [public setup guide](https://i.fontlab.com/fltheme26/) and
[MaterialX starter](https://i.fontlab.com/fltheme26/starter.zip) for new sites.
<!-- shared-theme-integration:end -->
