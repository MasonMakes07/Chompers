"""OpenStreetMap provider, via the Overpass API.

No API key, no billing account, no quota. Kept as a fully working fallback:
if Google billing lapses or a key is revoked, flip PLACES_PROVIDER back to
"openstreetmap" and the app keeps running with no code change.

Overpass is a volunteer service, so the cost here is politeness rather than
money: bounded queries, an identifying User-Agent, and a cap on concurrency.
"""

import asyncio
import re
from typing import Any

import httpx

from ..models.guest import Restriction
from ..models.restaurant import Restaurant
from ..models.search_intent import SearchIntent
from . import osm_tags
from .places_base import BasePlacesClient, PlacesError, mark_retryable

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
# 200 candidates measured at ~11ms, so a generous pool is effectively free.
MAX_RESULTS_PER_CALL = 200
REQUEST_TIMEOUT_SECONDS = 30.0
OVERPASS_QUERY_TIMEOUT_SECONDS = 25

# Overpass allocates each client a small number of concurrent "slots" and
# enforces its own cooldown server-side. It has NO minimum gap between
# requests - that rule belongs to Nominatim. Two matches the slot allowance.
MAX_CONCURRENT_QUERIES = 2
_REQUEST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)


# ---------------------------------------------------------------------------


class OverpassPlacesClient(BasePlacesClient):
    """Fetches nearby restaurants from OpenStreetMap and normalizes them."""

    provider_name = "openstreetmap"

    # Fetches every named food place near a point.
    async def _fetch_nearby(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
        query = self._nearby_query(latitude, longitude, radius_meters)
        return await self._run(query)

    # Fetches places matching a parsed intent's diets, cuisines, or words.
    async def _fetch_by_intent(
        self,
        intent: SearchIntent,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[Restaurant]:
        query = self._intent_query(intent, latitude, longitude, radius_meters)
        return await self._run(query)

    # Runs one Overpass query and normalizes the elements it returns.
    async def _run(self, overpass_query: str) -> list[Restaurant]:
        payload = await self._post_overpass(overpass_query)

        restaurants: list[Restaurant] = []
        for element in payload.get("elements", []):
            restaurant = self.normalize_place(element)
            if restaurant is not None:
                restaurants.append(restaurant)
        return restaurants

    # ---- Query construction ----------------------------------------------

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
                OverpassPlacesClient._escape_term(cuisine)
                for cuisine in sorted(intent.cuisines)
            )
            clauses.append(
                f'nwr{amenity_filter}["cuisine"~"({pattern})",i]({around});'
            )

        if intent.keywords:
            pattern = "|".join(
                OverpassPlacesClient._escape_term(word)
                for word in intent.keywords
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

    # ---- Transport --------------------------------------------------------

    # Sends the query to Overpass, falling back across mirrors when needed.
    async def _post_overpass(self, overpass_query: str) -> dict[str, Any]:
        endpoints = self._settings.overpass_endpoints
        # Report the PRIMARY's failure, not the last mirror's. A mirror being
        # unreachable is far less informative than the main server saying it
        # is rate limiting us, and reporting the mirror hides the real cause.
        primary_error: PlacesError | None = None

        for endpoint in endpoints:
            try:
                return await self._post_to(endpoint, overpass_query)
            except PlacesError as error:
                if primary_error is None:
                    primary_error = error
                if not getattr(error, "retryable", False):
                    raise
                continue

        raise primary_error or PlacesError("No OpenStreetMap endpoint configured.")

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
                raise mark_retryable(
                    PlacesError(
                        "OpenStreetMap took too long to answer. It is a shared "
                        "volunteer server and is sometimes busy - try again "
                        "in a moment."
                    )
                ) from error
            except httpx.RequestError as error:
                raise mark_retryable(
                    PlacesError(f"Could not reach OpenStreetMap: {error}")
                ) from error

        if response.status_code != 200:
            error = PlacesError(self._describe_error(response))
            if response.status_code in (429, 503, 504):
                error = mark_retryable(error)
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
            return "OpenStreetMap rejected the search. Try different wording."
        return f"OpenStreetMap error {response.status_code}."

    # ---- Normalization ----------------------------------------------------

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
            # OpenStreetMap carries no ratings or price levels at all.
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
