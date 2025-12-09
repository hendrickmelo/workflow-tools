"""Shared test fixtures for workflow-tools."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    # Create initial commit so branch exists
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


@pytest.fixture
def mock_subprocess_run(mocker: Any) -> MagicMock:
    """Mock subprocess.run for testing git commands without a real repo."""
    return mocker.patch("subprocess.run")


@pytest.fixture
def mock_gh_response() -> dict[str, Any]:
    """Sample GitHub CLI response for PR data."""
    return {
        "number": 123,
        "id": "PR_abc123",
        "title": "Test PR",
        "body": "Test body",
        "url": "https://github.com/owner/repo/pull/123",
        "state": "OPEN",
        "author": {"login": "testuser"},
        "baseRefName": "main",
        "headRefName": "feature-branch",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviewDecision": "APPROVED",
        "additions": 10,
        "deletions": 5,
        "changedFiles": 3,
    }
