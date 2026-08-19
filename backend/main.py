"""FastAPI application: routes, wiring, and error translation.

The Google API key never leaves this process. The browser talks only to this
backend, so no key is ever present in a frontend bundle.
"""

import os

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
from .services.geocoder import Geocoder, GeocodingError
from .services.places_client import PlacesClient, PlacesError

RESULT_LIMIT = 5

settings = get_settings()

# Enterprise dietary fields are opt-in: they cut the free monthly allowance
# from 5,000 calls to 1,000, and cuisine priors cover the same ground.
include_dietary_flags = os.getenv("INCLUDE_DIETARY_FLAGS", "false").lower() == "true"

app = FastAPI(
    title="Chompers API",
    description="Finds restaurants that fit a whole group's dietary needs.",
    version="1.0.0",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

places_client = PlacesClient(include_dietary_flags=include_dietary_flags)
geocoder = Geocoder()


# ---------------------------------------------------------------------------


# Reports service health and whether an API key is configured.
@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "api_key_configured": settings.has_api_key,
        "dietary_flags_enabled": include_dietary_flags,
    }


# Resolves the search origin from coordinates or a typed city/ZIP.
async def _resolve_location(payload: SearchRequest) -> tuple[float, float, str]:
    if payload.latitude is not None and payload.longitude is not None:
        return payload.latitude, payload.longitude, "your current location"
    try:
        return await geocoder.resolve(payload.location_query or "")
    except GeocodingError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error


# Finds the top restaurants that fit the whole party's needs.
@app.post("/api/search", response_model=SearchResponse)
async def search(payload: SearchRequest) -> SearchResponse:
    if not settings.has_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No Google API key configured. Copy .env.example to "
                "backend/.env and add GOOGLE_MAPS_API_KEY."
            ),
        )

    latitude, longitude, location_label = await _resolve_location(payload)

    # A free-text query routes to Text Search; otherwise plain Nearby Search.
    # Both cost exactly one API call.
    try:
        if payload.query:
            candidates = await places_client.search_text(
                payload.query, latitude, longitude, payload.radius_meters
            )
        else:
            candidates = await places_client.search_nearby(
                latitude, longitude, payload.radius_meters
            )
    except PlacesError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error

    party = translator.party_from_request(payload, latitude, longitude)
    ranked, excluded_count = rank_restaurants(candidates, party, limit=RESULT_LIMIT)

    return translator.build_search_response(
        ranked=ranked,
        searched_location=location_label,
        candidates_considered=len(candidates),
        excluded_count=excluded_count,
        query=payload.query,
    )
