"""Restaurant data from OpenStreetMap via the Overpass API.

No API key, no billing account, no quota to blow through. Overpass is a
volunteer-run public service, so the cost here is politeness rather than
money: results are cached, queries are bounded, and a User-Agent identifies
the app as the usage policy requires.

The class and error names stay provider-neutral on purpose. Everything
downstream - the scorer, the translator, the frontend - only ever sees
`Restaurant`, so swapping providers again would touch this file alone.
"""

import asyncio
import re
import time
from typing import Any

import httpx

from ..config import get_settings
from ..models.restaurant import Restaurant
from . import osm_tags

# Amenity values worth returning for a restaurant search.
FOOD_AMENITIES = "restaurant|cafe|fast_food|pub|bar|ice_cream|food_court"

MAX_RESULTS_PER_CALL = 60
REQUEST_TIMEOUT_SECONDS = 30.0
OVERPASS_QUERY_TIMEOUT_SECONDS = 25

# Overpass is a shared volunteer service; never issue concurrent queries.
_REQUEST_LOCK = asyncio.Lock()
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
_last_request_at = 0.0


# ---------------------------------------------------------------------------


class PlacesError(RuntimeError):
    """Raised when the places provider cannot be reached or rejects a query."""


# ---------------------------------------------------------------------------


class PlacesClient:
    """Fetches nearby restaurants from Overpass and normalizes them."""

    # Prepares the client with settings and an empty response cache.
    def __init__(self, include_dietary_flags: bool = True) -> None:
        self._settings = get_settings()
        self._include_dietary_flags = include_dietary_flags
        self._cache: dict[tuple, tuple[float, list[Restaurant]]] = {}

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

    # Reduces a user query to bare words, making Overpass injection impossible.
    @staticmethod
    def sanitize_query(query: str) -> str:
        words = re.sub(r"[^A-Za-z0-9 ]+", " ", query).split()
        return "|".join(words[:4])

    # Builds the Overpass QL for a plain "restaurants near here" search.
    @staticmethod
    def _nearby_query(latitude: float, longitude: float, radius: int) -> str:
        around = f"around:{radius},{latitude},{longitude}"
        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];"
            f'nwr["amenity"~"^({FOOD_AMENITIES})$"]["name"]({around});'
            f"out center tags {MAX_RESULTS_PER_CALL};"
        )

    # Builds Overpass QL matching a keyword against name or cuisine tags.
    @staticmethod
    def _text_query(
        pattern: str, latitude: float, longitude: float, radius: int
    ) -> str:
        around = f"around:{radius},{latitude},{longitude}"
        amenity_filter = f'["amenity"~"^({FOOD_AMENITIES})$"]'
        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];"
            f"("
            f'nwr{amenity_filter}["name"~"{pattern}",i]({around});'
            f'nwr{amenity_filter}["cuisine"~"{pattern}",i]({around});'
            f");"
            f"out center tags {MAX_RESULTS_PER_CALL};"
        )

    # Fetches restaurants near a point, using the cache when possible.
    async def search_nearby(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        cache_key = self._cache_key(latitude, longitude, radius_meters)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        query = self._nearby_query(latitude, longitude, radius_meters)
        return await self._run_query(query, cache_key)

    # Fetches restaurants matching a free-text query near a point.
    async def search_text(
        self, query: str, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        cache_key = self._cache_key(latitude, longitude, radius_meters, query)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        pattern = self.sanitize_query(query)
        # A query of pure punctuation leaves nothing searchable, so fall back
        # to a plain nearby search rather than sending Overpass an empty regex.
        if not pattern:
            return await self.search_nearby(latitude, longitude, radius_meters)

        overpass_query = self._text_query(
            pattern, latitude, longitude, radius_meters
        )
        return await self._run_query(overpass_query, cache_key)

    # Runs one Overpass query, normalizes the elements, and caches them.
    async def _run_query(
        self, overpass_query: str, cache_key: tuple
    ) -> list[Restaurant]:
        payload = await self._post_overpass(overpass_query)

        restaurants: list[Restaurant] = []
        for element in payload.get("elements", []):
            restaurant = self.normalize_place(element)
            if restaurant is not None:
                restaurants.append(restaurant)

        self._cache[cache_key] = (time.monotonic(), restaurants)
        return restaurants

    # Sends the query to Overpass, serialized and paced by the usage policy.
    async def _post_overpass(self, overpass_query: str) -> dict[str, Any]:
        global _last_request_at

        async with _REQUEST_LOCK:
            elapsed = time.monotonic() - _last_request_at
            if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
                await asyncio.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)

            headers = {"User-Agent": self._settings.user_agent}
            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT_SECONDS
                ) as client:
                    response = await client.post(
                        self._settings.overpass_url,
                        data={"data": overpass_query},
                        headers=headers,
                    )
            except httpx.RequestError as error:
                raise PlacesError(
                    f"Could not reach OpenStreetMap: {error}"
                ) from error
            finally:
                _last_request_at = time.monotonic()

        if response.status_code != 200:
            raise PlacesError(self._describe_error(response))

        try:
            return response.json()
        except ValueError as error:
            raise PlacesError(
                "OpenStreetMap returned a response we could not read."
            ) from error

    # Turns an Overpass error response into a message safe to show a user.
    @staticmethod
    def _describe_error(response: httpx.Response) -> str:
        if response.status_code == 429:
            return (
                "OpenStreetMap is rate limiting us. Wait a moment and try "
                "again - it is a free volunteer service."
            )
        if response.status_code == 504:
            return (
                "The OpenStreetMap query timed out. Try a smaller search "
                "radius."
            )
        return f"OpenStreetMap error {response.status_code}."

    # Converts one raw Overpass element into a Restaurant, or None if unusable.
    @staticmethod
    def normalize_place(element: dict[str, Any]) -> Restaurant | None:
        tags = element.get("tags") or {}
        name = tags.get("name", "").strip()
        if not name:
            return None

        # Nodes carry lat/lon directly; ways and relations carry a center.
        center = element.get("center") or {}
        latitude = element.get("lat", center.get("lat"))
        longitude = element.get("lon", center.get("lon"))
        if latitude is None or longitude is None:
            return None

        types = osm_tags.place_types_from_tags(tags)
        element_type = element.get("type", "node")
        element_id = element.get("id", "")

        return Restaurant(
            place_id=f"{element_type}/{element_id}",
            name=name,
            latitude=float(latitude),
            longitude=float(longitude),
            address=osm_tags.address_from_tags(tags),
            primary_type=types[0],
            types=types,
            # OpenStreetMap carries no ratings or price levels at all. Leaving
            # these as None is honest, and the scorer redistributes their
            # weight rather than inventing a value.
            rating=None,
            rating_count=0,
            price_level=None,
            open_now=None,
            diet_tags=osm_tags.diet_tags_from_tags(tags),
            maps_uri=(
                f"https://www.openstreetmap.org/{element_type}/{element_id}"
            ),
            summary=tags.get("cuisine", "").replace(";", ", ").replace("_", " "),
        )
