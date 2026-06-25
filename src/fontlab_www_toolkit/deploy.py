"""Deployment helpers shared by per-site `deploy.py` scripts.

Three responsibilities:

* Mirror the locally built site into ``web-fontlab/src/ionos/live/<site>/`` so
  the offline backup stays in sync.
* Rsync the same tree to ``fl_ionos:live/<site>/``.
* Commit & push the changes in the current site repo, and (if the local
  backup changed) commit & push in the ``web-fontlab/`` repo too.
"""

# this_file: src/fontlab_www_toolkit/deploy.py

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeployTarget:
    """Per-site deployment configuration."""

    site_root: Path
    site_label: str
    local_source: Path
    backup_dest: Path
    remote_host: str = "fl_ionos"
    remote_path: str = ""
    rsync_excludes: tuple[str, ...] = (
        ".git/",
        ".venv/",
        ".DS_Store",
        "__pycache__/",
        ".pytest_cache/",
        ".ruff_cache/",
    )
    rsync_delete: bool = True
    preserve_remote_subpaths: tuple[str, ...] = ()


def find_web_fontlab(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a sibling ``web-fontlab/`` checkout."""
    for parent in [start.resolve(), *start.resolve().parents]:
        candidate = parent / "web-fontlab"
        if (candidate / ".git").exists():
            return candidate
        if (parent.parent / "web-fontlab" / ".git").exists():
            return parent.parent / "web-fontlab"
    return None


def mirror_local(source: Path, destination: Path) -> bool:
    """Copy ``source/`` into ``destination/`` using rsync semantics.

    Returns True if anything was copied, False if the destination's parent
    doesn't exist (i.e., the local mirror isn't set up).
    """
    if not destination.parent.exists():
        return False
    if not source.exists():
        raise FileNotFoundError(f"Nothing to mirror — {source} does not exist")
    destination.mkdir(parents=True, exist_ok=True)
    rsync = shutil.which("rsync")
    if rsync:
        cmd = [
            rsync, "-a", "--delete",
            "--exclude=.DS_Store",
            f"{source}/",
            f"{destination}/",
        ]
        subprocess.run(cmd, check=True)
    else:
        # Fallback: replace directory atomically.
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    return True


def rsync_remote(target: DeployTarget) -> None:
    rsync = shutil.which("rsync")
    if rsync is None:
        raise SystemExit("rsync is required for remote deploy.")
    # ``--info=progress2`` shows a single live overall-progress line (percent,
    # transfer rate, ETA); ``-h`` makes sizes human-readable. ``--info=name0``
    # silences the per-file name spam so the progress line stays readable.
    # Without these the transfer is silent and looks hung on large trees.
    cmd = [rsync, "-az", "-h", "--info=progress2,name0"]
    if target.rsync_delete:
        cmd.append("--delete")
    for ex in target.rsync_excludes:
        cmd.extend(["--exclude", ex])
    for keep in target.preserve_remote_subpaths:
        cmd.extend(["--exclude", keep])
    remote = f"{target.remote_host}:{target.remote_path}/"
    cmd.extend([f"{target.local_source}/", remote])
    subprocess.run(cmd, check=True)


def git_status_dirty(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip() != ""


def git_commit_push(repo: Path, message: str) -> bool:
    """Stage everything, commit if dirty, push. Returns True if a commit was made."""
    if not (repo / ".git").exists():
        return False
    if not git_status_dirty(repo):
        return False
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "push"], check=True)
    return True


def run_full_deploy(
    target: DeployTarget,
    *,
    commit_message: str,
    web_fontlab_commit_message: str | None = None,
) -> None:
    """End-to-end deploy: mirror → rsync → commit-push (site + web-fontlab)."""
    backup_parent = target.backup_dest.parent
    mirrored = backup_parent.exists()
    if mirrored:
        mirror_local(target.local_source, target.backup_dest)
        print(f"[mirror] {target.local_source} → {target.backup_dest}")
    else:
        print(f"[mirror] skip (no {backup_parent})")

    if target.remote_path:
        rsync_remote(target)
        print(f"[rsync ] {target.local_source} → {target.remote_host}:{target.remote_path}")
    else:
        print("[rsync ] skip (no remote_path configured)")

    if git_commit_push(target.site_root, commit_message):
        print(f"[git   ] committed & pushed in {target.site_root}")
    else:
        print(f"[git   ] nothing to commit in {target.site_root}")

    if mirrored:
        wf = find_web_fontlab(target.site_root)
        if wf is not None:
            msg = web_fontlab_commit_message or f"Mirror {target.site_label} → ionos/live/"
            if git_commit_push(wf, msg):
                print(f"[git   ] committed & pushed in {wf}")
            else:
                print(f"[git   ] nothing to commit in {wf}")
