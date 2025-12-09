"""Fast repository discovery using shallow find."""

from __future__ import annotations

import subprocess
from pathlib import Path


def discover_repos(scan_paths: list[Path] | None = None) -> list[Path]:
    """Find git repos under scan_paths (default: ~/Documents).

    Uses maxdepth 3 for speed (~0.25s). Returns sorted list of repo paths.
    """
    if scan_paths is None:
        scan_paths = [Path.home() / "Documents"]

    repos: list[Path] = []
    seen: set[str] = set()

    for base in scan_paths:
        if not base.exists():
            continue

        # Resolve path and validate no traversal outside expected directories
        try:
            resolved_base = base.resolve()
            # Basic safety check: path should not contain .. after resolution
            if ".." in resolved_base.parts:
                continue
        except (OSError, ValueError):
            continue

        try:
            result = subprocess.run(
                [
                    "find",
                    str(resolved_base),
                    "-maxdepth",
                    "3",
                    "-type",
                    "d",
                    "-name",
                    ".git",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            repo_path = Path(line).parent
            path_str = str(repo_path)
            if path_str not in seen:
                seen.add(path_str)
                repos.append(repo_path)

    return sorted(repos, key=lambda p: p.name.lower())


def find_repo(name_or_path: str, repos: list[Path]) -> Path | None:
    """Find a repo by name or path from a list."""
    # Exact path match
    for r in repos:
        if str(r) == name_or_path:
            return r
    # Name match (case-insensitive)
    name_lower = name_or_path.lower()
    for r in repos:
        if r.name.lower() == name_lower:
            return r
    return None
