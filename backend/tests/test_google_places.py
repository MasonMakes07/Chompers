"""Tests for the Google Places provider and the provider factory.

These never make a network call and never need a real key. The key-handling
assertions matter most: a leaked key is the one failure here that costs money.
"""

import asyncio

import pytest

from backend.config import get_settings
from backend.matching import dietary_rules
from backend.services.google_places_client import (
    MAX_RESULTS_PER_CALL,
    GooglePlacesClient,
)
from backend.services.places_client import (
    OverpassPlacesClient,
    PlacesError,
    create_places_client,
)
from backend.services.query_parser import parse_query

BASE_LAT, BASE_LNG = 32.8801, -117.2340

SAMPLE_PLACE = {
    "id": "ChIJtest",
    "displayName": {"text": "Spice Route"},
    "formattedAddress": "123 Main St, San Diego, CA",
    "location": {"latitude": 32.88, "longitude": -117.23},
    "rating": 4.4,
    "userRatingCount": 512,
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "types": ["indian_restaurant", "restaurant", "food"],
    "primaryType": "indian_restaurant",
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "servesVegetarianFood": True,
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


# A realistic Google place must normalize into a Restaurant correctly.
def test_normalize_google_place():
    restaurant = GooglePlacesClient.normalize_place(SAMPLE_PLACE)

    assert restaurant.name == "Spice Route"
    assert restaurant.place_id == "ChIJtest"
    assert restaurant.rating == 4.4
    assert restaurant.rating_count == 512
    assert restaurant.price_level == 2
    assert "indian_restaurant" in restaurant.types


# Google's vegetarian flag must land in the same diet_tags the scorer reads.
def test_vegetarian_flag_becomes_a_diet_tag():
    restaurant = GooglePlacesClient.normalize_place(SAMPLE_PLACE)

    assert restaurant.diet_tags["vegetarian"] == "yes"


# A false vegetarian flag must be recorded as a negative claim, not dropped.
def test_negative_vegetarian_flag_is_recorded():
    place = dict(SAMPLE_PLACE, servesVegetarianFood=False)

    assert GooglePlacesClient.normalize_place(place).diet_tags["vegetarian"] == "no"


# A sparse payload must not crash normalization.
def test_normalize_sparse_place():
    restaurant = GooglePlacesClient.normalize_place({"id": "x"})

    assert restaurant.name == "Unnamed"
    assert restaurant.rating is None
    assert restaurant.rating_count == 0
    assert restaurant.price_level is None


# Google's own place types must be the ones the rules table already knows.
def test_google_types_are_known_to_the_rules_table():
    restaurant = GooglePlacesClient.normalize_place(SAMPLE_PLACE)

    assert any(
        dietary_rules.is_known_cuisine(place_type)
        for place_type in restaurant.types
    ), "Google types must match the dietary knowledge table vocabulary."


# Every price enum Google documents must map to an integer level.
@pytest.mark.parametrize(
    "enum_value,expected",
    [
        ("PRICE_LEVEL_INEXPENSIVE", 1),
        ("PRICE_LEVEL_MODERATE", 2),
        ("PRICE_LEVEL_EXPENSIVE", 3),
        ("PRICE_LEVEL_VERY_EXPENSIVE", 4),
    ],
)
def test_price_levels_map(enum_value, expected):
    place = dict(SAMPLE_PLACE, priceLevel=enum_value)

    assert GooglePlacesClient.normalize_place(place).price_level == expected


# ---------------------------------------------------------------------------
# Field mask and cost control
# ---------------------------------------------------------------------------


# The default mask must stay on Pro fields, which have the 5,000 free tier.
def test_default_field_mask_excludes_enterprise_fields():
    mask = GooglePlacesClient()._field_mask()

    assert "places.rating" in mask
    assert "servesVegetarianFood" not in mask


# Opting in must add the enterprise fields, at the smaller free allowance.
def test_dietary_flags_widen_the_field_mask():
    mask = GooglePlacesClient(include_dietary_flags=True)._field_mask()

    assert "places.servesVegetarianFood" in mask


# One search must stay one API call, which is what keeps usage free.
def test_one_search_is_one_api_call(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "cache_dir", str(tmp_path / "c"))
    client = GooglePlacesClient()
    calls: list[str] = []

    async def fake_post(url, payload):
        calls.append(url)
        return []

    monkeypatch.setattr(client, "_post", fake_post)
    asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))

    assert len(calls) == 1


# Google caps a single response, so we must never request more than it allows.
def test_result_count_respects_googles_ceiling():
    assert MAX_RESULTS_PER_CALL <= 20


# ---------------------------------------------------------------------------
# Key safety
# ---------------------------------------------------------------------------


# An error body echoing the key back must be stripped before display.
def test_error_message_never_echoes_a_key():
    class FakeResponse:
        status_code = 400

        @staticmethod
        def json():
            return {"error": {"message": "Bad key AIzaSyFAKE123"}}

    message = GooglePlacesClient._describe_error(FakeResponse())

    assert "AIza" not in message


# A rejected key must produce actionable guidance, not a raw status code.
def test_rejected_key_message_is_actionable():
    class FakeResponse:
        status_code = 403

        @staticmethod
        def json():
            return {}

    message = GooglePlacesClient._describe_error(FakeResponse())

    assert "Places API" in message
    assert "AIza" not in message


# Hitting the quota cap must explain that the cap is working as intended.
def test_quota_message_explains_the_cap():
    class FakeResponse:
        status_code = 429

        @staticmethod
        def json():
            return {}

    assert "quota" in GooglePlacesClient._describe_error(FakeResponse()).lower()


# Searching without a key must fail clearly rather than sending an empty one.
def test_missing_key_raises_before_any_request(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_maps_api_key", "")

    with pytest.raises(RuntimeError):
        get_settings().require_api_key()


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


# With a key present, the default provider must be Google.
def test_factory_returns_google_when_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "places_provider", "google")
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")

    assert isinstance(create_places_client(), GooglePlacesClient)


# Asking for OpenStreetMap must be honored even when a key exists.
def test_factory_honors_openstreetmap(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "places_provider", "openstreetmap")
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")

    assert isinstance(create_places_client(), OverpassPlacesClient)


# Google without a key must fall back rather than failing every search.
def test_factory_falls_back_without_a_key(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "places_provider", "google")
    monkeypatch.setattr(settings, "google_maps_api_key", "")

    assert isinstance(create_places_client(), OverpassPlacesClient)


# An unrecognized provider name must not crash startup.
def test_factory_tolerates_unknown_provider(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "places_provider", "nonsense")
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")

    assert isinstance(create_places_client(), GooglePlacesClient)


# Both providers must satisfy the same interface the app depends on.
@pytest.mark.parametrize(
    "client", [GooglePlacesClient(), OverpassPlacesClient()]
)
def test_providers_share_an_interface(client):
    assert hasattr(client, "search_nearby")
    assert hasattr(client, "search_by_intent")
    assert client.provider_name


# An uninterpretable query must fall back to a plain nearby search.
def test_empty_intent_falls_back_to_nearby(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "cache_dir", str(tmp_path / "c"))
    client = GooglePlacesClient()
    urls: list[str] = []

    async def fake_post(url, payload):
        urls.append(url)
        return []

    monkeypatch.setattr(client, "_post", fake_post)
    asyncio.run(
        client.search_by_intent(
            parse_query("!!!"), BASE_LAT, BASE_LNG, 5000
        )
    )

    assert urls and urls[0].endswith("searchNearby")


# A real query must route to Text Search with the user's own phrasing.
def test_intent_search_uses_text_search(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "cache_dir", str(tmp_path / "c"))
    client = GooglePlacesClient()
    sent: list[dict] = []

    async def fake_post(url, payload):
        sent.append({"url": url, "payload": payload})
        return []

    monkeypatch.setattr(client, "_post", fake_post)
    asyncio.run(
        client.search_by_intent(
            parse_query("vegan sushi"), BASE_LAT, BASE_LNG, 5000
        )
    )

    assert sent[0]["url"].endswith("searchText")
    assert sent[0]["payload"]["textQuery"] == "vegan sushi"


# A transport failure must surface as PlacesError, not leak an httpx error.
def test_transport_failure_becomes_places_error(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr(get_settings(), "cache_dir", str(tmp_path / "c"))
    monkeypatch.setattr(get_settings(), "google_maps_api_key", "test-key")
    client = GooglePlacesClient()

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FailingClient())

    with pytest.raises(PlacesError):
        asyncio.run(client.search_nearby(BASE_LAT, BASE_LNG, 5000))
