# Webflow stub frontmatter

A **Webflow stub** is any Markdown file in `src_docs/md/` that carries a
`webflow-import-url:` key in its YAML frontmatter.  The page-import plugin fetches this URL and renders the imported HTML at the
Markdown page’s output path.

## Required frontmatter

```yaml
---
title: Page title
webflow-import-url: https://your-project.webflow.io/page-slug
---
```

| Key | Required | Description |
|---|---|---|
| `title` | No | Page title used by ProperDocs |
| `webflow-import-url` | Yes | Canonical Webflow preview URL to fetch and cache |

The stub body (everything after the closing `---`) is a placeholder.  It is
indexed by search during the static build. Visitors see imported HTML when
available, or the rendered stub on an offline cache miss.

## Optional stub body

```yaml
---
title: Vexy Lines
webflow-import-url: https://vexy-art.webflow.io/lines
---

# Vexy Lines

Product page placeholder.
```

## Other import keys

Use `import-url` for general HTML or `copy-file` for a local export. Each stub
accepts one import key. Migrate custom `frontmatter_key` values to these fixed
keys and remove the setting from the toolkit JSON file.

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

The Markdown path determines the public path. The exact source URL determines
the SHA-256 cache filename. Moving a stub preserves its cached source when
the URL stays the same. See [cache layout](wf-cache.md).
