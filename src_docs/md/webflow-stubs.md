# Webflow stub frontmatter

A **Webflow stub** is any Markdown file in `src_docs/md/` that carries a
`webflow-import-url:` key in its YAML frontmatter.  The toolkit uses it to know
which URL to fetch and cache, and which `build_docs/` path to overlay.

## Required frontmatter

```yaml
---
title: Page title
webflow-import-url: https://your-project.webflow.io/page-slug
---
```

| Key | Required | Description |
|---|---|---|
| `title` | Yes | Page title used by ProperDocs |
| `webflow-import-url` | Yes | Canonical Webflow preview URL to fetch and cache |

The stub body (everything after the closing `---`) is a placeholder.  It is
used by ProperDocs during Layer 1 (static build) but is replaced by the cached
Webflow HTML during Layer 2.

## Optional stub body

```yaml
---
title: Vexy Lines
webflow-import-url: https://vexy-art.webflow.io/lines
---

<!-- This body is overwritten by the Webflow cache at build time. -->
# Vexy Lines

Product page placeholder.
```

## Frontmatter key customisation

The default key `webflow-import-url` can be overridden in the JSON config:

```json
{ "frontmatter_key": "wf-url" }
```

## Stub body refresh (`--update_stubs`)

Pass `--update_stubs` to `build` or `pull-webflow` to rewrite each stub's body
from the freshly cached HTML using [`url22md`](https://github.com/twardoch/url22md):

```bash
fontlab-www-toolkit pull-webflow --update_stubs
```

The refresh:

1. Fetches the Webflow preview URL and saves HTML to `wf_cache/`.
2. Strips noise (`<script>`, `<style>`, `<noscript>`, Windflow metadata).
3. Serves the cleaned HTML over a loopback HTTP server.
4. Calls `url22md` to extract Markdown.
5. **Preserves the stub frontmatter verbatim** and replaces only the body.

`url22md` must be on `PATH` (or set `url22md_bin` in the JSON config).  It is
an external runtime dependency, not a packaged dependency of this library.

## URL → cache path mapping

The stub's `webflow-import-url` value determines where the cached HTML is
stored:

| Markdown path | Public path | Cache path |
|---|---|---|
| `src_docs/md/font-editor/fontlab.md` | `/font-editor/fontlab/` | `wf_cache/font-editor/fontlab/index.html` |
| `src_docs/md/index.md` | `/` | `wf_cache/index.html` |
| `src_docs/md/lines/index.md` | `/lines/` | `wf_cache/lines/index.html` |

The public path is derived from the Markdown path (not from the Webflow URL),
so moving a stub file changes its published URL.
