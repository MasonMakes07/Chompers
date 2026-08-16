"""Geocoding: turns a typed city or ZIP into coordinates.

Only used when the browser refuses or the user overrides geolocation, so most
searches never spend a Geocoding call at all.
"""

import httpx

from ..config import get_settings

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
REQUEST_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------


class GeocodingError(RuntimeError):
    """Raised when an address cannot be resolved to coordinates."""


# ---------------------------------------------------------------------------


class Geocoder:
    """Resolves free-text locations into latitude/longitude pairs."""

    # Prepares the geocoder with settings and a small permanent cache.
    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: dict[str, tuple[float, float, str]] = {}

    # Resolves a place name or ZIP to (latitude, longitude, formatted name).
    async def resolve(self, query: str) -> tuple[float, float, str]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            raise GeocodingError("Enter a city or ZIP code.")
        if normalized_query in self._cache:
            return self._cache[normalized_query]

        params = {
            "address": query.strip(),
            "key": self._settings.require_api_key(),
        }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(GEOCODE_URL, params=params)
        except httpx.RequestError as error:
            raise GeocodingError(f"Could not reach the geocoder: {error}") from error

        if response.status_code != 200:
            raise GeocodingError(f"Geocoding failed ({response.status_code}).")

        body = response.json()
        status = body.get("status")
        if status == "ZERO_RESULTS" or not body.get("results"):
            raise GeocodingError(f"Could not find '{query}'. Try a ZIP code.")
        if status != "OK":
            raise GeocodingError(f"Geocoding failed ({status}).")

        best_result = body["results"][0]
        location = best_result["geometry"]["location"]
        resolved = (
            float(location["lat"]),
            float(location["lng"]),
            best_result.get("formatted_address", query),
        )
        self._cache[normalized_query] = resolved
        return resolved
