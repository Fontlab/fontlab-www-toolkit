---
this_file: WORK.md
---

# Work

## 2026-09-23: shared documentation theme (task422)

Added opt-in `theme_assets` to the final publication stage, after Webflow and
static overlays. Missing stylesheet/script links are injected without changing
body bytes; existing asset URLs are deduplicated. HTML fragments remain intact.
Asset URLs must use HTTPS and identify CSS or JavaScript. Tests cover injection,
duplicates, malformed input, fragments, final overlay precedence and output.

Baseline: 96 tests passed. After initial implementation: 105 tests passed.
Full integration test and final release verification remain in progress.
