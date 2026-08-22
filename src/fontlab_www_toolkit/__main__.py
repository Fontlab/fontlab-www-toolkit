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
    """Build, pull-webflow, convert-old, clean, setup, or mirror a FontLab site."""

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

    def mirror(
        self,
        manifest_url: str,
        dest: str,
        dry_run: bool = False,
        timeout: float = 60.0,
    ) -> None:
        """Mirror a static site folder over HTTPS from its ``manifest.json``.

        Used by api.fontlab.com/www-admin to republish e.g.
        https://fontlab.dev/tth-debugger/alpha-sdx992/ into
        studio.fontlab.com/public/tth-debugger/. Every file is verified
        (size + SHA-256) and the destination folder is swapped atomically.

        Args:
            manifest_url: https URL of the producer's ``manifest.json``.
            dest: destination folder (replaced on success).
            dry_run: list what would change without writing.
            timeout: per-request timeout in seconds.
        """
        from fontlab_www_toolkit.mirror import MirrorError, mirror

        try:
            res = mirror(manifest_url, Path(dest), dry_run=dry_run, timeout=timeout)
        except MirrorError as e:
            print(f"mirror failed: {e}", file=sys.stderr)
            raise SystemExit(1) from e
        if not dry_run:
            print(f"Mirrored {res.manifest.name} {res.manifest.version} -> {res.dest}")

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
