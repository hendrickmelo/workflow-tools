"""Tests for JSONCache."""

from __future__ import annotations

import time
from pathlib import Path

from workflow_tools.common.cache import JSONCache


class TestJSONCache:
    """Tests for JSONCache class."""

    def test_set_creates_parent_dirs(self, cache_file: Path) -> None:
        """Cache file parent directories are created automatically."""
        cache = JSONCache(cache_file)
        assert not cache_file.parent.exists()

        cache.set({"key": "value"})

        assert cache_file.parent.exists()
        assert cache_file.exists()

    def test_set_and_get(self, cache_file: Path) -> None:
        """Data can be stored and retrieved."""
        cache = JSONCache(cache_file)
        data = {"items": [1, 2, 3], "name": "test"}

        cache.set(data)
        result = cache.get()

        assert result == data

    def test_get_returns_none_when_no_cache(self, cache_file: Path) -> None:
        """get() returns None when cache file doesn't exist."""
        cache = JSONCache(cache_file)
        assert cache.get() is None

    def test_is_valid_false_when_no_file(self, cache_file: Path) -> None:
        """is_valid() returns False when file doesn't exist."""
        cache = JSONCache(cache_file)
        assert cache.is_valid() is False

    def test_is_valid_true_when_fresh(self, cache_file: Path) -> None:
        """is_valid() returns True for fresh cache."""
        cache = JSONCache(cache_file, ttl_seconds=3600)
        cache.set({"data": 123})
        assert cache.is_valid() is True

    def test_is_valid_false_when_expired(self, cache_file: Path) -> None:
        """is_valid() returns False for expired cache."""
        cache = JSONCache(cache_file, ttl_seconds=1)
        cache.set({"data": 123})

        # Wait for expiration
        time.sleep(1.1)

        assert cache.is_valid() is False

    def test_get_returns_none_when_expired(self, cache_file: Path) -> None:
        """get() returns None for expired cache."""
        cache = JSONCache(cache_file, ttl_seconds=1)
        cache.set({"data": 123})

        time.sleep(1.1)

        assert cache.get() is None

    def test_invalidate_removes_file(self, cache_file: Path) -> None:
        """invalidate() removes the cache file."""
        cache = JSONCache(cache_file)
        cache.set({"data": 123})
        assert cache_file.exists()

        cache.invalidate()

        assert not cache_file.exists()

    def test_invalidate_handles_missing_file(self, cache_file: Path) -> None:
        """invalidate() doesn't error when file doesn't exist."""
        cache = JSONCache(cache_file)
        cache.invalidate()  # Should not raise

    def test_get_or_compute_returns_cached(self, cache_file: Path) -> None:
        """get_or_compute returns cached data without calling compute_fn."""
        cache = JSONCache(cache_file)
        cache.set({"cached": True})

        call_count = 0

        def compute() -> dict[str, bool]:
            nonlocal call_count
            call_count += 1
            return {"computed": True}

        result = cache.get_or_compute(compute)

        assert result == {"cached": True}
        assert call_count == 0

    def test_get_or_compute_computes_and_caches(self, cache_file: Path) -> None:
        """get_or_compute calls compute_fn and caches result."""
        cache = JSONCache(cache_file)

        def compute() -> dict[str, int]:
            return {"value": 42}

        result = cache.get_or_compute(compute)

        assert result == {"value": 42}
        assert cache.get() == {"value": 42}

    def test_handles_corrupt_json(self, cache_file: Path) -> None:
        """Cache handles corrupt JSON gracefully."""
        cache = JSONCache(cache_file)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json {{{")

        assert cache.get() is None
        assert cache.is_valid() is True  # File exists and not expired

    def test_handles_non_serializable_data(self, cache_file: Path) -> None:
        """Cache uses default=str for non-serializable data."""
        cache = JSONCache(cache_file)

        # Path objects aren't directly serializable
        cache.set({"path": Path("/tmp/test")})

        result = cache.get()
        assert result == {"path": "/tmp/test"}
