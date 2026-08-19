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
from ..models.guest import Restriction
from ..models.restaurant import Restaurant
from ..models.search_intent import SearchIntent
from . import osm_tags

# Amenity values worth returning for a restaurant search.
FOOD_AMENITIES = "restaurant|cafe|fast_food|pub|bar|ice_cream|food_court"

# OSM tag keys that satisfy each restriction. Nut and shellfish allergies
# have no OSM tag, so a search for them falls back to cuisine and keywords.
OSM_DIET_KEYS: dict[Restriction, tuple[str, ...]] = {
    Restriction.VEGETARIAN: ("diet:vegetarian",),
    Restriction.VEGAN: ("diet:vegan",),
    Restriction.GLUTEN_FREE: ("diet:gluten_free",),
    Restriction.DAIRY_FREE: ("diet:dairy_free", "diet:lactose_free"),
    Restriction.HALAL: ("diet:halal",),
    Restriction.KOSHER: ("diet:kosher",),
}

# Overpass truncates in its own storage order, NOT by distance, so a small
# cap silently discards nearby places and ranks an arbitrary subset. Ranking
# 200 candidates measured at ~8ms, so a generous pool is effectively free and
# leaves enough survivors after dietary exclusions to fill a top five.
MAX_RESULTS_PER_CALL = 200
REQUEST_TIMEOUT_SECONDS = 30.0
OVERPASS_QUERY_TIMEOUT_SECONDS = 25

# Overpass allocates each client a small number of concurrent "slots" and
# enforces its own cooldown server-side. It has NO minimum gap between
# requests - that rule belongs to Nominatim, and applying it here only added
# latency. Two concurrent queries matches the documented slot allowance.
MAX_CONCURRENT_QUERIES = 2
_REQUEST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)


# ---------------------------------------------------------------------------


class PlacesError(RuntimeError):
    """Raised when the places provider cannot be reached or rejects a query."""

    # True when another mirror is worth trying for the same query.
    retryable: bool = False


# Marks an error as worth retrying against a different Overpass mirror.
def _retryable(error: PlacesError) -> PlacesError:
    error.retryable = True
    return error


# ---------------------------------------------------------------------------


class PlacesClient:
    """Fetches nearby restaurants from Overpass and normalizes them."""

    # Prepares the client with settings, a response cache, and a dedupe map.
    def __init__(self, include_dietary_flags: bool = True) -> None:
        self._settings = get_settings()
        self._include_dietary_flags = include_dietary_flags
        self._cache: dict[tuple, tuple[float, list[Restaurant]]] = {}
        # Identical queries already in flight, so a duplicate request joins
        # the existing call instead of queueing a second one behind it.
        self._inflight: dict[tuple, "asyncio.Task[list[Restaurant]]"] = {}

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

    # Builds the Overpass QL for a plain "restaurants near here" search.
    @staticmethod
    def _nearby_query(latitude: float, longitude: float, radius: int) -> str:
        around = f"around:{radius},{latitude},{longitude}"
        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];"
            f'nwr["amenity"~"^({FOOD_AMENITIES})$"]["name"]({around});'
            f"out center tags {MAX_RESULTS_PER_CALL};"
        )

    # Builds Overpass QL from a parsed intent as a union of match clauses.
    @staticmethod
    def _intent_query(
        intent: SearchIntent, latitude: float, longitude: float, radius: int
    ) -> str:
        around = f"around:{radius},{latitude},{longitude}"
        amenity_filter = f'["amenity"~"^({FOOD_AMENITIES})$"]'
        clauses: list[str] = []

        # Diets match the structured diet:* tags, which is the whole point:
        # "vegan" should find a place tagged diet:vegan=only whatever its name.
        for restriction in sorted(intent.diets, key=lambda item: item.value):
            for tag_key in OSM_DIET_KEYS.get(restriction, ()):
                clauses.append(
                    f'nwr{amenity_filter}["{tag_key}"~"^(yes|only)$"]({around});'
                )

        if intent.cuisines:
            pattern = "|".join(
                PlacesClient._escape_term(cuisine)
                for cuisine in sorted(intent.cuisines)
            )
            clauses.append(
                f'nwr{amenity_filter}["cuisine"~"({pattern})",i]({around});'
            )

        if intent.keywords:
            pattern = "|".join(
                PlacesClient._escape_term(word) for word in intent.keywords
            )
            clauses.append(
                f'nwr{amenity_filter}["name"~"({pattern})",i]({around});'
            )

        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];"
            f"({''.join(clauses)});"
            f"out center tags {MAX_RESULTS_PER_CALL};"
        )

    # Strips a term to bare word characters so it cannot alter the query.
    @staticmethod
    def _escape_term(term: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]+", "", term)

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

    # Fetches restaurants matching a parsed search intent near a point.
    async def search_by_intent(
        self,
        intent: SearchIntent,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[Restaurant]:
        # An intent we could not interpret has nothing to filter on, so show
        # everything nearby rather than sending Overpass an empty union.
        if intent.is_empty:
            return await self.search_nearby(latitude, longitude, radius_meters)

        cache_key = self._cache_key(
            latitude, longitude, radius_meters, self._intent_cache_key(intent)
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        overpass_query = self._intent_query(
            intent, latitude, longitude, radius_meters
        )
        return await self._run_query(overpass_query, cache_key)

    # Builds a stable cache key so equivalent phrasings share one entry.
    @staticmethod
    def _intent_cache_key(intent: SearchIntent) -> str:
        return "|".join(
            (
                ",".join(sorted(item.value for item in intent.diets)),
                ",".join(sorted(intent.cuisines)),
                ",".join(sorted(intent.keywords)),
            )
        )

    # Runs a query, collapsing duplicate concurrent requests into one call.
    #
    # Without this, a double-rendered page issues the same search twice; the
    # second waits behind the first on the pacing lock and can outlive the
    # browser's patience, so a working search looks like a timeout.
    async def _run_query(
        self, overpass_query: str, cache_key: tuple
    ) -> list[Restaurant]:
        existing = self._inflight.get(cache_key)
        if existing is not None:
            # shield keeps one caller giving up from cancelling the shared
            # call that other callers are still waiting on.
            return await asyncio.shield(existing)

        task = asyncio.create_task(self._execute_query(overpass_query, cache_key))
        self._inflight[cache_key] = task
        task.add_done_callback(lambda _: self._inflight.pop(cache_key, None))
        return await asyncio.shield(task)

    # Performs one Overpass query, normalizes the elements, and caches them.
    async def _execute_query(
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

    # Sends the query to Overpass, falling back across mirrors when needed.
    #
    # Mirrors keep independent rate-limit slots, so a throttled or queueing
    # primary is worth retrying elsewhere rather than making the user sit out
    # a cooldown. Measured runs hit a 429 after only a few queries.
    async def _post_overpass(self, overpass_query: str) -> dict[str, Any]:
        endpoints = self._settings.overpass_endpoints
        last_error: PlacesError | None = None

        for attempt_index, endpoint in enumerate(endpoints):
            try:
                return await self._post_to(endpoint, overpass_query)
            except PlacesError as error:
                last_error = error
                if not self._is_retryable(error) or attempt_index == len(
                    endpoints
                ) - 1:
                    raise
                continue

        # Unreachable while endpoints is non-empty, but keeps the contract.
        raise last_error or PlacesError("No OpenStreetMap endpoint configured.")

    # Reports whether a failure is worth retrying against another mirror.
    @staticmethod
    def _is_retryable(error: PlacesError) -> bool:
        return getattr(error, "retryable", False)

    # Posts one query to a single endpoint, capped by the slot allowance.
    async def _post_to(self, endpoint: str, overpass_query: str) -> dict[str, Any]:
        async with _REQUEST_SEMAPHORE:
            headers = {"User-Agent": self._settings.user_agent}
            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT_SECONDS
                ) as client:
                    response = await client.post(
                        endpoint, data={"data": overpass_query}, headers=headers
                    )
            except httpx.TimeoutException as error:
                raise _retryable(
                    PlacesError(
                        "OpenStreetMap took too long to answer. It is a shared "
                        "volunteer server and is sometimes busy - try again "
                        "in a moment."
                    )
                ) from error
            except httpx.RequestError as error:
                raise _retryable(
                    PlacesError(f"Could not reach OpenStreetMap: {error}")
                ) from error

        if response.status_code != 200:
            error = PlacesError(self._describe_error(response))
            if response.status_code in (429, 503, 504):
                error = _retryable(error)
            raise error

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
                "Every OpenStreetMap server we tried is rate limiting us. "
                "Wait about a minute and try again - they are free volunteer "
                "services with a shared query queue."
            )
        if response.status_code in (503, 504):
            return (
                "The OpenStreetMap servers are busy right now. Try again in "
                "a moment."
            )
        if response.status_code == 400:
            return (
                "OpenStreetMap rejected the search. Try different wording."
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
