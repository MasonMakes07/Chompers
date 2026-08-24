"""Geocoder resource-safety tests.

The geocoder is the one place where the app's own rate limits sit ABOVE the
capacity of the thing they protect: Nominatim is paced to one request per
second, while the global limiter allows two per second. Anything that queues
on that lock therefore has to be bounded, or arrivals outpace drain and the
backlog grows until healthy searches time out. These tests pin down the two
ceilings that prevent it, plus the lock release that keeps a failure from
wedging the queue permanently.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import geocoder as geocoder_module
from backend.services.bounded_cache import BoundedCache
from backend.services.geocoder import (
    Geocoder,
    GeocoderBusyError,
    GeocodingError,
)


# ---------------------------------------------------------------------------
# The cache primitive
# ---------------------------------------------------------------------------


# The cache must never hold more than its stated ceiling.
def test_bounded_cache_respects_its_ceiling():
    cache: BoundedCache[int, str] = BoundedCache(10)

    for index in range(1000):
        cache.put(index, f"value-{index}")

    assert len(cache) == 10


# Eviction must drop the least recently USED entry, not the oldest inserted.
def test_bounded_cache_evicts_least_recently_used():
    cache: BoundedCache[str, int] = BoundedCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)

    # Touch "a" so "b" becomes the coldest entry.
    assert cache.get("a") == 1
    cache.put("d", 4)

    assert "b" not in cache
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("d") == 4


# A miss must be reported as None rather than raising.
def test_bounded_cache_miss_returns_none():
    cache: BoundedCache[str, int] = BoundedCache(2)

    assert cache.get("never-stored") is None


# A ceiling of zero or less would make the cache useless; clamp it to one.
def test_bounded_cache_clamps_a_nonsense_ceiling():
    cache: BoundedCache[str, int] = BoundedCache(0)
    cache.put("a", 1)
    cache.put("b", 2)

    assert len(cache) == 1


# ---------------------------------------------------------------------------
# The geocoder's own caches
# ---------------------------------------------------------------------------


# Replaces the upstream call so no test ever reaches Nominatim.
@pytest.fixture
def offline_geocoder(monkeypatch):
    instance = Geocoder()

    async def fake_get(url, params):
        if url == geocoder_module.REVERSE_URL:
            return {
                "address": {"city": "Testville", "state": "Oregon"},
                "display_name": "Testville, Oregon",
            }
        return [{"lat": "45.5", "lon": "-122.6", "display_name": "Testville"}]

    monkeypatch.setattr(instance, "_get", fake_get)
    return instance


# Distinct queries must not grow the forward cache without limit. This is the
# leak: the key is whatever the user typed, so the key space is unbounded.
def test_forward_cache_is_bounded(offline_geocoder):
    async def resolve_many():
        for index in range(geocoder_module.MAX_FORWARD_CACHE_ENTRIES + 500):
            await offline_geocoder.resolve(f"place number {index}")

    asyncio.run(resolve_many())

    assert (
        len(offline_geocoder._cache)
        == geocoder_module.MAX_FORWARD_CACHE_ENTRIES
    )


# The same leak existed on the reverse path, where varying the fourth decimal
# of a coordinate defeats the rounding that is supposed to collapse jitter.
def test_reverse_cache_is_bounded(offline_geocoder):
    async def name_many():
        for index in range(geocoder_module.MAX_REVERSE_CACHE_ENTRIES + 500):
            await offline_geocoder.reverse(45.0 + index / 1000.0, -122.6)

    asyncio.run(name_many())

    assert (
        len(offline_geocoder._reverse_cache)
        == geocoder_module.MAX_REVERSE_CACHE_ENTRIES
    )


# Bounding the cache must not break the caching itself: a repeat lookup still
# has to be served locally rather than paying the one-per-second toll again.
def test_a_repeat_lookup_does_not_hit_upstream(monkeypatch):
    instance = Geocoder()
    calls = {"count": 0}

    async def counting_get(url, params):
        calls["count"] += 1
        return [{"lat": "45.5", "lon": "-122.6", "display_name": "Testville"}]

    monkeypatch.setattr(instance, "_get", counting_get)

    async def resolve_twice():
        first = await instance.resolve("Portland, OR")
        second = await instance.resolve("  portland, or  ")
        return first, second

    first, second = asyncio.run(resolve_twice())

    assert first == second
    assert calls["count"] == 1


# ---------------------------------------------------------------------------
# The paced queue
# ---------------------------------------------------------------------------


# A caller must give up rather than queue forever behind a stalled lock.
def test_a_long_queue_gives_up_instead_of_waiting_forever(monkeypatch):
    monkeypatch.setattr(geocoder_module, "MAX_LOCK_WAIT_SECONDS", 0.05)
    instance = Geocoder()

    async def blocked_lookup():
        # Hold the pacing lock so the lookup can never acquire it.
        await geocoder_module._REQUEST_LOCK.acquire()
        try:
            with pytest.raises(GeocoderBusyError):
                await instance.resolve("Portland, OR")
        finally:
            geocoder_module._REQUEST_LOCK.release()

    asyncio.run(blocked_lookup())


# A failed request must still release the lock. The pacing lock is acquired
# manually rather than with `async with`, so a missing release here would wedge
# every later lookup behind a lock nobody owns - a permanent outage from one
# transient network blip.
def test_a_failed_request_releases_the_lock(monkeypatch):
    instance = Geocoder()

    class FailingClient:
        # Accepts whatever arguments the real client takes.
        def __init__(self, *args, **kwargs) -> None:
            pass

        # Enters the async context manager, returning itself.
        async def __aenter__(self):
            return self

        # Leaves the context manager without suppressing anything.
        async def __aexit__(self, *args) -> bool:
            return False

        # Fails the way an unreachable host does.
        async def get(self, *args, **kwargs):
            raise httpx.RequestError("connection refused to 10.0.0.1:8080")

    monkeypatch.setattr(geocoder_module.httpx, "AsyncClient", FailingClient)

    async def failing_lookup():
        with pytest.raises(GeocodingError) as caught:
            await instance.resolve("Portland, OR")
        return str(caught.value)

    message = asyncio.run(failing_lookup())

    assert not geocoder_module._REQUEST_LOCK.locked(), (
        "the pacing lock was not released after a failed request"
    )
    # The upstream detail must not be echoed to the caller.
    assert "10.0.0.1" not in message
    assert "connection refused" not in message


# ---------------------------------------------------------------------------
# How shedding load surfaces to the browser
# ---------------------------------------------------------------------------


# Being too busy is a 503 with a Retry-After, never a 502 or a 400. Those
# would tell the frontend the upstream broke, or that the user's input was
# wrong - and neither is true when we simply could not get to the request.
def test_a_busy_geocoder_answers_503(monkeypatch):
    async def busy_reverse(latitude, longitude):
        raise GeocoderBusyError("Too many location lookups are queued.")

    monkeypatch.setattr(main.geocoder, "reverse", busy_reverse)

    with TestClient(main.app) as client:
        response = client.get("/api/reverse-geocode?latitude=45.5&longitude=-122.6")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"


# A busy reverse lookup during a coordinate search is cosmetic - the search
# itself must still succeed, with a generic location name.
def test_a_busy_reverse_lookup_does_not_fail_a_search(monkeypatch):
    async def busy_reverse(latitude, longitude):
        raise GeocoderBusyError("Too many location lookups are queued.")

    async def no_places(latitude, longitude, radius_meters):
        return []

    monkeypatch.setattr(main.geocoder, "reverse", busy_reverse)
    monkeypatch.setattr(main.places_client, "search_nearby", no_places)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/search",
            json={
                "guest_count": 2,
                "guests": [],
                "latitude": 45.5,
                "longitude": -122.6,
                "radius_meters": 5000,
            },
        )

    assert response.status_code == 200
    assert response.json()["searched_location"] == "your current location"
