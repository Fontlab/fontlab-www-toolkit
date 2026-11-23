---
this_file: WORK.md
---

# Work

## 2026-11-23 — Page imports during the static build

ProperDocs now renders URL and local-file imports through `page-import`. The
cache-only command refreshes raw sources by URL hash. An offline import miss
keeps rendered Markdown. Changed stub bodies trigger an offline render so
search indexes the new text in the same build.

Baseline: 108 tests passed. The two new build tests first reproduced an
inherited offline flag breaking an online build and an offline build making an
HTTP request. After migration, 65 tests passed, including the real ProperDocs
build, offline CLI, cache-only CLI, search-index and url22md checks. Ruff
reported no violations and mypy found no issues in seven files. uv synced
49 packages. The toolkit documentation also built with ProperDocs in strict mode.

## 2026-09-23: shared documentation theme (task422)

Added opt-in `theme_assets` to the final publication stage, after Webflow and
static overlays. Missing stylesheet/script links are injected without changing
body bytes; existing asset URLs are deduplicated. HTML fragments remain intact.
Asset URLs must use HTTPS and identify CSS or JavaScript. Tests cover injection,
duplicates, malformed input, fragments, final overlay precedence and output.

Baseline: 96 tests passed. After initial implementation: 105 tests passed.
Full integration test and final release verification remain in progress.
