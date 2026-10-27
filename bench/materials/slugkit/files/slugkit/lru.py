"""A small least-recently-used cache."""
from collections import OrderedDict


class LRUCache:
    """Keeps at most ``capacity`` items; reading or writing a key makes it the newest."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def put(self, key, value) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)
