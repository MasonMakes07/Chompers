"""Google Places API (New) client.

One user search costs exactly ONE Nearby Search call. The 20 places returned
are ranked locally by the scorer, which is what keeps usage inside the free
tier. Responses are cached briefly by rounded location to spend even less.
"""

import time
from typing import Any

import httpx

from ..config import get_settings
from ..models.restaurant import Restaurant

NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Pro-tier fields. Nearby Search Pro allows 5,000 free calls per month.
BASE_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.types",
        "places.primaryType",
        "places.googleMapsUri",
    )
)

# Enterprise-tier fields. Requesting these drops the free allowance from
# 5,000 to 1,000 calls per month, so they are opt-in via INCLUDE_DIETARY_FLAGS.
ENTERPRISE_FIELDS = ",".join(
    ("places.servesVegetarianFood", "places.currentOpeningHours.openNow")
)

# Google returns price as an enum string; map it to a 0-4 integer.
PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

MAX_RESULTS_PER_CALL = 20
REQUEST_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------


class PlacesError(RuntimeError):
    """Raised when the Places API cannot be reached or rejects the request."""


# ---------------------------------------------------------------------------


class PlacesClient:
    """Fetches nearby restaurants and normalizes them into Restaurant models."""

    # Prepares the client with settings and an empty response cache.
    def __init__(self, include_dietary_flags: bool = False) -> None:
        self._settings = get_settings()
        self._include_dietary_flags = include_dietary_flags
        self._cache: dict[tuple, tuple[float, list[Restaurant]]] = {}

    # Builds the field mask, widening it only if enterprise fields are on.
    def _field_mask(self) -> str:
        if self._include_dietary_flags:
            return f"{BASE_FIELD_MASK},{ENTERPRISE_FIELDS}"
        return BASE_FIELD_MASK

    # Rounds coordinates so nearby searches share one cache entry.
    @staticmethod
    def _cache_key(
        latitude: float,
        longitude: float,
        radius_meters: int,
        query: str | None = None,
    ) -> tuple:
        normalized_query = query.strip().lower() if query else None
        return (
            round(latitude, 3),
            round(longitude, 3),
            radius_meters,
            normalized_query,
        )

    # Returns a cached result set if it has not yet expired.
    def _read_cache(self, key: tuple) -> list[Restaurant] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        cached_at, restaurants = entry
        if time.monotonic() - cached_at > self._settings.cache_ttl_seconds:
            del self._cache[key]
            return None
        return restaurants

    # Fetches restaurants near a point, using the cache when possible.
    async def search_nearby(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        cache_key = self._cache_key(latitude, longitude, radius_meters)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        payload = {
            "includedTypes": ["restaurant"],
            "maxResultCount": MAX_RESULTS_PER_CALL,
            "rankPreference": "POPULARITY",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": float(radius_meters),
                }
            },
        }
        return await self._post_search(NEARBY_SEARCH_URL, payload, cache_key)

    # Fetches restaurants matching a free-text query near a point.
    async def search_text(
        self, query: str, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        cache_key = self._cache_key(latitude, longitude, radius_meters, query)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        # locationBias, not locationRestriction: a strong text match slightly
        # outside the radius is still worth showing on a keyword search.
        payload = {
            "textQuery": query,
            "includedType": "restaurant",
            "maxResultCount": MAX_RESULTS_PER_CALL,
            "locationBias": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": float(radius_meters),
                }
            },
        }
        return await self._post_search(TEXT_SEARCH_URL, payload, cache_key)

    # Posts one Places request, normalizes the results, and caches them.
    async def _post_search(
        self, url: str, payload: dict[str, Any], cache_key: tuple
    ) -> list[Restaurant]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._settings.require_api_key(),
            "X-Goog-FieldMask": self._field_mask(),
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.RequestError as error:
            raise PlacesError(f"Could not reach Google Places: {error}") from error

        if response.status_code != 200:
            raise PlacesError(self._describe_error(response))

        restaurants = [
            self.normalize_place(place)
            for place in response.json().get("places", [])
        ]
        self._cache[cache_key] = (time.monotonic(), restaurants)
        return restaurants

    # Turns a Google error response into a message safe to show a user.
    @staticmethod
    def _describe_error(response: httpx.Response) -> str:
        if response.status_code == 403:
            return (
                "Google rejected the API key. Check that Places API (New) is "
                "enabled and the key restrictions allow it."
            )
        if response.status_code == 429:
            return (
                "Daily quota reached. This is the safety cap doing its job - "
                "try again tomorrow or raise the cap in Google Cloud Console."
            )
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        return f"Places API error {response.status_code}. {detail}".strip()

    # Converts one raw Google place object into a normalized Restaurant.
    @staticmethod
    def normalize_place(place: dict[str, Any]) -> Restaurant:
        location = place.get("location") or {}
        opening_hours = place.get("currentOpeningHours") or {}
        return Restaurant(
            place_id=place.get("id", ""),
            name=(place.get("displayName") or {}).get("text", "Unnamed"),
            latitude=float(location.get("latitude", 0.0)),
            longitude=float(location.get("longitude", 0.0)),
            address=place.get("formattedAddress", ""),
            primary_type=place.get("primaryType", ""),
            types=list(place.get("types") or []),
            rating=place.get("rating"),
            rating_count=int(place.get("userRatingCount") or 0),
            price_level=PRICE_LEVEL_MAP.get(place.get("priceLevel", "")),
            open_now=opening_hours.get("openNow"),
            serves_vegetarian=place.get("servesVegetarianFood"),
            maps_uri=place.get("googleMapsUri", ""),
            summary=(place.get("editorialSummary") or {}).get("text", ""),
        )
