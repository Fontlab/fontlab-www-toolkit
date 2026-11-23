# Build flow

1. **Build the pages.** ProperDocs reads `src_docs/mkdocs.yml` and writes into
   `build_docs/`. The `page-import` plugin places imported HTML at the stub's
   output path after search and navigation have seen its Markdown. Webflow
   imports receive the site's badge, font, Cloudinary and Rocket Loader settings.
2. **Overlay static files.** Files under `static_docs/` replace files at matching
   paths in `build_docs/`. Typical overrides include legacy redirects,
   `robots.txt` and `sitemap.xml`.
3. **Inject theme assets.** The toolkit adds missing configured stylesheets and
   scripts to final HTML, including static overrides.
4. **Publish locally.** Each top-level name in `build_docs/` replaces its
   counterpart in `public/`. Other names already in `public/` are preserved.

## CLI flags

| Flag | Effect |
|---|---|
| `--skip_webflow` | Use cached URL imports. Keep the rendered Markdown when a cache entry is missing. |
| `--update_stubs` | Extract stub bodies from cached HTML via `url22md`. If the text changes, render again offline to update search. |
| `--root PATH` | Set the site repository root. Defaults to the current directory. |
| `--config PATH` | Override the toolkit JSON configuration path. |

Use `fontlab-www-toolkit pull-webflow` to refresh the URL cache independently
of the static build. See [cache layout and overlay precedence](wf-cache.md).
