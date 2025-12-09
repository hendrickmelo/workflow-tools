"""Input validation utilities for security and safety."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

# GitHub limits
GITHUB_OWNER_MAX_LENGTH = 39
GITHUB_REPO_MAX_LENGTH = 100


class ValidationError(Exception):
    """Raised when input validation fails."""

    pass


def validate_worktree_name(name: str) -> str:
    """Validate worktree name: no path traversal, reasonable characters.

    Returns validated name or raises ValidationError.
    """
    if not name:
        raise ValidationError("Worktree name cannot be empty")

    # Block path traversal
    if ".." in name or name.startswith("/") or name.startswith("~"):
        raise ValidationError(
            f"Invalid worktree name: {name!r} (path traversal not allowed)"
        )

    # Block path separators
    if "/" in name or "\\" in name:
        raise ValidationError(
            f"Invalid worktree name: {name!r} (path separators not allowed)"
        )

    # Allow alphanumeric, hyphens, underscores, dots (but not leading dots)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", name):
        raise ValidationError(
            f"Invalid worktree name: {name!r} (use alphanumeric, hyphens, underscores)"
        )

    return name


def validate_branch_name(branch: str) -> str:
    """Validate git branch name per git-check-ref-format rules.

    Returns the branch name or raises ValidationError.
    """
    if not branch:
        raise ValidationError("Branch name cannot be empty")

    # Common dangerous patterns
    forbidden = ["..", "~", "^", ":", "\\", " ", "\t", "\n", "?", "*", "["]
    for char in forbidden:
        if char in branch:
            raise ValidationError(f"Invalid branch name: contains {char!r}")

    # Must not start/end with slash or dot
    if branch.startswith("/") or branch.endswith("/"):
        raise ValidationError("Branch name cannot start or end with /")
    if branch.startswith(".") or branch.endswith("."):
        raise ValidationError("Branch name cannot start or end with .")
    if branch.endswith(".lock"):
        raise ValidationError("Branch name cannot end with .lock")

    # No consecutive slashes
    if "//" in branch:
        raise ValidationError("Branch name cannot contain consecutive slashes")

    return branch


def validate_pr_number(pr_num: int | str) -> int:
    """Validate PR number is a positive integer.

    Returns validated int or raises ValidationError.
    """
    try:
        num = int(pr_num)
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid PR number: {pr_num!r}") from e

    if num <= 0:
        raise ValidationError(f"PR number must be positive: {num}")

    return num


def validate_github_owner(owner: str) -> str:
    """Validate GitHub username/organization name.

    GitHub usernames: 1-39 chars, alphanumeric or hyphen, cannot start with hyphen.
    Returns validated name or raises ValidationError.
    """
    if not owner:
        raise ValidationError("GitHub owner cannot be empty")

    if len(owner) > GITHUB_OWNER_MAX_LENGTH:
        raise ValidationError(f"GitHub owner too long: {owner!r}")

    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$", owner):
        raise ValidationError(f"Invalid GitHub owner: {owner!r}")

    # Cannot have consecutive hyphens or end with hyphen
    if "--" in owner or owner.endswith("-"):
        raise ValidationError(f"Invalid GitHub owner: {owner!r}")

    return owner


def validate_github_repo(repo: str) -> str:
    """Validate GitHub repository name.

    Returns validated name or raises ValidationError.
    """
    if not repo:
        raise ValidationError("Repository name cannot be empty")

    if len(repo) > GITHUB_REPO_MAX_LENGTH:
        raise ValidationError(f"Repository name too long: {repo!r}")

    # GitHub repo names: alphanumeric, hyphens, underscores, dots
    # Cannot be just dots, cannot start with dot
    if repo in (".", ".."):
        raise ValidationError(f"Invalid repository name: {repo!r}")

    if not re.match(r"^[a-zA-Z0-9._-]+$", repo):
        raise ValidationError(f"Invalid repository name: {repo!r}")

    return repo


def validate_path_no_traversal(path_str: str, base_dir: Path | None = None) -> Path:
    """Validate path has no traversal and optionally stays within base_dir.

    Returns resolved Path or raises ValidationError.
    """
    if not path_str:
        raise ValidationError("Path cannot be empty")

    path = Path(path_str)

    # Check for explicit traversal attempts
    if ".." in path.parts:
        raise ValidationError(f"Path traversal not allowed: {path_str!r}")

    resolved = path.resolve()

    if base_dir is not None:
        base_resolved = base_dir.resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError as e:
            raise ValidationError(
                f"Path must be within {base_dir}: {path_str!r}"
            ) from e

    return resolved


def validate_temp_path(path_str: str) -> Path:
    """Validate that a path is within the system temp directory.

    Returns resolved Path or raises ValidationError.
    """
    if not path_str:
        raise ValidationError("Path cannot be empty")

    path = Path(path_str)
    resolved = path.resolve()
    temp_dir = Path(tempfile.gettempdir()).resolve()

    try:
        resolved.relative_to(temp_dir)
    except ValueError as e:
        raise ValidationError(
            f"Path must be within temp directory: {path_str!r}"
        ) from e

    return resolved


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Parse owner/repo from GitHub URL.

    Handles:
    - https://github.com/owner/repo
    - git@github.com:owner/repo.git

    Returns (owner, repo) or None if not a valid GitHub URL.
    """
    if not url:
        return None

    # Match https://github.com/owner/repo or git@github.com:owner/repo
    patterns = [
        r"github\.com[/:]([^/]+)/([^/.]+?)(?:\.git)?/?$",
        r"github\.com[/:]([^/]+)/([^/.]+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner, repo = match.group(1), match.group(2)
            # Validate the extracted values
            try:
                validate_github_owner(owner)
                validate_github_repo(repo)
                return (owner, repo)
            except ValidationError:
                return None

    return None
