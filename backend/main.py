"""FastAPI application: routes, wiring, and error translation.

The Google API key never leaves this process. The browser talks only to this
backend, so no key is ever present in a frontend bundle.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from . import translator
from .config import get_settings
from .matching.scorer import rank_restaurants
from .middleware import (
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from .schemas import SearchRequest, SearchResponse
from .services.geocoder import Geocoder, GeocoderBusyError, GeocodingError
from .services.places_client import PlacesError, create_places_client
from .services.query_parser import parse_query

settings = get_settings()


# Closes the shared upstream HTTP client when the server stops.
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await places_client.aclose()


app = FastAPI(
    title="Chompers API",
    description="Finds restaurants that fit a whole group's dietary needs.",
    version="1.0.0",
    lifespan=lifespan,
)

# Order matters, and reads backwards: add_middleware prepends, so the LAST
# one added is the outermost. Effective order is therefore
# CORS -> SecurityHeaders -> RequestSizeLimit -> RateLimit -> route.
#
# SecurityHeaders has to sit outside the two limiters. When it was innermost,
# every response those limiters short-circuit - each 429 and each 413 - went
# out with no security headers at all, because the route (and so the header
# middleware) never ran.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    # Retry-After is not CORS-safelisted, so the browser cannot read it on a
    # cross-origin 429 unless it is explicitly exposed. The frontend reads it
    # to tell the user how long to wait.
    expose_headers=["Retry-After"],
)

places_client = create_places_client()
geocoder = Geocoder()


# ---------------------------------------------------------------------------


# Reports service health and whether an API key is configured.
@app.get("/api/health")
async def health() -> dict[str, object]:
    # Reports whether a key was found, never any part of the key itself.
    return {
        "status": "ok",
        "provider": places_client.provider_name,
        "requested_provider": settings.places_provider,
        "api_key_configured": settings.has_api_key,
        "dietary_flags_enabled": settings.include_dietary_flags,
    }


# Names the coordinates the browser reported, for display in the UI.
@app.get("/api/reverse-geocode")
async def reverse_geocode(latitude: float, longitude: float) -> dict[str, object]:
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Coordinates are out of range.",
        )
    try:
        return {"label": await geocoder.reverse(latitude, longitude)}
    except GeocoderBusyError as error:
        # Shedding load, not a bad gateway. 503 with Retry-After tells the
        # client to come back rather than treating this as a dead end.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
            headers={"Retry-After": "5"},
        ) from error
    except GeocodingError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error


# Names a coordinate for display, degrading to a generic phrase on failure.
async def _name_location(latitude: float, longitude: float) -> str:
    try:
        return await geocoder.reverse(latitude, longitude)
    except GeocodingError:
        return "your current location"


# Turns a typed city or ZIP into coordinates, or rejects the search.
async def _geocode_or_reject(location_query: str) -> tuple[float, float, str]:
    try:
        return await geocoder.resolve(location_query)
    except GeocoderBusyError as error:
        # The query was fine; we simply could not get to it in time.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
            headers={"Retry-After": "5"},
        ) from error
    except GeocodingError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error


# Finds the top restaurants that fit the whole party's needs.
@app.post("/api/search", response_model=SearchResponse)
async def search(payload: SearchRequest) -> SearchResponse:
    # A typed query is parsed into diets, cuisines, and leftover keywords, so
    # "vegan" searches the diet:* tags rather than matching letters in a name.
    intent = parse_query(payload.query) if payload.query else None

    resolved_label: str | None = None
    label_task: asyncio.Task[str] | None = None

    if payload.latitude is not None and payload.longitude is not None:
        latitude, longitude = payload.latitude, payload.longitude
        # The coordinates are already known, so naming them is cosmetic.
        # Run it alongside the search instead of making the search wait.
        label_task = asyncio.create_task(_name_location(latitude, longitude))
    else:
        latitude, longitude, resolved_label = await _geocode_or_reject(
            payload.location_query or ""
        )

    try:
        if intent is not None and not intent.is_empty:
            candidates = await places_client.search_by_intent(
                intent, latitude, longitude, payload.radius_meters
            )
        else:
            candidates = await places_client.search_nearby(
                latitude, longitude, payload.radius_meters
            )
    except PlacesError as error:
        if label_task is not None:
            label_task.cancel()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error

    # By now the label lookup has almost certainly finished alongside the
    # search, so this await usually costs nothing.
    location_label = (
        await label_task if label_task is not None else resolved_label or ""
    )

    party = translator.party_from_request(payload, latitude, longitude, intent)
    ranked, excluded_count = rank_restaurants(
        candidates, party, limit=payload.limit
    )

    return translator.build_search_response(
        ranked=ranked,
        searched_location=location_label,
        candidates_considered=len(candidates),
        excluded_count=excluded_count,
        query=payload.query,
    )
