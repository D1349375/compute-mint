import pytest

from slugkit.lru import LRUCache


def test_stores_and_returns_values():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing", 0) == 0


def test_evicts_the_oldest_when_full():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None


def test_get_marks_a_key_as_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        LRUCache(0)
