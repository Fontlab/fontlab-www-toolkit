# fontlab-www-toolkit

Shared **ProperDocs + MaterialX** site builder and deploy helpers used by
FontLab web properties.

## Consumer sites

| Site | Repo |
|---|---|
| `www.fontlab.com` | `github.fontlab/www.fontlab.com` |
| `www.vexy.art` | `github.fontlab/www.vexy.art` |
| `api.fontlab.com/www-admin/` | `github.fontlab/api.fontlab.com` |

## Quick start

```bash
pip install fontlab-www-toolkit          # or: uv add fontlab-www-toolkit
fontlab-www-toolkit build                # full build in site repo root
fontlab-www-toolkit build --skip_webflow # build without hitting Webflow network
```

## Architecture overview

The toolkit follows a **four-layer build flow** (see [Build flow](build-flow.md)):

```
ProperDocs build (src_docs/ → build_docs/)
    ↓  overlay Webflow pages (wf_cache/ → build_docs/)
    ↓  overlay static files (static_docs/ → build_docs/)
    ↓  publish (build_docs/ → public/)
```

## Key concepts

- **[Webflow stubs](webflow-stubs.md)** — Markdown files with `webflow-import-url:` frontmatter
- **[wf_cache/](wf-cache.md)** — local mirror of live Webflow page HTML
- **[static_docs/](wf-cache.md#static_docs-overlay)** — verbatim file overlay (wins on conflict)
- **[www-admin integration](www-admin.md)** — remote trigger from the PHP admin UI
