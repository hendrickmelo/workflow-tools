"""Fast repository discovery with caching."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from workflow_tools.common.cache import JSONCache
from workflow_tools.common.git import run_git


class RepoInfo(NamedTuple):
    """Information about a git repository."""

    name: str
    path: str  # String for JSON serialization
    remote: str | None
    remote_type: str  # "github", "gitlab", "bitbucket", "other", "local"


def categorize_remote(remote: str | None) -> str:
    """Categorize the remote URL type."""
    if not remote:
        return "local"
    remote_lower = remote.lower()
    if "github.com" in remote_lower:
        return "github"
    if "gitlab" in remote_lower:
        return "gitlab"
    if "bitbucket" in remote_lower:
        return "bitbucket"
    return "other"


def extract_repo_info(repo_path: Path) -> RepoInfo:
    """Extract name, path, and remote info from a repo."""
    name = repo_path.name
    remote = run_git("remote", "get-url", "origin", cwd=repo_path)
    remote_type = categorize_remote(remote)
    return RepoInfo(
        name=name,
        path=str(repo_path),
        remote=remote,
        remote_type=remote_type,
    )


def discover_repos(scan_paths: list[Path]) -> list[RepoInfo]:
    """Discover all git repositories under the given paths.

    Uses `find` with `-prune` for fast scanning (~200ms for 100-500 repos).
    Skips common directories that don't contain user repos.
    """
    repos: list[RepoInfo] = []
    seen_paths: set[str] = set()

    for base in scan_paths:
        if not base.exists():
            continue

        # Use find with -prune to skip .git internals and other slow dirs
        # This is much faster than os.walk
        try:
            result = subprocess.run(
                [
                    "find",
                    str(base),
                    "-type",
                    "d",
                    "(",
                    "-name",
                    "node_modules",
                    "-o",
                    "-name",
                    ".pixi",
                    "-o",
                    "-name",
                    "__pycache__",
                    "-o",
                    "-name",
                    "venv",
                    "-o",
                    "-name",
                    ".venv",
                    "-o",
                    "-name",
                    ".tox",
                    "-o",
                    "-name",
                    "target",  # Rust target dir
                    "-o",
                    "-name",
                    "build",
                    "-o",
                    "-name",
                    "dist",
                    ")",
                    "-prune",
                    "-o",
                    "-type",
                    "d",
                    "-name",
                    ".git",
                    "-print",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        for git_dir in result.stdout.strip().split("\n"):
            if not git_dir:
                continue

            repo_path = Path(git_dir).parent
            path_str = str(repo_path)

            # Avoid duplicates
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)

            # Skip repos under hidden directories (e.g., .terraform, .cache)
            # Check if any parent directory starts with a dot
            relative_to_base = repo_path.relative_to(base)
            if any(part.startswith(".") for part in relative_to_base.parts):
                continue

            try:
                info = extract_repo_info(repo_path)
                repos.append(info)
            except Exception:
                # Skip repos we can't read
                continue

    return sorted(repos, key=lambda r: r.name.lower())


class RepoCache:
    """Cache for discovered repositories."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        scan_paths: list[Path] | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        """Initialize repo cache.

        Args:
            cache_dir: Directory for cache files (default: ~/.cache/workflow-tools)
            scan_paths: Paths to scan for repos (default: ~/Documents)
            ttl_seconds: Cache TTL in seconds (default: 1 hour)
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "workflow-tools"

        if scan_paths is None:
            scan_paths = [Path.home() / "Documents"]

        self.scan_paths = scan_paths
        self._cache = JSONCache(cache_dir / "repos.json", ttl_seconds)

    def get_repos(
        self, *, force_refresh: bool = False, show_progress: bool = False
    ) -> tuple[list[RepoInfo], bool]:
        """Get list of repos, using cache if valid.

        Args:
            force_refresh: Force a cache refresh even if cache is valid.
            show_progress: Show a message to stderr when scanning.

        Returns:
            Tuple of (repos, from_cache) where from_cache indicates if cache was used.
        """
        if force_refresh:
            return self._refresh(show_progress=show_progress), False

        cached = self._cache.get()
        if cached is not None:
            return [RepoInfo(**r) for r in cached], True

        return self._refresh(show_progress=show_progress), False

    def _refresh(self, *, show_progress: bool = False) -> list[RepoInfo]:
        """Refresh cache by scanning for repos."""
        if show_progress:
            sys.stderr.write("Scanning for repositories...\n")
            sys.stderr.flush()
        repos = discover_repos(self.scan_paths)
        self._cache.set([r._asdict() for r in repos])
        return repos

    def invalidate(self) -> None:
        """Invalidate the cache."""
        self._cache.invalidate()

    def add_repo(self, repo_path: Path) -> None:
        """Add a new repo to the cache (call after clone/create)."""
        repos, _ = self.get_repos()
        info = extract_repo_info(repo_path)

        # Check if already exists
        if any(r.path == str(repo_path) for r in repos):
            return

        repos.append(info)
        repos.sort(key=lambda r: r.name.lower())
        self._cache.set([r._asdict() for r in repos])

    def remove_repo(self, repo_path: Path) -> None:
        """Remove a repo from the cache."""
        repos, _ = self.get_repos()
        path_str = str(repo_path)
        repos = [r for r in repos if r.path != path_str]
        self._cache.set([r._asdict() for r in repos])

    def find_repo(self, name_or_path: str) -> RepoInfo | None:
        """Find a repo by name or path."""
        repos, _ = self.get_repos()

        # Check exact path match first
        for r in repos:
            if r.path == name_or_path:
                return r

        # Check name match
        for r in repos:
            if r.name == name_or_path:
                return r

        # Check partial name match
        name_lower = name_or_path.lower()
        for r in repos:
            if r.name.lower() == name_lower:
                return r

        return None
