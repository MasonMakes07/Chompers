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
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
REQUEST_TIMEOUT_SECONDS = 10.0

# Address keys to try for the neighborhood line, most specific first.
LOCALITY_KEYS = ("neighbourhood", "suburb", "quarter", "city_district")

# Address keys to try for the town line, most specific first.
CITY_KEYS = ("city", "town", "village", "municipality", "county")

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

    # Prepares the geocoder with settings and small permanent caches.
    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: dict[str, tuple[float, float, str]] = {}
        self._reverse_cache: dict[tuple[float, float], str] = {}

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

    # Names the place at a coordinate, e.g. "La Jolla, San Diego, CA".
    async def reverse(self, latitude: float, longitude: float) -> str:
        # Rounding to ~100m means small GPS jitter reuses one cache entry.
        cache_key = (round(latitude, 3), round(longitude, 3))
        if cache_key in self._reverse_cache:
            return self._reverse_cache[cache_key]

        params = {
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "format": "jsonv2",
            "zoom": "14",
            "addressdetails": "1",
        }
        body = await self._get(REVERSE_URL, params)
        if not isinstance(body, dict) or "address" not in body:
            raise GeocodingError("Could not name that location.")

        label = self._label_from_address(
            body["address"], body.get("display_name", "")
        )
        self._reverse_cache[cache_key] = label
        return label

    # Builds a short, readable place label from Nominatim's address parts.
    @staticmethod
    def _label_from_address(address: dict, display_name: str) -> str:
        # Prefer neighborhood + city + state; each line is optional.
        locality = next(
            (address[key] for key in LOCALITY_KEYS if address.get(key)), None
        )
        city = next((address[key] for key in CITY_KEYS if address.get(key)), None)

        # "US-CA" -> "CA" gives a compact state without a lookup table.
        state_code = address.get("ISO3166-2-lvl4", "")
        state = (
            state_code.split("-")[-1] if "-" in state_code else address.get("state")
        )

        parts: list[str] = []
        for part in (locality, city, state):
            if part and part not in parts:
                parts.append(part)

        if parts:
            return ", ".join(parts)
        return Geocoder._shorten(display_name) if display_name else "your location"

    # Looks up an address, returning Nominatim's ranked list of matches.
    async def _request(self, address: str) -> list[dict]:
        params = {
            "q": address,
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "0",
        }
        body = await self._get(GEOCODE_URL, params)
        return body if isinstance(body, list) else []

    # Sends one paced, identified request to Nominatim and returns the JSON.
    async def _get(self, url: str, params: dict[str, str]):
        global _last_request_at

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
                        url, params=params, headers=headers
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
            return response.json()
        except ValueError as error:
            raise GeocodingError(
                "The geocoder returned an unreadable reply."
            ) from error

    # Trims Nominatim's very long display names down to something readable.
    @staticmethod
    def _shorten(display_name: str) -> str:
        parts = [part.strip() for part in display_name.split(",") if part.strip()]
        if len(parts) <= 3:
            return display_name
        return ", ".join(parts[:2] + [parts[-1]])
