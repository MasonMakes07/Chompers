"""Pydantic request and response contracts.

Every field is bounded here so malformed or hostile input is rejected before
it reaches any business logic or costs a Google API call.
"""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from .models.guest import Restriction

MAX_GUESTS = 20
MAX_NAME_LENGTH = 40
MAX_CUISINE_TERMS = 8
MAX_CUISINE_LENGTH = 30

# Input that looks like code or markup is rejected outright rather than
# escaped, per the project rule on user input.
CODE_LIKE_PATTERN = re.compile(
    r"(<\s*script)|(<\s*/?\s*[a-z]+\s*>)|(\{\{)|(\$\{)|(;\s*(drop|select|insert)\s)"
    r"|(--\s)|(\bunion\s+select\b)|(javascript:)|(\bon\w+\s*=)",
    re.IGNORECASE,
)


# Rejects free text that resembles code, markup, or injection payloads.
def reject_code_like(value: str, field_name: str) -> str:
    if CODE_LIKE_PATTERN.search(value):
        raise ValueError(f"{field_name} contains disallowed characters.")
    return value


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class GuestRequest(BaseModel):
    """One guest as submitted by the frontend."""

    name: str = Field(default="Guest", max_length=MAX_NAME_LENGTH)
    restrictions: list[Restriction] = Field(default_factory=list)
    liked_cuisines: list[str] = Field(
        default_factory=list, max_length=MAX_CUISINE_TERMS
    )
    disliked_cuisines: list[str] = Field(
        default_factory=list, max_length=MAX_CUISINE_TERMS
    )

    # Strips the name and rejects code-like content.
    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip() or "Guest"
        return reject_code_like(cleaned, "Guest name")

    # Bounds and sanitizes each cuisine term in both preference lists.
    @field_validator("liked_cuisines", "disliked_cuisines")
    @classmethod
    def _clean_cuisines(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw_term in values:
            term = raw_term.strip().lower()[:MAX_CUISINE_LENGTH]
            if term:
                cleaned.append(reject_code_like(term, "Cuisine"))
        return cleaned


class SearchRequest(BaseModel):
    """A full search: who is eating, where, and within what limits."""

    guest_count: int = Field(ge=1, le=MAX_GUESTS)
    guests: list[GuestRequest] = Field(default_factory=list, max_length=MAX_GUESTS)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    location_query: str | None = Field(default=None, max_length=120)
    radius_meters: int = Field(default=5000, ge=500, le=50000)
    max_price_level: int | None = Field(default=None, ge=0, le=4)

    # Sanitizes the typed location, which is the only free-text search field.
    @field_validator("location_query")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return reject_code_like(cleaned, "Location")

    # Requires either coordinates or a typed location, and never neither.
    @model_validator(mode="after")
    def _require_a_location(self) -> "SearchRequest":
        has_coordinates = self.latitude is not None and self.longitude is not None
        if not has_coordinates and not self.location_query:
            raise ValueError(
                "Provide either coordinates or a city/ZIP to search near."
            )
        return self


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class RestrictionFitResponse(BaseModel):
    """Why one restriction was judged satisfied or not."""

    restriction: str
    label: str
    confidence: float
    evidence: str
    reason: str
    verified: bool


class GuestFitResponse(BaseModel):
    """How well one named guest is served by a restaurant."""

    guest_name: str
    confidence: float
    status: str
    restriction_fits: list[RestrictionFitResponse]


class RestaurantResponse(BaseModel):
    """A single ranked restaurant, with the reasoning attached."""

    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    cuisine: str
    rating: float | None
    rating_count: int
    price_level: int | None
    open_now: bool | None
    maps_uri: str
    distance_meters: float
    score: float
    group_fit: float
    guest_fits: list[GuestFitResponse]
    warnings: list[str]


class SearchResponse(BaseModel):
    """The full search result returned to the frontend."""

    results: list[RestaurantResponse]
    searched_location: str
    candidates_considered: int
    excluded_count: int
    notes: list[str]
