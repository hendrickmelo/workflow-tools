"""Git operations shared across workflow tools."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from workflow_tools.common.ui import style_error, style_info


def run_git(*args: str, capture: bool = True, cwd: Path | None = None) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=capture,
            text=True,
            cwd=cwd,
            check=True,
        )
        return result.stdout.strip() if capture else None
    except subprocess.CalledProcessError:
        return None


def find_repo_root() -> Path | None:
    """Find the root of the main git repository (not worktree)."""
    # Get the common git dir (shared across worktrees)
    git_common = run_git("rev-parse", "--git-common-dir")
    if not git_common:
        return None

    git_common_path = Path(git_common).resolve()

    # If it's a bare repo's .git or ends with .git, parent is repo root
    if git_common_path.name == ".git":
        return git_common_path.parent

    # For worktrees, git-common-dir points to main repo's .git
    return git_common_path.parent


def require_repo() -> Path:
    """Get repo root or exit with error."""
    repo_root = find_repo_root()
    if not repo_root:
        click.echo(style_error("Not in a git repository"), err=True)
        sys.exit(1)
    return repo_root


def get_default_branch(repo_root: Path) -> str:
    """Detect the default branch (main/master/etc)."""
    # Try to get from remote HEAD
    result = run_git("symbolic-ref", "refs/remotes/origin/HEAD", cwd=repo_root)
    if result:
        return result.split("/")[-1]

    # Check common names
    for branch in ["main", "master"]:
        if run_git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=repo_root):
            return branch

    return "main"  # fallback


def get_current_branch() -> str | None:
    """Get the current branch name."""
    return run_git("branch", "--show-current")


def list_branches(repo_root: Path, *, include_remote: bool = True) -> list[str]:
    """List all branches."""
    args = ["branch", "--format=%(refname:short)"]
    if include_remote:
        args.append("-a")

    result = run_git(*args, cwd=repo_root)
    if not result:
        return []

    branches: list[str] = []
    for line in result.split("\n"):
        branch = line.strip()
        if branch and "HEAD" not in branch:
            branches.append(branch)

    return sorted(set(branches))


def fetch_origin(repo_root: Path) -> bool:
    """Fetch from origin. Returns True on success."""
    click.echo(style_info("Fetching from origin..."))
    result = subprocess.run(
        ["git", "fetch", "--prune", "origin"],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_repo_dirty(repo_path: Path) -> bool:
    """Check if a repository has uncommitted changes."""
    result = run_git("status", "--porcelain", cwd=repo_path)
    return bool(result and result.strip())
