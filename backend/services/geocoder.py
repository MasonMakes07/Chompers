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
from .bounded_cache import BoundedCache

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
# Google's geocoder, used only as a typo-tolerant fallback when Nominatim
# finds nothing. Requires the "Geocoding API" enabled on the same key.
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
REQUEST_TIMEOUT_SECONDS = 10.0

# Address keys to try for the neighborhood line, most specific first.
LOCALITY_KEYS = ("neighbourhood", "suburb", "quarter", "city_district")

# Address keys to try for the town line, most specific first.
CITY_KEYS = ("city", "town", "village", "municipality", "county")

# Nominatim's usage policy allows at most one request per second, absolute.
_REQUEST_LOCK = asyncio.Lock()
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
_last_request_at = 0.0

# How long a caller will queue for the paced lock before giving up. The lock
# serializes every lookup to one per second, so under load the queue is the
# bottleneck, not the network. Without a ceiling, arrivals outpacing one per
# second grow the waiter list without bound: latency climbs until healthy
# searches time out. Failing fast sheds that load instead of absorbing it.
MAX_LOCK_WAIT_SECONDS = 8.0

# Ceilings for the two permanent caches. A ZIP code's coordinates never change,
# so entries stay valid forever - but "forever" must still be bounded, since
# the key space is attacker-controlled (any typed string, any coordinate).
MAX_FORWARD_CACHE_ENTRIES = 2048
MAX_REVERSE_CACHE_ENTRIES = 2048


# ---------------------------------------------------------------------------


class GeocodingError(RuntimeError):
    """Raised when an address cannot be resolved to coordinates."""


class GeocoderBusyError(GeocodingError):
    """Raised when the paced request queue is too long to join.

    Separate from GeocodingError so the API can answer 503 (come back later)
    rather than 400 (your input was bad) - the query was never the problem.
    """


# ---------------------------------------------------------------------------


class Geocoder:
    """Resolves free-text locations into latitude/longitude pairs."""

    # Prepares the geocoder with settings and small bounded permanent caches.
    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache: BoundedCache[str, tuple[float, float, str]] = BoundedCache(
            MAX_FORWARD_CACHE_ENTRIES
        )
        self._reverse_cache: BoundedCache[tuple[float, float], str] = BoundedCache(
            MAX_REVERSE_CACHE_ENTRIES
        )

    # Resolves a place name or ZIP to (latitude, longitude, display name).
    async def resolve(self, query: str) -> tuple[float, float, str]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            raise GeocodingError("Enter a city or ZIP code.")
        cached = self._cache.get(normalized_query)
        if cached is not None:
            return cached

        body = await self._request(query.strip())
        if not body:
            # Nominatim has weak typo tolerance, so try Google (which handles
            # misspellings) before giving up. Same country restriction applies.
            fallback = await self._google_fallback(query.strip())
            if fallback is not None:
                self._cache.put(normalized_query, fallback)
                return fallback
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

        self._cache.put(normalized_query, resolved)
        return resolved

    # Names the place at a coordinate, e.g. "La Jolla, San Diego, CA".
    async def reverse(self, latitude: float, longitude: float) -> str:
        # Rounding to ~100m means small GPS jitter reuses one cache entry.
        cache_key = (round(latitude, 3), round(longitude, 3))
        cached = self._reverse_cache.get(cache_key)
        if cached is not None:
            return cached

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
        self._reverse_cache.put(cache_key, label)
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
        # Pin the search to the configured countries so an ambiguous or
        # misspelled query cannot resolve to a same-named place abroad.
        if self._settings.geocode_country_codes:
            params["countrycodes"] = self._settings.geocode_country_codes
        body = await self._get(GEOCODE_URL, params)
        return body if isinstance(body, list) else []

    # Resolves via Google's typo-tolerant geocoder, or None when it cannot.
    # Used only when Nominatim finds nothing, and only if a key is present.
    async def _google_fallback(
        self, address: str
    ) -> tuple[float, float, str] | None:
        if not self._settings.has_api_key:
            return None

        params = {"address": address, "key": self._settings.require_api_key()}
        # Google takes a components filter; restrict to the first country code.
        primary = self._settings.geocode_country_codes.split(",")[0].strip()
        if primary:
            params["components"] = f"country:{primary.upper()}"
            params["region"] = primary

        body = await self._get_google(params)
        results = body.get("results") if isinstance(body, dict) else None
        if not results:
            return None

        location = results[0].get("geometry", {}).get("location", {})
        try:
            return (
                float(location["lat"]),
                float(location["lng"]),
                self._shorten(results[0].get("formatted_address", address)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    # Sends one request to Google's geocoder, returning JSON or None. Failures
    # are swallowed so the caller reports the original not-found error, and the
    # key is never placed anywhere but the outbound query string.
    async def _get_google(self, params: dict[str, str]):
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(GOOGLE_GEOCODE_URL, params=params)
        except httpx.RequestError:
            return None

        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    # Sends one paced, identified request to Nominatim and returns the JSON.
    async def _get(self, url: str, params: dict[str, str]):
        global _last_request_at

        headers = {"User-Agent": self._settings.user_agent}

        # Join the paced queue, but only for so long. Waiting forever is what
        # turns a slow upstream into an unbounded backlog of held requests.
        try:
            await asyncio.wait_for(
                _REQUEST_LOCK.acquire(), timeout=MAX_LOCK_WAIT_SECONDS
            )
        except asyncio.TimeoutError as error:
            raise GeocoderBusyError(
                "Too many location lookups are queued. Try again in a moment."
            ) from error

        try:
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
                # The upstream message can carry internal connection detail,
                # so it is deliberately not echoed to the caller.
                raise GeocodingError(
                    "Could not reach the geocoder. Try again shortly."
                ) from error
            finally:
                _last_request_at = time.monotonic()
        finally:
            _REQUEST_LOCK.release()

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
