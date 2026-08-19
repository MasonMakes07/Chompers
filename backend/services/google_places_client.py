"""Google Places API (New) provider.

One user search costs exactly ONE API call. Google returns up to 20 places,
which are ranked locally by the scorer - that is what keeps usage inside the
free tier of 5,000 Nearby Search calls per month.

The API key is read from settings and attached in exactly one place here. It
never appears in a response, a log line, or anything the browser can see.
"""

import asyncio
from typing import Any

import httpx

from ..models.restaurant import Restaurant
from ..models.search_intent import SearchIntent
from .places_base import BasePlacesClient, PlacesError, mark_retryable

NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Pro-tier fields. Nearby Search Pro allows 5,000 free calls per month.
BASE_FIELDS = (
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

# Enterprise-tier fields. Requesting these drops the free allowance from
# 5,000 to 1,000 calls per month, so they stay opt-in. The cuisine priors
# cover most of the same ground, so leaving them off costs little.
ENTERPRISE_FIELDS = (
    "places.servesVegetarianFood",
    "places.currentOpeningHours.openNow",
)

# Google returns price as an enum string; map it to a 0-4 integer.
PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

# Google's hard ceiling for a single search response.
MAX_RESULTS_PER_CALL = 20
REQUEST_TIMEOUT_SECONDS = 15.0

# Last line of defence: even requests the rate limiter allows must not all
# reach Google at once. Excess callers queue here instead of stampeding.
MAX_CONCURRENT_QUERIES = 4
_REQUEST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)


# ---------------------------------------------------------------------------


class GooglePlacesClient(BasePlacesClient):
    """Fetches nearby restaurants from Google Places and normalizes them."""

    provider_name = "google"

    # Prepares the client, noting whether enterprise dietary fields are on.
    def __init__(self, include_dietary_flags: bool = False) -> None:
        super().__init__()
        self._include_dietary_flags = include_dietary_flags
        # Created lazily inside the running loop and reused across searches so
        # the TLS handshake and connection are not rebuilt on every call.
        self._http_client: httpx.AsyncClient | None = None

    # Returns the pooled HTTP client, creating it on first use.
    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS
            )
        return self._http_client

    # Closes the pooled client when the server shuts down.
    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # Builds the field mask, widening it only if enterprise fields are on.
    def _field_mask(self) -> str:
        fields = list(BASE_FIELDS)
        if self._include_dietary_flags:
            fields.extend(ENTERPRISE_FIELDS)
        return ",".join(fields)

    # Fetches restaurants near a point with one Nearby Search call.
    async def _fetch_nearby(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[Restaurant]:
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
        return await self._post(NEARBY_SEARCH_URL, payload)

    # Fetches restaurants matching a query with one Text Search call.
    async def _fetch_by_intent(
        self,
        intent: SearchIntent,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[Restaurant]:
        # Google's text search already handles synonyms and misspellings, so
        # the raw phrasing beats our parsed terms here. The parsed intent is
        # still used by the scorer to rank what comes back.
        payload = {
            "textQuery": intent.raw or " ".join(sorted(intent.cuisines)),
            "includedType": "restaurant",
            "maxResultCount": MAX_RESULTS_PER_CALL,
            # locationBias, not locationRestriction: a strong text match just
            # outside the radius is still worth showing on a keyword search.
            "locationBias": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": float(radius_meters),
                }
            },
        }
        return await self._post(TEXT_SEARCH_URL, payload)

    # Sends one request to Google and normalizes the places it returns.
    async def _post(
        self, url: str, payload: dict[str, Any]
    ) -> list[Restaurant]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._settings.require_api_key(),
            "X-Goog-FieldMask": self._field_mask(),
        }

        try:
            async with _REQUEST_SEMAPHORE:
                response = await self._client().post(
                    url, json=payload, headers=headers
                )
        except httpx.TimeoutException as error:
            raise mark_retryable(
                PlacesError("Google Places took too long to answer.")
            ) from error
        except httpx.RequestError as error:
            raise PlacesError(
                f"Could not reach Google Places: {error}"
            ) from error

        if response.status_code != 200:
            raise PlacesError(self._describe_error(response))

        return [
            self.normalize_place(place)
            for place in response.json().get("places", [])
        ]

    # Turns a Google error into a message safe to show a user. The key is
    # never echoed, only whether it was accepted.
    @staticmethod
    def _describe_error(response: httpx.Response) -> str:
        if response.status_code == 403:
            return (
                "Google rejected the API key. Check that Places API (New) is "
                "enabled and that the key restrictions allow it."
            )
        if response.status_code == 429:
            return (
                "Daily quota reached. That is the safety cap doing its job - "
                "try tomorrow, or raise the cap in Google Cloud Console."
            )
        if response.status_code == 400:
            return "Google rejected the search. Try different wording."
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        # Guard against an error body echoing the key back into our response.
        if detail and "AIza" in detail:
            detail = ""
        return f"Google Places error {response.status_code}. {detail}".strip()

    # Converts one raw Google place into a normalized Restaurant.
    @staticmethod
    def normalize_place(place: dict[str, Any]) -> Restaurant:
        location = place.get("location") or {}
        opening_hours = place.get("currentOpeningHours") or {}
        place_types = [str(item).lower() for item in (place.get("types") or [])]

        return Restaurant(
            place_id=place.get("id", ""),
            name=(place.get("displayName") or {}).get("text", "Unnamed"),
            latitude=float(location.get("latitude", 0.0)),
            longitude=float(location.get("longitude", 0.0)),
            address=place.get("formattedAddress", ""),
            primary_type=place.get("primaryType", ""),
            types=place_types,
            rating=place.get("rating"),
            rating_count=int(place.get("userRatingCount") or 0),
            price_level=PRICE_LEVEL_MAP.get(place.get("priceLevel", "")),
            open_now=opening_hours.get("openNow"),
            # Restaurant folds this into diet_tags, so the scorer reads one
            # source of explicit evidence whatever the provider.
            serves_vegetarian=place.get("servesVegetarianFood"),
            maps_uri=place.get("googleMapsUri", ""),
            summary=(place.get("editorialSummary") or {}).get("text", ""),
        )
