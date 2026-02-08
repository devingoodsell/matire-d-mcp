"""Tests for src.clients.cache — InMemoryCache with TTL, LRU eviction, and metrics."""

import pytest

from src.clients.cache import CacheMetrics, InMemoryCache


class TestCacheMetrics:
    def test_initial_state(self):
        m = CacheMetrics()
        assert m.hits == 0
        assert m.misses == 0
        assert m.hit_rate == 0.0

    def test_hit_rate_calculation(self):
        m = CacheMetrics()
        m.hits = 3
        m.misses = 1
        assert m.hit_rate == 0.75


class TestInMemoryCache:
    def test_get_on_empty_returns_none(self):
        cache = InMemoryCache()
        assert cache.get("missing") is None

    def test_set_and_get_within_ttl(self):
        cache = InMemoryCache()
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_get_after_ttl_returns_none(self):
        cache = InMemoryCache()
        cache.set("k1", "v1")
        # Manually age the entry
        ts, val = cache._store["k1"]
        cache._store["k1"] = (ts - 400, val)
        assert cache.get("k1", max_age_seconds=300) is None

    def test_eviction_at_max_size(self):
        cache = InMemoryCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3
        assert cache.size == 2

    def test_lru_eviction_order(self):
        cache = InMemoryCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        # Access "a" to make it recently used
        cache.get("a")
        cache.set("c", 3)  # Should evict "b" (least recently used)
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3

    def test_invalidate_existing_key(self):
        cache = InMemoryCache()
        cache.set("k1", "v1")
        assert cache.invalidate("k1") is True
        assert cache.get("k1") is None

    def test_invalidate_missing_key(self):
        cache = InMemoryCache()
        assert cache.invalidate("missing") is False

    def test_clear(self):
        cache = InMemoryCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None

    def test_size_property(self):
        cache = InMemoryCache()
        assert cache.size == 0
        cache.set("a", 1)
        assert cache.size == 1
        cache.set("b", 2)
        assert cache.size == 2

    def test_metrics_tracking(self):
        cache = InMemoryCache()
        cache.set("k1", "v1")
        cache.get("k1")  # hit
        cache.get("k1")  # hit
        cache.get("missing")  # miss
        assert cache.metrics.hits == 2
        assert cache.metrics.misses == 1
        assert cache.metrics.hit_rate == pytest.approx(2 / 3)

    def test_overwrite_existing_key(self):
        cache = InMemoryCache()
        cache.set("k1", "v1")
        cache.set("k1", "v2")
        assert cache.get("k1") == "v2"
        assert cache.size == 1

    def test_expired_entry_not_counted_in_size_after_get(self):
        cache = InMemoryCache()
        cache.set("k1", "v1")
        # Age it
        ts, val = cache._store["k1"]
        cache._store["k1"] = (ts - 400, val)
        cache.get("k1", max_age_seconds=300)  # triggers removal
        assert cache.size == 0
