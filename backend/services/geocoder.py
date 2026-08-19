"""Geocoding: turns a typed city or ZIP into coordinates, via Nominatim.

Only used when the browser refuses or the user overrides geolocation, so most
searches never geocode at all.

Nominatim is free and keyless, but its usage policy is strict: an identifying
User-Agent is required and requests are capped at one per second. Both are
enforced here rather than left to chance, and results are cached permanently
for the process since a ZIP code's coordinates never change.
"""

import asyncio
import time

import httpx

from ..config import get_settings

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
REQUEST_TIMEOUT_SECONDS = 10.0

# Nominatim's usage policy allows at most one request per second, absolute.
_REQUEST_LOCK = asyncio.Lock()
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
_last_request_at = 0.0


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

    # Resolves a place name or ZIP to (latitude, longitude, display name).
    async def resolve(self, query: str) -> tuple[float, float, str]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            raise GeocodingError("Enter a city or ZIP code.")
        if normalized_query in self._cache:
            return self._cache[normalized_query]

        body = await self._request(query.strip())
        if not body:
            raise GeocodingError(
                f"Could not find '{query}'. Try a ZIP code or 'City, State'."
            )

        best_result = body[0]
        try:
            resolved = (
                float(best_result["lat"]),
                float(best_result["lon"]),
                self._shorten(best_result.get("display_name", query)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise GeocodingError("The geocoder returned an unusable result.") from error

        self._cache[normalized_query] = resolved
        return resolved

    # Sends one paced, identified request to Nominatim and returns the JSON.
    async def _request(self, address: str) -> list[dict]:
        global _last_request_at

        params = {
            "q": address,
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "0",
        }
        headers = {"User-Agent": self._settings.user_agent}

        async with _REQUEST_LOCK:
            elapsed = time.monotonic() - _last_request_at
            if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
                await asyncio.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)

            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT_SECONDS
                ) as client:
                    response = await client.get(
                        GEOCODE_URL, params=params, headers=headers
                    )
            except httpx.RequestError as error:
                raise GeocodingError(
                    f"Could not reach the geocoder: {error}"
                ) from error
            finally:
                _last_request_at = time.monotonic()

        if response.status_code == 429:
            raise GeocodingError(
                "The geocoder is rate limiting us. Wait a moment and retry."
            )
        if response.status_code != 200:
            raise GeocodingError(f"Geocoding failed ({response.status_code}).")

        try:
            body = response.json()
        except ValueError as error:
            raise GeocodingError("The geocoder returned an unreadable reply.") from error

        return body if isinstance(body, list) else []

    # Trims Nominatim's very long display names down to something readable.
    @staticmethod
    def _shorten(display_name: str) -> str:
        parts = [part.strip() for part in display_name.split(",") if part.strip()]
        if len(parts) <= 3:
            return display_name
        return ", ".join(parts[:2] + [parts[-1]])
