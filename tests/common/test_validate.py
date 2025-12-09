"""Tests for validation utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from workflow_tools.common.validate import (
    ValidationError,
    parse_github_url,
    validate_branch_name,
    validate_github_owner,
    validate_github_repo,
    validate_path_no_traversal,
    validate_pr_number,
    validate_temp_path,
    validate_worktree_name,
)


class TestValidateWorktreeName:
    """Tests for validate_worktree_name."""

    def test_valid_simple_name(self) -> None:
        assert validate_worktree_name("feature-123") == "feature-123"

    def test_valid_with_underscores(self) -> None:
        assert validate_worktree_name("my_feature") == "my_feature"

    def test_valid_with_dots(self) -> None:
        assert validate_worktree_name("v1.2.3") == "v1.2.3"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_worktree_name("")

    def test_path_traversal_double_dots(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_worktree_name("../etc/passwd")

    def test_path_traversal_absolute(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_worktree_name("/etc/passwd")

    def test_path_traversal_home(self) -> None:
        with pytest.raises(ValidationError, match="path traversal"):
            validate_worktree_name("~/.ssh/id_rsa")

    def test_slash_in_name(self) -> None:
        with pytest.raises(ValidationError, match="path separators"):
            validate_worktree_name("feature/branch")

    def test_backslash_in_name(self) -> None:
        with pytest.raises(ValidationError, match="path separators"):
            validate_worktree_name("feature\\branch")

    def test_leading_dot_rejected(self) -> None:
        with pytest.raises(ValidationError, match="alphanumeric"):
            validate_worktree_name(".hidden")

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="alphanumeric"):
            validate_worktree_name("feature$name")


class TestValidateBranchName:
    """Tests for validate_branch_name."""

    def test_valid_simple(self) -> None:
        assert validate_branch_name("main") == "main"

    def test_valid_with_slash(self) -> None:
        assert validate_branch_name("feature/add-login") == "feature/add-login"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_branch_name("")

    def test_double_dot_rejected(self) -> None:
        with pytest.raises(ValidationError, match="contains"):
            validate_branch_name("feature..branch")

    def test_tilde_rejected(self) -> None:
        with pytest.raises(ValidationError, match="contains"):
            validate_branch_name("feature~1")

    def test_caret_rejected(self) -> None:
        with pytest.raises(ValidationError, match="contains"):
            validate_branch_name("feature^2")

    def test_leading_slash_rejected(self) -> None:
        with pytest.raises(ValidationError, match="start or end"):
            validate_branch_name("/feature")

    def test_trailing_slash_rejected(self) -> None:
        with pytest.raises(ValidationError, match="start or end"):
            validate_branch_name("feature/")

    def test_leading_dot_rejected(self) -> None:
        with pytest.raises(ValidationError, match="start or end"):
            validate_branch_name(".feature")

    def test_lock_suffix_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"\.lock"):
            validate_branch_name("branch.lock")

    def test_consecutive_slashes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="consecutive"):
            validate_branch_name("feature//branch")


class TestValidatePrNumber:
    """Tests for validate_pr_number."""

    def test_valid_int(self) -> None:
        assert validate_pr_number(123) == 123

    def test_valid_string(self) -> None:
        assert validate_pr_number("456") == 456

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            validate_pr_number(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            validate_pr_number(-5)

    def test_non_numeric_string_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid PR number"):
            validate_pr_number("abc")

    def test_none_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid PR number"):
            validate_pr_number(None)  # type: ignore[arg-type]


class TestValidateGithubOwner:
    """Tests for validate_github_owner."""

    def test_valid_username(self) -> None:
        assert validate_github_owner("octocat") == "octocat"

    def test_valid_with_hyphen(self) -> None:
        assert validate_github_owner("my-org") == "my-org"

    def test_valid_with_numbers(self) -> None:
        assert validate_github_owner("user123") == "user123"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_github_owner("")

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError, match="too long"):
            validate_github_owner("a" * 40)

    def test_leading_hyphen_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_owner("-user")

    def test_consecutive_hyphens_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_owner("my--org")

    def test_trailing_hyphen_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_owner("user-")

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_owner("user_name")


class TestValidateGithubRepo:
    """Tests for validate_github_repo."""

    def test_valid_simple(self) -> None:
        assert validate_github_repo("my-repo") == "my-repo"

    def test_valid_with_dots(self) -> None:
        assert validate_github_repo("repo.js") == "repo.js"

    def test_valid_with_underscore(self) -> None:
        assert validate_github_repo("my_repo") == "my_repo"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_github_repo("")

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError, match="too long"):
            validate_github_repo("a" * 101)

    def test_single_dot_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_repo(".")

    def test_double_dot_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_repo("..")

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid"):
            validate_github_repo("repo$name")


class TestValidatePathNoTraversal:
    """Tests for validate_path_no_traversal."""

    def test_valid_simple_path(self, tmp_path: Path) -> None:
        test_file = tmp_path / "file.txt"
        test_file.touch()
        result = validate_path_no_traversal(str(test_file))
        assert result == test_file.resolve()

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_path_no_traversal("")

    def test_double_dot_in_parts_rejected(self) -> None:
        with pytest.raises(ValidationError, match="traversal"):
            validate_path_no_traversal("/foo/../bar")

    def test_within_base_dir(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        test_file = subdir / "file.txt"
        test_file.touch()
        result = validate_path_no_traversal(str(test_file), base_dir=tmp_path)
        assert result == test_file.resolve()

    def test_outside_base_dir_rejected(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "file.txt"
        outside_file.touch()
        with pytest.raises(ValidationError, match="must be within"):
            validate_path_no_traversal(str(outside_file), base_dir=base)


class TestValidateTempPath:
    """Tests for validate_temp_path."""

    def test_valid_temp_path(self) -> None:
        temp_dir = Path(tempfile.gettempdir())
        test_path = temp_dir / "test_file.txt"
        result = validate_temp_path(str(test_path))
        assert result == test_path.resolve()

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_temp_path("")

    def test_non_temp_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="temp directory"):
            validate_temp_path("/etc/passwd")


class TestParseGithubUrl:
    """Tests for parse_github_url."""

    def test_https_url(self) -> None:
        result = parse_github_url("https://github.com/owner/repo")
        assert result == ("owner", "repo")

    def test_https_url_with_git_suffix(self) -> None:
        result = parse_github_url("https://github.com/owner/repo.git")
        assert result == ("owner", "repo")

    def test_ssh_url(self) -> None:
        result = parse_github_url("git@github.com:owner/repo.git")
        assert result == ("owner", "repo")

    def test_ssh_url_no_git_suffix(self) -> None:
        result = parse_github_url("git@github.com:owner/repo")
        assert result == ("owner", "repo")

    def test_empty_url_returns_none(self) -> None:
        assert parse_github_url("") is None

    def test_non_github_url_returns_none(self) -> None:
        assert parse_github_url("https://gitlab.com/owner/repo") is None

    def test_invalid_owner_returns_none(self) -> None:
        # Leading hyphen in owner
        assert parse_github_url("https://github.com/-invalid/repo") is None

    def test_trailing_slash(self) -> None:
        result = parse_github_url("https://github.com/owner/repo/")
        assert result == ("owner", "repo")
