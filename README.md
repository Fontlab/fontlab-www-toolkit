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
