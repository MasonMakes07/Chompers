"""End-to-end API tests. No network calls and no API key required."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app

BASE_LAT, BASE_LNG = 32.8801, -117.2340


# Provides a test client sharing the real middleware stack.
@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


# The health endpoint must report status without leaking any secret.
def test_health_reports_status_not_secrets(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] in ("google", "openstreetmap")
    assert isinstance(body["api_key_configured"], bool)
    # The health check may report THAT a key exists, never any part of it.
    assert "GOOGLE_MAPS_API_KEY" not in response.text
    assert "AIza" not in response.text


# Security headers must be present on every response.
def test_security_headers_are_applied(client):
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


# A malformed body must be rejected by validation, never reaching the provider.
def test_invalid_search_is_rejected(client):
    response = client.post("/api/search", json={"guest_count": 99})

    assert response.status_code == 422


# A search with no location at all must be rejected with a clear error.
def test_missing_location_is_rejected(client):
    response = client.post("/api/search", json={"guest_count": 4})

    assert response.status_code == 422


# Hostile guest names must be rejected at the schema boundary.
def test_hostile_input_is_rejected(client):
    response = client.post(
        "/api/search",
        json={
            "guest_count": 2,
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "guests": [{"name": "<script>alert(1)</script>", "restrictions": []}],
        },
    )

    assert response.status_code == 422


# Searching must not require any API key now that the provider is OSM.
def test_search_does_not_require_an_api_key(client, monkeypatch):
    from backend import main

    monkeypatch.setattr(main.settings, "google_maps_api_key", "")

    async def fake_search_nearby(latitude, longitude, radius_meters):
        return []

    monkeypatch.setattr(main.places_client, "search_nearby", fake_search_nearby)

    response = client.post(
        "/api/search",
        json={"guest_count": 2, "latitude": BASE_LAT, "longitude": BASE_LNG},
    )

    assert response.status_code == 200


# The rate limiter must eventually reject a flood of upstream-hitting calls.
def test_rate_limit_blocks_a_flood(client):
    # Invalid coordinates still count: the limiter runs before routing, so a
    # flood cannot dodge the cap by being malformed.
    statuses = [
        client.get("/api/reverse-geocode?latitude=999&longitude=0").status_code
        for _ in range(60)
    ]

    assert 429 in statuses, "A flood must be capped before it reaches upstream."


# Health must stay exempt, so monitoring never consumes a user's budget.
def test_health_is_exempt_from_rate_limiting(client):
    statuses = [client.get("/api/health").status_code for _ in range(60)]

    assert set(statuses) == {200}
