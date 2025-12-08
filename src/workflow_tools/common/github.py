"""GitHub CLI operations shared across workflow tools."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def run_gh(*args: str, capture: bool = True) -> str | None:
    """Run a gh CLI command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=capture,
            text=True,
            check=True,
        )
        return result.stdout.strip() if capture else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run_gh_json(*args: str) -> Any | None:
    """Run a gh CLI command and parse JSON output."""
    result = run_gh(*args)
    if result is None:
        return None
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return None


def gh_api_graphql(query: str, variables: dict[str, Any] | None = None) -> Any | None:
    """Execute a GraphQL query via gh api graphql."""
    cmd = ["api", "graphql"]

    if variables:
        for key, value in variables.items():
            cmd.extend(["-F", f"{key}={value}"])

    cmd.extend(["-f", f"query={query}"])

    return run_gh_json(*cmd)


def get_repo_info() -> tuple[str, str] | None:
    """Get owner/repo from git remote. Returns (owner, name) or None."""
    data = run_gh_json("repo", "view", "--json", "owner,name")
    if not data:
        return None
    return (data["owner"]["login"], data["name"])


def get_viewer_login() -> str | None:
    """Get the current authenticated user's login."""
    result = run_gh("api", "user", "--jq", ".login")
    return result.strip() if result else None
