"""End-to-end wiring: the exact request the React app sends, and the exact
response shape it reads back.

These tests stub the upstream provider but exercise the real route,
middleware, translator, and scorer, so a broken contract between the
frontend and backend fails here rather than in a browser.
"""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.models.restaurant import Restaurant

BASE_LAT, BASE_LNG = 32.8801, -117.2340

# Every field types.ts declares on RestaurantResult.
EXPECTED_RESULT_FIELDS = {
    "place_id",
    "name",
    "address",
    "latitude",
    "longitude",
    "cuisine",
    "rating",
    "rating_count",
    "price_level",
    "open_now",
    "maps_uri",
    "distance_meters",
    "score",
    "group_fit",
    "guest_fits",
    "warnings",
}

# Every field types.ts declares on SearchResponse.
EXPECTED_RESPONSE_FIELDS = {
    "results",
    "searched_location",
    "query",
    "candidates_considered",
    "excluded_count",
    "notes",
}


@pytest.fixture
def client():
    return TestClient(main.app)


# Builds an OSM-shaped restaurant, with no rating or price, as Overpass gives.
def make_place(name: str, place_type: str, offset: float = 0.001) -> Restaurant:
    return Restaurant(
        place_id=f"node/{name}",
        name=name,
        latitude=BASE_LAT + offset,
        longitude=BASE_LNG,
        address="123 Example St",
        primary_type=place_type,
        types=[place_type],
        rating=None,
        rating_count=0,
        price_level=None,
        maps_uri="https://www.openstreetmap.org/node/1",
    )


# Replaces both provider calls so no network is touched during the test.
@pytest.fixture
def stub_provider(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_nearby(latitude, longitude, radius_meters):
        calls["mode"] = "nearby"
        calls["radius"] = radius_meters
        return [
            make_place("Prime Cut", "steak_house"),
            make_place("Spice Route", "indian_restaurant", 0.002),
            make_place("Green Fork", "vegan_restaurant", 0.003),
        ]

    async def fake_by_intent(intent, latitude, longitude, radius_meters):
        calls["mode"] = "intent"
        calls["intent"] = intent
        return [make_place("Sushi Bar", "sushi_restaurant")]

    async def fake_reverse(latitude, longitude):
        return "La Jolla, San Diego, CA"

    monkeypatch.setattr(main.places_client, "search_nearby", fake_nearby)
    monkeypatch.setattr(main.places_client, "search_by_intent", fake_by_intent)
    monkeypatch.setattr(main.geocoder, "reverse", fake_reverse)
    return calls


# ---------------------------------------------------------------------------
# The exact payload the frontend sends
# ---------------------------------------------------------------------------


# The real payload App.tsx builds must be accepted and fully answered.
def test_frontend_payload_round_trips(client, stub_provider):
    response = client.post(
        "/api/search",
        json={
            "guest_count": 4,
            "guests": [
                {"name": "Maya", "restrictions": ["gluten_free", "vegan"]},
                {"name": "Jordan", "restrictions": ["nut_allergy"]},
            ],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 5000,
            "max_price_level": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXPECTED_RESPONSE_FIELDS
    assert body["results"], "A search with real candidates must return results."
    assert set(body["results"][0]) == EXPECTED_RESULT_FIELDS


# Nested guest_fits must carry the exact keys MatchBadge and ResultCard read.
def test_guest_fit_shape_matches_frontend(client, stub_provider):
    response = client.post(
        "/api/search",
        json={
            "guest_count": 2,
            "guests": [{"name": "Maya", "restrictions": ["vegan"]}],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 5000,
        },
    )

    fit = response.json()["results"][0]["guest_fits"][0]
    assert set(fit) == {
        "guest_name",
        "confidence",
        "status",
        "restriction_fits",
    }
    assert fit["status"] in {"good", "limited", "risky"}
    assert set(fit["restriction_fits"][0]) == {
        "restriction",
        "label",
        "confidence",
        "evidence",
        "reason",
        "verified",
    }


# Omitting optional fields entirely, as the quick search does, must work.
def test_minimal_quick_search_payload(client, stub_provider):
    response = client.post(
        "/api/search",
        json={
            "query": "sushi",
            "guest_count": 1,
            "guests": [],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 5000,
        },
    )

    assert response.status_code == 200
    assert stub_provider["mode"] == "intent"
    # The raw word must have been parsed into a structured cuisine, not
    # passed through as an opaque string.
    assert "sushi" in stub_provider["intent"].cuisines
    assert response.json()["query"] == "sushi"


# Without a query the backend must use the plain nearby search instead.
def test_party_search_uses_nearby_mode(client, stub_provider):
    response = client.post(
        "/api/search",
        json={
            "guest_count": 3,
            "guests": [],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 16000,
        },
    )

    assert response.status_code == 200
    assert stub_provider["mode"] == "nearby"
    assert stub_provider["radius"] == 16000


# A coordinate search must report the named place, not a generic phrase.
def test_search_reports_named_location(client, stub_provider):
    response = client.post(
        "/api/search",
        json={
            "guest_count": 1,
            "guests": [],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 5000,
        },
    )

    assert response.json()["searched_location"] == "La Jolla, San Diego, CA"


# Restriction ids the frontend sends must all be accepted by the backend.
def test_all_frontend_restriction_ids_are_valid(client, stub_provider):
    every_restriction = [
        "vegetarian",
        "vegan",
        "gluten_free",
        "dairy_free",
        "nut_allergy",
        "shellfish_allergy",
        "halal",
        "kosher",
    ]

    response = client.post(
        "/api/search",
        json={
            "guest_count": 1,
            "guests": [{"name": "Everything", "restrictions": every_restriction}],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 5000,
        },
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Reverse geocoding endpoint
# ---------------------------------------------------------------------------


# The endpoint the location display calls must return a label.
def test_reverse_geocode_endpoint(client, stub_provider):
    response = client.get(
        f"/api/reverse-geocode?latitude={BASE_LAT}&longitude={BASE_LNG}"
    )

    assert response.status_code == 200
    assert response.json()["label"] == "La Jolla, San Diego, CA"


# Out-of-range coordinates must be rejected, not forwarded upstream.
def test_reverse_geocode_rejects_bad_coordinates(client):
    response = client.get("/api/reverse-geocode?latitude=999&longitude=0")

    assert response.status_code == 422


# Missing parameters must fail validation rather than 500.
def test_reverse_geocode_requires_both_coordinates(client):
    assert client.get("/api/reverse-geocode?latitude=32.8").status_code == 422


# ---------------------------------------------------------------------------
# Middleware must not get in the frontend's way
# ---------------------------------------------------------------------------


# Health must be exempt from rate limiting so it never burns search budget.
def test_health_is_not_rate_limited(client):
    for _ in range(60):
        assert client.get("/api/health").status_code == 200


# The dev-server origin must be allowed through CORS.
def test_vite_origin_is_allowed(client):
    response = client.options(
        "/api/search",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code in (200, 204)
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:5173"
    )
