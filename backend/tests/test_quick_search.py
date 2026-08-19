"""Tests for the free-text quick search path."""

import pytest
from pydantic import ValidationError

from backend import translator
from backend.schemas import SearchRequest
from backend.services.places_client import OverpassPlacesClient

BASE_LAT, BASE_LNG = 32.8801, -117.2340


# Builds a minimal valid search request with an optional query.
def make_request(query: str | None) -> SearchRequest:
    return SearchRequest(
        query=query, latitude=BASE_LAT, longitude=BASE_LNG, guest_count=2
    )


# ---------------------------------------------------------------------------
# Query validation
# ---------------------------------------------------------------------------


# A quick search must work without any guests being described.
def test_query_search_needs_no_guests():
    request = SearchRequest(query="sushi", latitude=BASE_LAT, longitude=BASE_LNG)

    assert request.query == "sushi"
    assert request.guest_count == 1
    assert request.guests == []


# Omitting the query entirely must remain valid, keeping Nearby Search working.
def test_query_is_optional():
    assert make_request(None).query is None


# Blank or whitespace-only queries must normalize to None, not an empty search.
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_query_becomes_none(blank):
    assert make_request(blank).query is None


# Internal whitespace must be collapsed so caching stays effective.
def test_query_whitespace_is_collapsed():
    assert make_request("  cheap    tacos  ").query == "cheap tacos"


# Code-like queries must be rejected, exactly like other free-text fields.
@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        "sushi'; DROP TABLE places --",
        "${GOOGLE_MAPS_API_KEY}",
        "javascript:fetch('/')",
    ],
)
def test_code_like_query_is_rejected(hostile):
    with pytest.raises(ValidationError):
        make_request(hostile)


# Overlong queries must be rejected before they reach Google.
def test_overlong_query_is_rejected():
    with pytest.raises(ValidationError):
        make_request("a" * 200)


# Ordinary queries with punctuation must survive sanitization.
def test_normal_queries_are_accepted():
    assert make_request("Joe's late-night pizza").query == "Joe's late-night pizza"


# A quick search still requires a location, same as any other search.
def test_query_alone_is_not_enough():
    with pytest.raises(ValidationError):
        SearchRequest(query="sushi")


# ---------------------------------------------------------------------------
# Cache keying
# ---------------------------------------------------------------------------


# Different queries at one location must not collide in the cache.
def test_cache_key_separates_queries():
    client = OverpassPlacesClient()
    nearby_key = client._cache_key(BASE_LAT, BASE_LNG, 5000)
    sushi_key = client._cache_key(BASE_LAT, BASE_LNG, 5000, "sushi")
    tacos_key = client._cache_key(BASE_LAT, BASE_LNG, 5000, "tacos")

    assert len({nearby_key, sushi_key, tacos_key}) == 3


# Queries differing only by case or padding must share one cache entry.
def test_cache_key_normalizes_query():
    client = OverpassPlacesClient()

    assert client._cache_key(
        BASE_LAT, BASE_LNG, 5000, "  SUSHI "
    ) == client._cache_key(BASE_LAT, BASE_LNG, 5000, "sushi")


# Two providers must never share a cache entry for the same coordinates.
def test_cache_key_separates_providers():
    from backend.services.places_client import GooglePlacesClient

    overpass_key = OverpassPlacesClient()._cache_key(BASE_LAT, BASE_LNG, 5000)
    google_key = GooglePlacesClient()._cache_key(BASE_LAT, BASE_LNG, 5000)

    assert overpass_key != google_key


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


# The response must echo the query so the results page can display it.
def test_response_echoes_query():
    response = translator.build_search_response([], "92093", 0, 0, query="ramen")

    assert response.query == "ramen"


# An empty keyword search must explain itself in terms of the query.
def test_empty_query_results_mention_the_query():
    response = translator.build_search_response([], "92093", 0, 0, query="ramen")

    assert any("ramen" in note for note in response.notes)


# An empty search with no query must fall back to the radius suggestion.
def test_empty_results_without_query_suggest_radius():
    response = translator.build_search_response([], "92093", 0, 0)

    assert response.query is None
    assert any("widening" in note for note in response.notes)
