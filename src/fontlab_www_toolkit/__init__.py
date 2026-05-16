"""Shared ProperDocs+MaterialX site builder and deploy helpers for FontLab web properties."""

# this_file: src/fontlab_www_toolkit/__init__.py

from fontlab_www_toolkit.builder import (
    BuildPaths,
    OldPageMapping,
    SiteBuilder,
    WebflowPage,
)
from fontlab_www_toolkit.deploy import (
    DeployTarget,
    find_web_fontlab,
    git_commit_push,
    mirror_local,
    rsync_remote,
    run_full_deploy,
)

try:
    from fontlab_www_toolkit.__version__ import __version__
except ImportError:  # editable install before hatch-vcs has written the file
    __version__ = "0.0.0.dev0"

__all__ = [
    "BuildPaths",
    "DeployTarget",
    "OldPageMapping",
    "SiteBuilder",
    "WebflowPage",
    "__version__",
    "find_web_fontlab",
    "git_commit_push",
    "mirror_local",
    "rsync_remote",
    "run_full_deploy",
]
