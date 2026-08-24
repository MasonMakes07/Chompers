"""A mapping that evicts its least recently used entry once it is full.

A cache with no eviction rule is a memory leak with good intentions. The
geocoder caches were exactly that: every distinct query added an entry that
was never removed, so an attacker varying the fourth decimal of a coordinate
could grow the process forever. A ceiling turns that into a bounded, boring
cache miss.

Kept provider-agnostic so the places cache can adopt the same ceiling without
inventing a second eviction policy.
"""

from collections import OrderedDict
from typing import Generic, TypeVar

CacheKey = TypeVar("CacheKey")
CacheValue = TypeVar("CacheValue")


# ---------------------------------------------------------------------------


class BoundedCache(Generic[CacheKey, CacheValue]):
    """An LRU cache holding at most a fixed number of entries.

    `get` returns None for a miss, so this is only suitable for caches that
    never store None as a real value - true of every caller here.
    """

    # Prepares an empty cache with a ceiling of at least one entry.
    def __init__(self, max_entries: int) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: "OrderedDict[CacheKey, CacheValue]" = OrderedDict()

    # Returns a cached value, marking it most recently used, or None.
    def get(self, key: CacheKey) -> CacheValue | None:
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    # Stores a value, evicting the least recently used entry when over the cap.
    def put(self, key: CacheKey, value: CacheValue) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    # Empties the cache. Used by tests and by any future invalidation.
    def clear(self) -> None:
        self._entries.clear()

    # Reports how many entries are currently held.
    def __len__(self) -> int:
        return len(self._entries)

    # Reports whether a key is cached, without disturbing its recency.
    def __contains__(self, key: object) -> bool:
        return key in self._entries
