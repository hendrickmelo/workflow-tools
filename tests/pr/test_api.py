"""Tests for PR API functions."""

from __future__ import annotations

import json
from subprocess import CalledProcessError
from typing import Any
from unittest.mock import MagicMock

from workflow_tools.pr.api import (
    PRListInfo,
    format_date,
    get_current_branch,
    get_pr_files,
    get_pr_for_branch,
    list_prs_simple,
)


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    def test_returns_branch_name(self, tmp_path: Any, mocker: Any) -> None:
        """get_current_branch returns the branch name."""
        mock_result = MagicMock()
        mock_result.stdout = "feature-branch\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        branch = get_current_branch()
        assert branch == "feature-branch"

    def test_returns_none_on_error(self, mocker: Any) -> None:
        """get_current_branch returns None on subprocess error."""
        mocker.patch("subprocess.run", side_effect=CalledProcessError(1, "git"))

        branch = get_current_branch()
        assert branch is None


class TestListPrsSimple:
    """Tests for list_prs_simple function."""

    def test_parses_pr_list(self, mocker: Any) -> None:
        """list_prs_simple parses gh pr list output."""
        mock_data = [
            {
                "number": 1,
                "title": "First PR",
                "headRefName": "feature-1",
                "isDraft": False,
            },
            {
                "number": 2,
                "title": "Second PR",
                "headRefName": "feature-2",
                "isDraft": True,
            },
        ]
        mocker.patch(
            "workflow_tools.pr.api.run_gh",
            return_value=json.dumps(mock_data),
        )

        prs = list_prs_simple()

        assert len(prs) == 2
        assert prs[0] == PRListInfo(
            number=1, title="First PR", branch="feature-1", is_draft=False
        )
        assert prs[1] == PRListInfo(
            number=2, title="Second PR", branch="feature-2", is_draft=True
        )

    def test_returns_empty_list_on_error(self, mocker: Any) -> None:
        """list_prs_simple returns empty list when gh fails."""
        mocker.patch("workflow_tools.pr.api.run_gh", return_value=None)

        prs = list_prs_simple()

        assert prs == []

    def test_handles_invalid_json(self, mocker: Any) -> None:
        """list_prs_simple handles invalid JSON gracefully."""
        mocker.patch(
            "workflow_tools.pr.api.run_gh",
            return_value="not valid json",
        )

        prs = list_prs_simple()

        assert prs == []


class TestGetPrForBranch:
    """Tests for get_pr_for_branch function."""

    def test_parses_pr_data(
        self, mocker: Any, mock_gh_response: dict[str, Any]
    ) -> None:
        """get_pr_for_branch parses PR data correctly."""
        mocker.patch(
            "workflow_tools.pr.api.run_gh",
            return_value=json.dumps(mock_gh_response),
        )

        pr = get_pr_for_branch(123)

        assert pr is not None
        assert pr.number == 123
        assert pr.title == "Test PR"
        assert pr.author == "testuser"
        assert pr.is_draft is False
        assert pr.additions == 10
        assert pr.deletions == 5

    def test_returns_none_when_no_pr(self, mocker: Any) -> None:
        """get_pr_for_branch returns None when no PR exists."""
        mocker.patch("workflow_tools.pr.api.run_gh", return_value=None)

        pr = get_pr_for_branch()

        assert pr is None

    def test_handles_missing_optional_fields(self, mocker: Any) -> None:
        """get_pr_for_branch handles missing optional fields."""
        minimal_data = {
            "number": 1,
            "id": "PR_1",
            "title": "Test",
            "url": "https://github.com/o/r/pull/1",
            "state": "OPEN",
            "author": {"login": "user"},
            "baseRefName": "main",
            "headRefName": "branch",
            "isDraft": False,
        }
        mocker.patch(
            "workflow_tools.pr.api.run_gh",
            return_value=json.dumps(minimal_data),
        )

        pr = get_pr_for_branch(1)

        assert pr is not None
        assert pr.body is None
        assert pr.additions == 0
        assert pr.deletions == 0


class TestGetPrFiles:
    """Tests for get_pr_files function."""

    def test_returns_file_list(self, mocker: Any) -> None:
        """get_pr_files returns list of changed files."""
        mocker.patch(
            "workflow_tools.pr.api.run_gh",
            return_value="src/main.py\nsrc/utils.py\nREADME.md",
        )

        files = get_pr_files(123)

        assert files == ["src/main.py", "src/utils.py", "README.md"]

    def test_returns_empty_on_error(self, mocker: Any) -> None:
        """get_pr_files returns empty list on error."""
        mocker.patch("workflow_tools.pr.api.run_gh", return_value=None)

        files = get_pr_files(123)

        assert files == []

    def test_filters_empty_lines(self, mocker: Any) -> None:
        """get_pr_files filters out empty lines."""
        mocker.patch(
            "workflow_tools.pr.api.run_gh",
            return_value="file1.py\n\nfile2.py\n",
        )

        files = get_pr_files(123)

        assert files == ["file1.py", "file2.py"]


class TestFormatDate:
    """Tests for format_date function."""

    def test_formats_iso_date(self) -> None:
        """format_date formats ISO date strings."""
        result = format_date("2024-01-15T10:30:00Z")
        assert result == "2024-01-15 10:30"

    def test_handles_invalid_date(self) -> None:
        """format_date returns input for invalid dates."""
        result = format_date("not a date")
        assert result == "not a date"

    def test_handles_empty_string(self) -> None:
        """format_date handles empty string."""
        result = format_date("")
        assert result == ""
