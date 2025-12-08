"""Generic caching utilities for workflow tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class JSONCache:
    """Simple JSON file cache with TTL support."""

    def __init__(
        self,
        cache_file: Path,
        ttl_seconds: int = 3600,
    ) -> None:
        """Initialize cache.

        Args:
            cache_file: Path to the cache file
            ttl_seconds: Time-to-live in seconds (default: 1 hour)
        """
        self.cache_file = cache_file
        self.ttl_seconds = ttl_seconds

    def is_valid(self) -> bool:
        """Check if cache exists and is not expired."""
        if not self.cache_file.exists():
            return False
        try:
            mtime = self.cache_file.stat().st_mtime
            return (time.time() - mtime) < self.ttl_seconds
        except OSError:
            return False

    def get(self) -> Any | None:
        """Get cached data if valid, else None."""
        if not self.is_valid():
            return None
        try:
            return json.loads(self.cache_file.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, data: Any) -> None:
        """Save data to cache."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(data, indent=2, default=str))

    def invalidate(self) -> None:
        """Remove cache file."""
        try:
            self.cache_file.unlink(missing_ok=True)
        except OSError:
            pass

    def get_or_compute(self, compute_fn: Any) -> Any:
        """Get cached data or compute and cache it.

        Args:
            compute_fn: Callable that returns data to cache
        """
        data = self.get()
        if data is not None:
            return data
        data = compute_fn()
        self.set(data)
        return data
