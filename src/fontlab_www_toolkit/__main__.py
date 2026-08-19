"""Fire CLI for ``fontlab-www-toolkit``.

Both invocations resolve to :func:`main`:

* ``python -m fontlab_www_toolkit COMMAND``
* ``fontlab-www-toolkit COMMAND`` (console script, also ``uvx fontlab-www-toolkit``)
* ``fontlab-build COMMAND`` (backwards-compatible alias)
"""

# this_file: src/fontlab_www_toolkit/__main__.py

from __future__ import annotations

import sys
from pathlib import Path

import fire

from fontlab_www_toolkit.builder import BuildPaths, SiteBuilder, setup_environment


class Cli:
    """Build, pull-webflow, convert-old, clean, or setup a FontLab site repo."""

    def build(
        self,
        root: str | None = None,
        skip_webflow: bool = False,
        update_stubs: bool = False,
        config: str | None = None,
    ) -> None:
        """Full build: pull Webflow (unless skipped), build, overlay, publish.

        Args:
            root: site repo root; defaults to the current working directory.
            skip_webflow: if true, do not refresh ``wf_cache/`` before building.
            update_stubs: if true, rewrite each Webflow stub's body from the
                cached HTML (via url22md), preserving the original frontmatter.
            config: path to the JSON configuration file.
        """
        builder, paths = _builder(root, config=config)
        builder.build(pull_webflow=not skip_webflow, update_stubs=update_stubs)
        print(f"Published {paths.public}")

    def pull_webflow(
        self,
        root: str | None = None,
        update_stubs: bool = False,
        config: str | None = None,
    ) -> None:
        """Refresh ``wf_cache/`` only.

        Args:
            root: site repo root; defaults to the current working directory.
            update_stubs: if true, rewrite each Webflow stub's body from the
                cached HTML (via url22md), preserving the original frontmatter.
            config: path to the JSON configuration file.
        """
        builder, paths = _builder(root, config=config)
        for path in builder.pull_webflow(update_stubs=update_stubs):
            print(path.relative_to(paths.root))

    def convert_old(self, root: str | None = None, config: str | None = None) -> None:
        """Regenerate OLD pages from ``src_docs/old-pages.yml``.

        Args:
            root: site repo root; defaults to the current working directory.
            config: path to the JSON configuration file.
        """
        builder, paths = _builder(root, config=config)
        for path in builder.convert_old_pages():
            print(path.relative_to(paths.root))

    def clean(self, root: str | None = None, config: str | None = None) -> None:
        """Delete ``build_docs/`` and the matching names under ``public/``.

        Args:
            root: site repo root; defaults to the current working directory.
            config: path to the JSON configuration file.
        """
        builder, _ = _builder(root, config=config)
        builder.clean()

    def setup(
        self,
        root: str | None = None,
        venv: str | None = None,
        clear: bool = False,
    ) -> None:
        """Create / refresh a uv-managed venv for the admin pipeline."""
        _, paths = _builder(root)
        setup_environment(paths.root, Path(venv) if venv else None, clear=clear)

    def version(self) -> None:
        """Print the package version and exit."""
        from fontlab_www_toolkit import __version__

        print(__version__)


def _builder(root: str | None, config: str | None = None) -> tuple[SiteBuilder, BuildPaths]:
    paths = BuildPaths.from_root(Path(root) if root else Path.cwd())
    return SiteBuilder(paths, config_path=config), paths


def main(argv: list[str] | None = None) -> int:
    # `fire.Fire` reads sys.argv when argv is None; pass-through is a no-op.
    if argv is not None:
        sys.argv = [sys.argv[0], *argv]
    fire.Fire(Cli, name="fontlab-www-toolkit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
