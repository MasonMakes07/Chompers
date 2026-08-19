"""Shared plumbing for every places provider.

Caching, request deduplication, and the on-disk store live here so a provider
only has to implement "fetch these coordinates" and "fetch this intent".
Everything downstream sees `Restaurant` and never learns which service
produced it.
"""

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path

from ..config import get_settings
from ..models.restaurant import Restaurant
from ..models.search_intent import SearchIntent


# ---------------------------------------------------------------------------


class PlacesError(RuntimeError):
    """Raised when the places provider cannot be reached or rejects a query."""

    # True when the same query is worth retrying against another endpoint.
    retryable: bool = False


# Marks an error as worth retrying against a different endpoint or mirror.
def mark_retryable(error: PlacesError) -> PlacesError:
    error.retryable = True
    return error


# ---------------------------------------------------------------------------


class BasePlacesClient(ABC):
    """Caching, deduplication, and disk persistence for any provider."""

    # Short name used in cache keys so providers never share cached results.
    provider_name = "base"

    # Prepares the client with settings, a memory cache, and a dedupe map.
    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: dict[tuple, tuple[float, list[Restaurant]]] = {}
        # Identical queries already in flight, so a duplicate request joins
        # the existing call instead of queueing a second one behind it.
        self._inflight: dict[tuple, "asyncio.Task[list[Restaurant]]"] = {}

    # ---- Provider hooks ---------------------------------------------------

    # Fetches restaurants near a point. Implemented per provider.
    @abstractmethod
    async def _fetch_nearby(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        raise NotImplementedError

    # Fetches restaurants matching a parsed intent. Implemented per provider.
    @abstractmethod
    async def _fetch_by_intent(
        self,
        intent: SearchIntent,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[Restaurant]:
        raise NotImplementedError

    # ---- Public API -------------------------------------------------------

    # Fetches restaurants near a point, using the cache when possible.
    async def search_nearby(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        key = self._cache_key(latitude, longitude, radius_meters)
        cached = self._read_cache(key)
        if cached is not None:
            return cached

        return await self._deduplicated(
            key, lambda: self._fetch_nearby(latitude, longitude, radius_meters)
        )

    # Fetches restaurants matching a parsed search intent near a point.
    async def search_by_intent(
        self,
        intent: SearchIntent,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[Restaurant]:
        # An intent we could not interpret has nothing to filter on, so show
        # everything nearby rather than sending an empty query.
        if intent.is_empty:
            return await self.search_nearby(latitude, longitude, radius_meters)

        key = self._cache_key(
            latitude, longitude, radius_meters, self._intent_cache_key(intent)
        )
        cached = self._read_cache(key)
        if cached is not None:
            return cached

        return await self._deduplicated(
            key,
            lambda: self._fetch_by_intent(
                intent, latitude, longitude, radius_meters
            ),
        )

    # ---- Deduplication ----------------------------------------------------

    # Runs a fetch, collapsing duplicate concurrent requests into one call.
    #
    # Without this, a double-rendered page issues the same search twice; the
    # second waits behind the first and can outlive the browser's patience,
    # so a working search looks like a timeout.
    async def _deduplicated(self, key: tuple, fetch) -> list[Restaurant]:
        existing = self._inflight.get(key)
        if existing is not None:
            # shield keeps one caller giving up from cancelling the shared
            # call that other callers are still waiting on.
            return await asyncio.shield(existing)

        task = asyncio.create_task(self._fetch_and_cache(key, fetch))
        self._inflight[key] = task
        task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    # Performs the provider fetch then stores the result.
    async def _fetch_and_cache(self, key: tuple, fetch) -> list[Restaurant]:
        restaurants = await fetch()
        self._write_cache(key, restaurants)
        return restaurants

    # ---- Cache ------------------------------------------------------------

    # Builds a cache key. The provider is included so switching providers
    # never serves results fetched from the other one.
    def _cache_key(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        query: str | None = None,
    ) -> tuple:
        normalized_query = query.strip().lower() if query else None
        return (
            self.provider_name,
            round(latitude, 3),
            round(longitude, 3),
            radius_meters,
            normalized_query,
        )

    # Builds a stable key so equivalent phrasings share one cache entry.
    @staticmethod
    def _intent_cache_key(intent: SearchIntent) -> str:
        return "|".join(
            (
                ",".join(sorted(item.value for item in intent.diets)),
                ",".join(sorted(intent.cuisines)),
                ",".join(sorted(intent.keywords)),
            )
        )

    # Maps a cache key to the file that holds it, one file per entry so a
    # write stays small instead of rewriting the whole cache.
    def _cache_path(self, key: tuple) -> Path:
        digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:32]
        return Path(self._settings.cache_dir) / f"{digest}.json"

    # Returns a cached result set if it has not yet expired, memory first.
    def _read_cache(self, key: tuple) -> list[Restaurant] | None:
        entry = self._cache.get(key)
        if entry is not None:
            cached_at, restaurants = entry
            if time.time() - cached_at <= self._settings.cache_ttl_seconds:
                return restaurants
            del self._cache[key]

        return self._read_disk_cache(key)

    # Loads one entry from disk, promoting it into memory when still fresh.
    def _read_disk_cache(self, key: tuple) -> list[Restaurant] | None:
        path = self._cache_path(key)
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            # A missing or corrupt cache file is never worth failing over.
            return None

        cached_at = payload.get("cached_at", 0)
        if time.time() - cached_at > self._settings.cache_ttl_seconds:
            path.unlink(missing_ok=True)
            return None

        try:
            restaurants = [
                Restaurant(**record) for record in payload.get("restaurants", [])
            ]
        except TypeError:
            # The Restaurant shape changed since this file was written.
            path.unlink(missing_ok=True)
            return None

        self._cache[key] = (cached_at, restaurants)
        return restaurants

    # Stores a result set in memory and on disk for the next process.
    def _write_cache(self, key: tuple, restaurants: list[Restaurant]) -> None:
        cached_at = time.time()
        self._cache[key] = (cached_at, restaurants)

        path = self._cache_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cached_at": cached_at,
                "restaurants": [asdict(item) for item in restaurants],
            }
            # Write then replace, so a crash mid-write cannot leave a
            # half-written file that later reads as corrupt.
            temp_path = path.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            temp_path.replace(path)
        except OSError:
            # Disk caching is an optimization, never a requirement.
            pass
