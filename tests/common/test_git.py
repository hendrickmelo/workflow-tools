"""Tests for git operations."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from workflow_tools.common.git import (
    find_repo_root,
    get_current_branch,
    get_default_branch,
    is_repo_dirty,
    list_branches,
    run_git,
)


class TestRunGit:
    """Tests for run_git function."""

    def test_returns_stdout_on_success(self, tmp_git_repo: Path) -> None:
        """run_git returns stdout for successful commands."""
        result = run_git("status", "--porcelain", cwd=tmp_git_repo)
        assert result is not None
        assert isinstance(result, str)

    def test_returns_none_on_failure(self, tmp_path: Path) -> None:
        """run_git returns None for failed commands."""
        # Run in non-git directory
        result = run_git("status", cwd=tmp_path)
        assert result is None

    def test_capture_false_returns_none(self, tmp_git_repo: Path) -> None:
        """run_git with capture=False returns None on success."""
        result = run_git("status", capture=False, cwd=tmp_git_repo)
        assert result is None


class TestFindRepoRoot:
    """Tests for find_repo_root function."""

    def test_finds_repo_root(self, tmp_git_repo: Path) -> None:
        """find_repo_root returns the repository root."""
        # Change to a subdirectory
        subdir = tmp_git_repo / "subdir"
        subdir.mkdir()

        original_cwd = os.getcwd()
        try:
            os.chdir(subdir)
            root = find_repo_root()
            assert root is not None
            assert root.resolve() == tmp_git_repo.resolve()
        finally:
            os.chdir(original_cwd)

    def test_returns_none_outside_repo(self, tmp_path: Path) -> None:
        """find_repo_root returns None when not in a git repo."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = find_repo_root()
            assert result is None
        finally:
            os.chdir(original_cwd)


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    def test_returns_branch_name(self, tmp_git_repo: Path) -> None:
        """get_current_branch returns the current branch."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_git_repo)
            branch = get_current_branch()
            # Git init creates either 'main' or 'master' depending on config
            assert branch in ("main", "master")
        finally:
            os.chdir(original_cwd)


class TestGetDefaultBranch:
    """Tests for get_default_branch function."""

    def test_returns_main_or_master(self, tmp_git_repo: Path) -> None:
        """get_default_branch returns main or master."""
        branch = get_default_branch(tmp_git_repo)
        assert branch in ("main", "master")

    def test_fallback_to_main(self, tmp_path: Path) -> None:
        """get_default_branch falls back to 'main'."""
        # Create a repo without main or master
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", "develop"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        (tmp_path / "file.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        branch = get_default_branch(tmp_path)
        assert branch == "main"  # fallback


class TestListBranches:
    """Tests for list_branches function."""

    def test_lists_local_branches(self, tmp_git_repo: Path) -> None:
        """list_branches returns local branches."""
        # Create another branch
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=tmp_git_repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "-"],
            cwd=tmp_git_repo,
            capture_output=True,
            check=True,
        )

        branches = list_branches(tmp_git_repo, include_remote=False)

        assert "feature" in branches
        assert any(b in branches for b in ("main", "master"))


class TestIsRepoDirty:
    """Tests for is_repo_dirty function."""

    def test_clean_repo_not_dirty(self, tmp_git_repo: Path) -> None:
        """is_repo_dirty returns False for clean repo."""
        assert is_repo_dirty(tmp_git_repo) is False

    def test_uncommitted_changes_dirty(self, tmp_git_repo: Path) -> None:
        """is_repo_dirty returns True with uncommitted changes."""
        (tmp_git_repo / "new_file.txt").write_text("content")
        assert is_repo_dirty(tmp_git_repo) is True

    def test_staged_changes_dirty(self, tmp_git_repo: Path) -> None:
        """is_repo_dirty returns True with staged changes."""
        (tmp_git_repo / "staged.txt").write_text("content")
        subprocess.run(
            ["git", "add", "staged.txt"],
            cwd=tmp_git_repo,
            capture_output=True,
            check=True,
        )
        assert is_repo_dirty(tmp_git_repo) is True
