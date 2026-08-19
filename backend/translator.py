"""Translator: the single boundary between the frontend and the backend.

Every conversion between wire format (Pydantic schemas the React app sees)
and domain models (Guest, Party, Restaurant) happens here and nowhere else.
Routes stay thin, and the matching engine never knows a browser exists.
"""

from .matching.scorer import EVIDENCE_IS_VERIFIED, GuestFit, ScoredRestaurant
from .models.guest import Guest
from .models.party import Party
from .schemas import (
    GuestFitResponse,
    GuestRequest,
    RestaurantResponse,
    RestrictionFitResponse,
    SearchRequest,
    SearchResponse,
)

# Confidence thresholds that turn a raw number into a UI status word.
STATUS_GOOD_THRESHOLD = 0.75
STATUS_LIMITED_THRESHOLD = 0.45

STATUS_GOOD = "good"
STATUS_LIMITED = "limited"
STATUS_RISKY = "risky"


# ---------------------------------------------------------------------------
# Frontend -> backend
# ---------------------------------------------------------------------------


# Converts one wire guest into a domain Guest.
def guest_from_request(payload: GuestRequest) -> Guest:
    return Guest(
        name=payload.name,
        restrictions=set(payload.restrictions),
        liked_cuisines=set(payload.liked_cuisines),
        disliked_cuisines=set(payload.disliked_cuisines),
    )


# Builds a domain Party from a validated request plus resolved coordinates.
def party_from_request(
    payload: SearchRequest, latitude: float, longitude: float
) -> Party:
    return Party(
        guest_count=payload.guest_count,
        guests=[guest_from_request(guest) for guest in payload.guests],
        latitude=latitude,
        longitude=longitude,
        radius_meters=payload.radius_meters,
        max_price_level=payload.max_price_level,
    )


# ---------------------------------------------------------------------------
# Backend -> frontend
# ---------------------------------------------------------------------------


# Turns a confidence value into the status word the UI colors badges by.
def confidence_to_status(confidence: float) -> str:
    if confidence >= STATUS_GOOD_THRESHOLD:
        return STATUS_GOOD
    if confidence >= STATUS_LIMITED_THRESHOLD:
        return STATUS_LIMITED
    return STATUS_RISKY


# Converts one guest's fit, including per-restriction reasoning, to the wire.
def guest_fit_to_response(fit: GuestFit) -> GuestFitResponse:
    return GuestFitResponse(
        guest_name=fit.guest_name,
        confidence=round(fit.confidence, 3),
        status=confidence_to_status(fit.confidence),
        restriction_fits=[
            RestrictionFitResponse(
                restriction=item.restriction.value,
                label=item.label,
                confidence=round(item.confidence, 3),
                evidence=item.evidence.value,
                reason=item.reason,
                verified=EVIDENCE_IS_VERIFIED.get(item.evidence, False),
            )
            for item in fit.restriction_fits
        ],
    )


# Picks the most specific cuisine label available for display.
def readable_cuisine(place_types: list[str], primary_type: str) -> str:
    candidate = primary_type or next(
        (item for item in place_types if item.endswith("_restaurant")), ""
    )
    if not candidate:
        candidate = place_types[0] if place_types else "restaurant"
    return candidate.replace("_", " ").title()


# Converts one scored restaurant into its wire representation.
def scored_to_response(scored: ScoredRestaurant) -> RestaurantResponse:
    restaurant = scored.restaurant
    return RestaurantResponse(
        place_id=restaurant.place_id,
        name=restaurant.name,
        address=restaurant.address,
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        cuisine=readable_cuisine(restaurant.types, restaurant.primary_type),
        rating=restaurant.rating,
        rating_count=restaurant.rating_count,
        price_level=restaurant.price_level,
        open_now=restaurant.open_now,
        maps_uri=restaurant.maps_uri,
        distance_meters=scored.distance_meters,
        score=scored.score,
        group_fit=scored.group_fit,
        guest_fits=[guest_fit_to_response(fit) for fit in scored.guest_fits],
        warnings=scored.warnings,
    )


# Assembles the complete search response, including honest result notes.
def build_search_response(
    ranked: list[ScoredRestaurant],
    searched_location: str,
    candidates_considered: int,
    excluded_count: int,
    query: str | None = None,
) -> SearchResponse:
    notes: list[str] = []

    if excluded_count and ranked and excluded_count == candidates_considered:
        notes.append(
            "No nearby restaurant clearly suits everyone. These are the "
            "closest matches - check the warnings before deciding."
        )
    elif excluded_count:
        notes.append(
            f"{excluded_count} nearby restaurant(s) were ruled out because at "
            f"least one guest likely could not eat there."
        )

    if not ranked:
        if query:
            notes.append(
                f"Nothing matched '{query}' nearby. Try a broader term or a "
                f"wider radius."
            )
        else:
            notes.append("No restaurants found. Try widening the search radius.")

    notes.append(
        "Dietary fit is inferred from cuisine and listing data. Confirm with "
        "the restaurant if a restriction is serious."
    )

    return SearchResponse(
        results=[scored_to_response(item) for item in ranked],
        searched_location=searched_location,
        query=query,
        candidates_considered=candidates_considered,
        excluded_count=excluded_count,
        notes=notes,
    )
