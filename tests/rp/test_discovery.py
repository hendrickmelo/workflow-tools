"""Tests for repository discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

from workflow_tools.rp.discovery import discover_repos, find_repo


class TestDiscoverRepos:
    """Tests for discover_repos function."""

    def test_finds_git_repos(self, tmp_path: Path) -> None:
        """discover_repos finds git repositories."""
        # Create a git repo
        repo = tmp_path / "my-repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])

        assert len(repos) == 1
        assert repos[0] == repo

    def test_returns_sorted_by_name(self, tmp_path: Path) -> None:
        """discover_repos returns repos sorted by name (case-insensitive)."""
        for name in ["Zebra", "apple", "Banana"]:
            repo = tmp_path / name
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])

        names = [r.name for r in repos]
        assert names == ["apple", "Banana", "Zebra"]

    def test_ignores_non_repos(self, tmp_path: Path) -> None:
        """discover_repos ignores non-git directories."""
        # Create a regular directory
        (tmp_path / "not-a-repo").mkdir()

        # Create a git repo
        repo = tmp_path / "is-a-repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])

        assert len(repos) == 1
        assert repos[0].name == "is-a-repo"

    def test_handles_missing_path(self, tmp_path: Path) -> None:
        """discover_repos handles non-existent paths gracefully."""
        missing = tmp_path / "does-not-exist"
        repos = discover_repos([missing])
        assert repos == []

    def test_deduplicates_repos(self, tmp_path: Path) -> None:
        """discover_repos deduplicates when same repo found via multiple paths."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        # Search same path twice
        repos = discover_repos([tmp_path, tmp_path])

        assert len(repos) == 1


class TestFindRepo:
    """Tests for find_repo function."""

    def test_find_by_exact_path(self, tmp_path: Path) -> None:
        """find_repo matches by exact path."""
        repo = tmp_path / "my-repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])
        found = find_repo(str(repo), repos)

        assert found == repo

    def test_find_by_name(self, tmp_path: Path) -> None:
        """find_repo matches by repository name."""
        repo = tmp_path / "my-repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])
        found = find_repo("my-repo", repos)

        assert found == repo

    def test_find_by_name_case_insensitive(self, tmp_path: Path) -> None:
        """find_repo matches names case-insensitively."""
        repo = tmp_path / "My-Repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])
        found = find_repo("MY-REPO", repos)

        assert found == repo

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """find_repo returns None when no match."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

        repos = discover_repos([tmp_path])
        found = find_repo("nonexistent", repos)

        assert found is None
