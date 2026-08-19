"""Rate limiting tests.

Each limit exists to stop a different attack, so each is tested for the
specific thing it prevents. The burst limit matters most: without it a whole
minute's allowance can land in one second, which is exactly the flood a
per-minute counter looks like it prevents but does not.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend import main, middleware
from backend.config import get_settings
from backend.middleware import RateLimitMiddleware

BASE_LAT, BASE_LNG = 32.8801, -117.2340


@pytest.fixture
def client():
    return TestClient(main.app)


# Replaces the provider so no test ever reaches a real API.
@pytest.fixture(autouse=True)
def stub_provider(monkeypatch):
    async def fake_nearby(latitude, longitude, radius_meters):
        return []

    async def fake_by_intent(intent, latitude, longitude, radius_meters):
        return []

    async def fake_reverse(latitude, longitude):
        return "Somewhere, CA"

    monkeypatch.setattr(main.places_client, "search_nearby", fake_nearby)
    monkeypatch.setattr(main.places_client, "search_by_intent", fake_by_intent)
    monkeypatch.setattr(main.geocoder, "reverse", fake_reverse)


# Makes each request appear to come from its own address.
@pytest.fixture
def rotating_ips(monkeypatch):
    counter = {"n": 0}

    def fake_key(request):
        counter["n"] += 1
        return f"10.0.0.{counter['n']}"

    monkeypatch.setattr(RateLimitMiddleware, "_client_key", staticmethod(fake_key))
    return counter


# Posts one valid search.
def do_search(client: TestClient):
    return client.post(
        "/api/search",
        json={
            "guest_count": 2,
            "guests": [],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "radius_meters": 5000,
        },
    )


# ---------------------------------------------------------------------------
# Burst - the limit that actually stops "all at once"
# ---------------------------------------------------------------------------


# A rapid burst must be cut off well before the per-minute allowance.
def test_burst_is_blocked_immediately(client):
    statuses = [do_search(client).status_code for _ in range(40)]

    assert 429 in statuses
    allowed = statuses.count(200)
    assert allowed <= get_settings().rate_limit_burst, (
        "A burst must be capped by the short window, not the minute window."
    )


# The burst cap must bite before the per-minute cap is anywhere near reached.
def test_burst_cap_is_lower_than_the_minute_cap():
    settings = get_settings()

    assert settings.rate_limit_burst < settings.rate_limit_per_minute


# Once the burst window passes, the client must be allowed to continue.
def test_burst_window_recovers(client, monkeypatch):
    for _ in range(40):
        do_search(client)

    # Jump past the burst window without actually sleeping.
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        middleware.time,
        "monotonic",
        lambda: real_monotonic() + middleware.BURST_WINDOW_SECONDS + 1,
    )

    assert do_search(client).status_code == 200


# ---------------------------------------------------------------------------
# Sustained per-client limit
# ---------------------------------------------------------------------------


# Dripping requests slowly must still hit the per-minute ceiling.
def test_sustained_drip_is_capped(client, monkeypatch):
    settings = get_settings()
    real_monotonic = time.monotonic
    offset = {"seconds": 0.0}

    # Advance past the burst window between each request, so only the
    # per-minute limit can be what stops this.
    monkeypatch.setattr(
        middleware.time, "monotonic", lambda: real_monotonic() + offset["seconds"]
    )

    # Spacing must stay inside the 60s window or entries age out and the
    # per-minute limit can never accumulate enough hits to trigger.
    spacing = middleware.BURST_WINDOW_SECONDS / settings.rate_limit_burst + 0.05

    statuses = []
    for _ in range(settings.rate_limit_per_minute + 5):
        offset["seconds"] += spacing
        statuses.append(do_search(client).status_code)

    assert 429 in statuses
    assert statuses.count(200) <= settings.rate_limit_per_minute


# ---------------------------------------------------------------------------
# Global limit - what a per-IP limit alone cannot do
# ---------------------------------------------------------------------------


# Many distinct addresses must not together exceed the global ceiling.
def test_many_ips_cannot_drain_the_quota(client, rotating_ips):
    settings = get_settings()
    limit = settings.global_rate_limit_per_minute

    statuses = [do_search(client).status_code for _ in range(limit + 10)]

    assert 429 in statuses, "A distributed flood must hit the global cap."
    assert statuses.count(200) <= limit


# Each address must still get its own allowance below the global ceiling.
def test_separate_ips_have_separate_budgets(client, rotating_ips):
    burst = get_settings().rate_limit_burst

    statuses = [do_search(client).status_code for _ in range(burst + 3)]

    assert statuses.count(200) == burst + 3, (
        "Distinct clients must not share one client's burst budget."
    )


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------


# A throttled response must tell the client how long to wait.
def test_throttled_response_sets_retry_after(client):
    statuses = [do_search(client) for _ in range(40)]
    throttled = [item for item in statuses if item.status_code == 429]

    assert throttled
    assert int(throttled[0].headers["Retry-After"]) > 0


# A throttled response must explain itself, not just return a bare code.
def test_throttled_response_explains_itself(client):
    responses = [do_search(client) for _ in range(40)]
    throttled = next(item for item in responses if item.status_code == 429)

    assert "detail" in throttled.json()
    assert throttled.json()["detail"]


# Health must stay exempt so monitoring never consumes a search budget.
def test_health_is_never_throttled(client):
    statuses = [client.get("/api/health").status_code for _ in range(100)]

    assert set(statuses) == {200}


# Rejected requests must never reach the provider.
def test_throttled_requests_do_not_reach_the_provider(client, monkeypatch):
    calls: list[int] = []

    async def counting_nearby(latitude, longitude, radius_meters):
        calls.append(1)
        return []

    monkeypatch.setattr(main.places_client, "search_nearby", counting_nearby)

    for _ in range(40):
        do_search(client)

    assert len(calls) <= get_settings().rate_limit_burst, (
        "Throttling must happen before any upstream call is made."
    )


# ---------------------------------------------------------------------------
# Memory safety
# ---------------------------------------------------------------------------


# The client table must stay bounded however many addresses are seen.
def test_client_table_is_bounded(client, rotating_ips, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_tracked_clients", 100)

    for _ in range(300):
        do_search(client)

    assert len(middleware._HITS) <= 100, (
        "An unbounded table lets cycling addresses exhaust memory."
    )


# Validation failures must still count, so malformed floods are capped too.
def test_invalid_requests_still_consume_budget(client):
    statuses = [
        client.post("/api/search", json={"guest_count": 999}).status_code
        for _ in range(40)
    ]

    assert 429 in statuses, "A flood must not dodge the cap by being invalid."


# ---------------------------------------------------------------------------
# Provider concurrency
# ---------------------------------------------------------------------------


# Concurrent upstream calls must be capped even when all are permitted.
def test_google_client_caps_concurrency(monkeypatch, tmp_path):
    import httpx

    from backend.services import google_places_client
    from backend.services.google_places_client import GooglePlacesClient

    settings = get_settings()
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "google_maps_api_key", "test-key")

    in_flight = {"now": 0, "peak": 0}

    class TrackingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            in_flight["now"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            await asyncio.sleep(0.02)
            in_flight["now"] -= 1

            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {"places": []}

            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: TrackingClient())

    async def twelve_distinct_searches():
        client = GooglePlacesClient()
        await asyncio.gather(
            *(
                client.search_nearby(BASE_LAT + index / 100, BASE_LNG, 5000)
                for index in range(12)
            )
        )

    asyncio.run(twelve_distinct_searches())

    assert in_flight["peak"] <= google_places_client.MAX_CONCURRENT_QUERIES, (
        "Permitted requests must still queue rather than stampede upstream."
    )
