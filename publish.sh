#!/usr/bin/env bash
# this_file: publish.sh
#
# Publish fontlab-www-toolkit to PyPI.
#
# Pipeline:
#   1. Clean any previous build artefacts.
#   2. Bump the git tag to the next semver patch via `uvx gitnextver`.
#   3. Build sdist + wheel.
#   4. Upload to PyPI (uses $UV_PUBLISH_TOKEN).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

uvx hatch clean
uvx gitnextver --directory .
uv build
uv publish
