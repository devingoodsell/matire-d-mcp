"""In-memory TTL cache with LRU eviction and metrics."""

import time
from collections import OrderedDict


class CacheMetrics:
    """Tracks cache hit/miss statistics."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total


class InMemoryCache:
    """TTL-based cache with LRU eviction.

    Args:
        max_size: Maximum number of entries before eviction.
    """

    def __init__(self, max_size: int = 100) -> None:
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self.metrics = CacheMetrics()

    def get(self, key: str, max_age_seconds: float = 300) -> object | None:
        """Retrieve a value if present and within TTL.

        Args:
            key: Cache key.
            max_age_seconds: Maximum age in seconds.

        Returns:
            Cached value or None.
        """
        entry = self._store.get(key)
        if entry is None:
            self.metrics.misses += 1
            return None

        ts, value = entry
        if time.monotonic() - ts > max_age_seconds:
            del self._store[key]
            self.metrics.misses += 1
            return None

        # Move to end (most recently used)
        self._store.move_to_end(key)
        self.metrics.hits += 1
        return value

    def set(self, key: str, value: object) -> None:
        """Store a value, evicting the oldest entry if at capacity."""
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = (time.monotonic(), value)
            return

        if len(self._store) >= self.max_size:
            self._store.popitem(last=False)

        self._store[key] = (time.monotonic(), value)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if the key existed."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    @property
    def size(self) -> int:
        """Current number of entries."""
        return len(self._store)
