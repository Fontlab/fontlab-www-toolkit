---
this_file: WORK.md
---

# Work

## 2026-11-23 — Page-import release checks

Explicit pulls use the plugin’s public `refresh_cache` with the configured timeout
and byte limit. The new stale-cache regression failed before the change. After
the fix, all 78 tests passed, including inherited and environment-valued plugin
entries, pull with stub rewriting, and published Markdown on an offline cache
miss. A separate loopback pull with the installed url22md readability engine
verified the raw cache, preserved front matter and rewritten body.

uv resolved 58 packages. Ruff passed lint and formatting, and mypy passed on
seven source files. Twine passed both distributions. Inspection found 17 files
in the sdist and 12 in the wheel after anchoring Hatch’s sdist include paths.
The wheel declares both requested dependency bounds. The editable plugin’s
installed development version is below 0.1.0, so `uv pip check` reports one
version mismatch pending the plugin release.

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
