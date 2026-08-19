# Build flow

`fontlab-www-toolkit build` runs a four-layer pipeline that merges static
Markdown, Webflow-cached pages, and verbatim overlay files into a single
`public/` tree.

## The four layers

```
Layer 1 — ProperDocs build
    src_docs/md/  ──mkdocs/properdocs──▶  build_docs/

Layer 2 — Webflow overlay
    wf_cache/  ──copy-on-conflict──▶  build_docs/

Layer 3 — Static overlay
    static_docs/  ──copy-on-conflict──▶  build_docs/

Layer 4 — Publish
    build_docs/  ──replace──▶  public/
```

Each layer **wins over the previous one** on file conflict.  So:

- A static HTML file in `static_docs/` always overrides the same path in
  `build_docs/` (whether it came from ProperDocs or Webflow cache).
- A Webflow-cached page overrides the ProperDocs build output for the same URL.
- ProperDocs output is the base — it provides all non-Webflow, non-static pages.

## Layer 1 — ProperDocs build

```bash
fontlab-www-toolkit build
# internally calls:
mkdocs build -f src_docs/mkdocs.yml -d ../build_docs
```

ProperDocs (a `mkdocs-materialx` extension) processes the site's
`src_docs/mkdocs.yml` and converts all `src_docs/md/*.md` files to HTML in
`build_docs/`.

**Webflow stub Markdown files** (any `.md` with a `webflow-import-url:` key in
frontmatter) are included in the ProperDocs build as placeholder pages.
The cached Webflow HTML overwrites them in Layer 2.

## Layer 2 — Webflow overlay

`wf_cache/` is a local directory that mirrors the HTML of each Webflow-hosted
page.  During the build, each cached HTML file is post-processed
(`SiteBuilder.process_page_html`) and copied over the ProperDocs output at the
matching URL path.

Post-processing steps:

1. Strip the Webflow badge DOM node; inject `display:none` CSS rule.
2. Split multi-family Google Fonts `<link>` tags (one per family).
3. Apply Cloudinary URL mapping and responsive image transformation (if
   configured).
4. Add `data-cfasync="false"` to all executable `<script>` tags (Rocket Loader
   opt-out).

Run only this layer without a full rebuild:

```bash
fontlab-www-toolkit pull-webflow   # refreshes wf_cache/ from Webflow network
```

## Layer 3 — Static overlay

Files under `static_docs/` are copied verbatim to `build_docs/`.  No
processing is applied.  Use this layer for:

- Prebuilt or third-party HTML/CSS/JS that must not be touched.
- Legacy redirect pages.
- Canonical `robots.txt`, `sitemap.xml`, or other root-level assets.

## Layer 4 — Publish

Each top-level name in `build_docs/` is copied over the same name in `public/`.
Names that exist only in `public/` (not produced by this build) are not
touched. The consumer site's deploy step (`deploy.py`) then rsyncs `public/`
to the remote host.

## CLI flags

| Flag | Effect |
|---|---|
| `--skip_webflow` | Skip Layer 2 (use existing `wf_cache/` without network fetch) |
| `--update_stubs` | After pulling Webflow pages, also rewrite each stub's body from the cached HTML via `url22md` |
| `--root PATH` | Set the site repo root (default: current directory) |
| `--config PATH` | Override the JSON config file path |

## Sequence diagram

```
                     ┌─────────────┐
  src_docs/md/   ──▶ │  ProperDocs │ ──▶ build_docs/
                     └─────────────┘
  wf_cache/      ──overlay──▶ build_docs/   (Webflow pages win)
  static_docs/   ──overlay──▶ build_docs/   (static wins)
  build_docs/    ──publish names──▶ public/   (other public/ names untouched)
```
