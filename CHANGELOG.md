# Changelog

All notable changes to `fontlab-www-toolkit` are documented here.

## v1.0.13 — 2026-08-22

### Added
- `mirror`: honours the optional `sha256Normalized` manifest field (HTML
  only; hash with ASCII whitespace removed). Cloudflare not only injects
  scripts into HTML but also reflows whitespace around `</body>`, so the
  exact bytes cannot be recovered; the normalized hash still proves the page
  is the published one. A whitespace-only difference also counts as "up to
  date" on later runs.

## v1.0.12 — 2026-08-22

### Fixed
- `mirror`: strip *any* `<script>` Cloudflare injects into HTML (the Web
  Analytics beacon from `static.cloudflareinsights.com` as well as the
  `/cdn-cgi/` challenge script), not just the first variant seen.

## v1.0.11 — 2026-08-22

### Fixed
- `mirror`: destination folder/files now get explicit `0755`/`0644` modes.
  `mkdtemp()` creates `0700` and IONOS runs with umask `077`, so the first
  live publish produced a tree Apache could not read (HTTP 403).

## v1.0.10 — 2026-08-22

### Added
- `mirror --manifest_url URL --dest DIR [--dry_run] [--timeout S]`: mirror a
  static site folder over HTTPS from a `fontlab-site-manifest/1`
  `manifest.json`. Verifies size + SHA-256 per file, reuses unchanged files,
  swaps the destination folder in atomically, strips Cloudflare's injected
  bot-detection `<script>` from HTML before verification. Used by
  api.fontlab.com/www-admin to publish `studio.fontlab.com/tth-debugger`
  from `https://fontlab.dev/tth-debugger/alpha-sdx992/`.
- `fontlab_www_toolkit.mirror` module (stdlib only) with tests.

## v1.0.9 — 2026-08-19

### Changed
- Publish writes only the names present in `build_docs/` into `public/`.
  Anything else already in `public/` is left alone.

## v1.0.7 — 2026-06-27

### Changed
- Cloudinary responsive script: replaced inline `opacity` fade with
  `filter: blur(4px)` load-in to avoid overriding class/CSS-driven opacity
  animations (scroll-driven layer reveals, etc.).
- Improved `exempt_scripts_from_rocket_loader`: the function now returns the
  original string object (no copy) when no `<script>` tags are found, saving
  a parse round-trip on Webflow pages that have already been cleaned.

## v1.0.6

### Added
- `rocket_loader_optout` config key (default `true`): adds `data-cfasync="false"`
  to all executable `<script>` tags so Cloudflare Rocket Loader does not
  reorder or defer them.
- `exempt_scripts_from_rocket_loader` function exported from `builder.py`.

## v1.0.5

### Added
- `lazyload` option for Cloudinary responsive images (`"observer"`, `"native"`,
  `True`, `False`).
- `placeholder` option: `"blur"`, `"pixelate"`, `"vectorize"`, `"predominant"`,
  `False` (blank GIF), or a custom Cloudinary transformation string.
- `accessibility` option: `"colorblind"`, `"monochrome"`, `"darkmode"`,
  `"brightmode"`, or a custom effect string.

## v1.0.4

### Added
- `data-cld-responsive="false"` opt-out attribute: images carrying this
  attribute get a static Cloudinary URL (no responsive class, no `data-src`).
- SVG image handling: SVG files get a minimal `f_svg,q_auto` transform instead
  of the responsive width chain.

### Fixed
- Cloudinary nested fetch-URL guard: URLs that are already embedded inside a
  `res.cloudinary.com/…/fetch/…` transform string are no longer double-mapped.

## v1.0.3

### Added
- `split_google_fonts_links`: splits a multi-family `fonts.googleapis.com/css2`
  `<link>` into one link per family, preventing downstream URL truncation from
  silently dropping all but the first font family.
- Regression fix for BeautifulSoup ≥ 4.13 where `decompose()` on a live
  `ResultSet` nulled sibling tags' `.attrs` dict.

## v1.0.2

### Added
- Cloudinary URL mapping and responsive image transformation
  (`process_html_cloudinary`): `cl_cloud`, `cl_map`, `cl_trans`,
  `cl_trans_svg`, `cl_trans_static`, `cl_responsive` with `"modern"` and
  `"legacy"` methodologies.
- Page-level config override via `<script id="fontlab-toolkit-config" type="application/json">`.

## v1.0.1

### Added
- `strip_webflow_badge` and `inject_badge_hiding_css` for Webflow badge
  suppression in cached pages.
- `update_stub` command: rewrites Webflow stub Markdown bodies from the cached
  HTML via `url22md` while preserving frontmatter.
- `mkdocs_command` config key for custom build command overrides.

## v1.0.0 — Initial release

### Added
- `SiteBuilder` with four-layer build flow: ProperDocs → Webflow overlay →
  static overlay → publish.
- `pull-webflow` command: fetches Webflow stub URLs and writes `wf_cache/`.
- `convert-old` command: batch HTML → Markdown conversion from
  `src_docs/old-pages.yml`.
- `clean` command: removes `build_docs/` and `public/`.
- `setup` command: creates a `uv`-managed virtual environment.
- `version` command: prints the installed package version.
- `DeployTarget` and `run_full_deploy` for rsync + git deploy helpers.
- `hatch-vcs` versioning; published to PyPI as `fontlab-www-toolkit`.
