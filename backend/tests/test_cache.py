"""Tests for the on-disk Overpass response cache.

A cache hit measured at 0.019ms against a 3-18 second fetch, so the only
thing that matters here is that hits actually happen - including across a
process restart, which is what the in-memory-only cache could never do.
"""

import asyncio
import json
import time

import pytest

from backend.config import get_settings
from backend.services.places_client import OverpassPlacesClient

BASE_LAT, BASE_LNG = 32.8801, -117.2340

SAMPLE_ELEMENTS = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": BASE_LAT,
            "lon": BASE_LNG,
            "tags": {
                "name": "Green Fork",
                "amenity": "restaurant",
                "cuisine": "vegan",
                "diet:vegan": "only",
            },
        },
        {
            "type": "node",
            "id": 2,
            "lat": BASE_LAT + 0.001,
            "lon": BASE_LNG,
            "tags": {"name": "Prime Cut", "amenity": "restaurant"},
        },
    ]
}


# Points the cache at a throwaway directory for each test.
@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path / "places"))
    monkeypatch.setattr(settings, "cache_ttl_seconds", 86_400)
    return tmp_path / "places"


# Builds a client whose upstream calls are counted rather than performed.
def make_client(monkeypatch, calls: list[str]):
    client = OverpassPlacesClient()

    async def fake_post(overpass_query: str):
        calls.append(overpass_query)
        return SAMPLE_ELEMENTS

    monkeypatch.setattr(client, "_post_overpass", fake_post)
    return client


# ---------------------------------------------------------------------------


# A repeated search must be served from memory without touching upstream.
def test_second_search_hits_memory_cache(cache_dir, monkeypatch):
    calls: list[str] = []
    client = make_client(monkeypatch, calls)

    async def search_twice():
        await client.search_nearby(BASE_LAT, BASE_LNG, 5000)
        await client.search_nearby(BASE_LAT, BASE_LNG, 5000)

    asyncio.run(search_twice())

    assert len(calls) == 1


# A search must leave a cache file behind for the next process.
def test_search_writes_a_cache_file(cache_dir, monkeypatch):
    client = make_client(monkeypatch, [])
    asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["restaurants"][0]["name"] == "Green Fork"


# The headline behavior: a brand new process must reuse the cached results.
def test_cache_survives_a_restart(cache_dir, monkeypatch):
    first_calls: list[str] = []
    first_client = make_client(monkeypatch, first_calls)
    asyncio.run(first_client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    # A second client with empty memory stands in for a restarted server.
    second_calls: list[str] = []
    second_client = make_client(monkeypatch, second_calls)
    restaurants = asyncio.run(second_client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert second_calls == [], "A restart must not refetch what is on disk."
    assert [item.name for item in restaurants] == ["Green Fork", "Prime Cut"]


# Restored entries must keep the structured diet tags ranking depends on.
def test_restored_entry_keeps_diet_tags(cache_dir, monkeypatch):
    asyncio.run(make_client(monkeypatch, []).search_nearby(BASE_LAT, BASE_LNG, 5000))

    restored = asyncio.run(
        make_client(monkeypatch, []).search_nearby(BASE_LAT, BASE_LNG, 5000)
    )

    assert restored[0].diet_tags["vegan"] == "only"
    assert "vegan_restaurant" in restored[0].types


# An expired entry must be refetched, not served stale.
def test_expired_disk_entry_is_refetched(cache_dir, monkeypatch):
    client = make_client(monkeypatch, [])
    asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    # Backdate the file well past any sane TTL.
    cache_file = next(cache_dir.glob("*.json"))
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["cached_at"] = time.time() - 10_000_000
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    calls: list[str] = []
    fresh_client = make_client(monkeypatch, calls)
    asyncio.run(fresh_client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert len(calls) == 1, "A stale entry must trigger a refetch."


# A corrupt cache file must be ignored, never crash a search.
def test_corrupt_cache_file_is_ignored(cache_dir, monkeypatch):
    client = make_client(monkeypatch, [])
    asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    next(cache_dir.glob("*.json")).write_text("{not json", encoding="utf-8")

    calls: list[str] = []
    fresh_client = make_client(monkeypatch, calls)
    restaurants = asyncio.run(fresh_client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert len(calls) == 1
    assert restaurants


# A cache file written by an older Restaurant shape must be discarded.
def test_incompatible_cache_file_is_discarded(cache_dir, monkeypatch):
    client = make_client(monkeypatch, [])
    asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    cache_file = next(cache_dir.glob("*.json"))
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["restaurants"][0]["field_that_no_longer_exists"] = True
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    calls: list[str] = []
    fresh_client = make_client(monkeypatch, calls)
    asyncio.run(fresh_client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert len(calls) == 1, "An unreadable shape must refetch, not raise."


# Different searches must not collide on one cache file.
def test_distinct_searches_use_distinct_files(cache_dir, monkeypatch):
    client = make_client(monkeypatch, [])

    async def two_searches():
        await client.search_nearby(BASE_LAT, BASE_LNG, 5000)
        await client.search_nearby(BASE_LAT, BASE_LNG, 16000)

    asyncio.run(two_searches())

    assert len(list(cache_dir.glob("*.json"))) == 2


# An unwritable cache directory must degrade quietly, not fail the search.
def test_unwritable_cache_dir_does_not_break_search(monkeypatch, tmp_path):
    settings = get_settings()
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(settings, "cache_dir", str(blocker / "places"))

    calls: list[str] = []
    client = make_client(monkeypatch, calls)
    restaurants = asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert restaurants, "Search must succeed even when caching cannot."


# No temporary files may be left behind by a successful write.
def test_no_temp_files_remain(cache_dir, monkeypatch):
    asyncio.run(make_client(monkeypatch, []).search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert list(cache_dir.glob("*.tmp")) == []
