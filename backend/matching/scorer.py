"""Group-aware ranking: score restaurants by how well they serve everyone.

The central idea is that a restaurant where four people are delighted and one
person cannot eat is a BAD result. A plain average hides that person, so the
group score is dominated by the worst-served guest.
"""

import math
from dataclasses import dataclass, field
from enum import Enum

from ..models.guest import ALLERGY_RESTRICTIONS, Guest, RESTRICTION_LABELS
from ..models.guest import Restriction
from ..models.party import Party
from ..models.restaurant import Restaurant
from . import dietary_rules

# --- Tunable weights. These sum to 1.0. ------------------------------------
WEIGHT_GROUP_FIT = 0.55
WEIGHT_RATING = 0.20
WEIGHT_DISTANCE = 0.10
WEIGHT_CUISINE = 0.10
WEIGHT_PRICE = 0.05

# How much the worst-served guest dominates the group score. At 0.6 a single
# poorly served guest cannot be averaged away by four happy ones.
MIN_GUEST_WEIGHT = 0.60
MEAN_GUEST_WEIGHT = 1.0 - MIN_GUEST_WEIGHT

# Any guest below this confidence disqualifies the restaurant outright.
HARD_FLOOR = 0.25

# Bayesian damping so a 5.0 from 3 reviews cannot beat a 4.6 from 900.
RATING_PRIOR_MEAN = 3.9
RATING_PRIOR_COUNT = 20

# Confidence granted by an explicit first-party diet claim. OpenStreetMap
# publishes these as diet:* tags covering six of our eight restrictions,
# which is stronger evidence than any cuisine prior can be.
EXPLICIT_DIET_CONFIDENCE = {
    "only": 0.98,
    "yes": 0.90,
    "limited": 0.55,
    "no": 0.08,
}

# How each explicit claim is phrased in the "why this ranked" explanation.
EXPLICIT_DIET_REASON = {
    "only": "the menu is entirely {label}",
    "yes": "tagged as serving {label}",
    "limited": "tagged as limited {label} options",
    "no": "tagged as not serving {label}",
}

# Retained so a provider exposing only a vegetarian boolean still works.
EXPLICIT_FLAG_TRUE = 0.90
EXPLICIT_FLAG_FALSE = 0.12


# ---------------------------------------------------------------------------


class Evidence(str, Enum):
    """How a confidence value was derived, strongest first."""

    EXPLICIT = "explicit"
    KEYWORD = "keyword"
    CUISINE = "cuisine"
    DEFAULT = "default"


# Maps evidence strength to whether it should be shown as a verified fact.
EVIDENCE_IS_VERIFIED = {
    Evidence.EXPLICIT: True,
    Evidence.KEYWORD: False,
    Evidence.CUISINE: False,
    Evidence.DEFAULT: False,
}


# ---------------------------------------------------------------------------


@dataclass
class RestrictionFit:
    """Confidence that one restriction is satisfied, plus why we think so."""

    restriction: Restriction
    confidence: float
    evidence: Evidence
    reason: str

    # Returns the human-readable restriction name for the UI.
    @property
    def label(self) -> str:
        return RESTRICTION_LABELS.get(self.restriction, self.restriction.value)


@dataclass
class GuestFit:
    """How well one guest is served, driven by their weakest restriction."""

    guest_name: str
    confidence: float
    restriction_fits: list[RestrictionFit] = field(default_factory=list)

    # Returns the restriction that limited this guest, if any.
    @property
    def limiting_fit(self) -> RestrictionFit | None:
        if not self.restriction_fits:
            return None
        return min(self.restriction_fits, key=lambda fit: fit.confidence)


@dataclass
class ScoredRestaurant:
    """A restaurant with its final score and the reasoning behind it."""

    restaurant: Restaurant
    score: float
    group_fit: float
    guest_fits: list[GuestFit]
    distance_meters: float
    warnings: list[str] = field(default_factory=list)

    # Returns the names of guests who may struggle to eat here.
    def struggling_guests(self) -> list[str]:
        return [fit.guest_name for fit in self.guest_fits if fit.confidence < 0.45]


# ---------------------------------------------------------------------------
# Confidence derivation
# ---------------------------------------------------------------------------


# Resolves the cuisine-prior confidence across all of a restaurant's types.
def _cuisine_confidence(
    restaurant: Restaurant, restriction: Restriction
) -> tuple[float, str] | None:
    known_priors = [
        (dietary_rules.cuisine_prior(place_type, restriction), place_type)
        for place_type in restaurant.types
        if dietary_rules.is_known_cuisine(place_type)
    ]
    known_priors = [(value, name) for value, name in known_priors if value is not None]
    if not known_priors:
        return None

    # Allergies take the most cautious type; diets take the best option
    # available, since one accommodating menu section is enough to eat well.
    if restriction in ALLERGY_RESTRICTIONS:
        confidence, place_type = min(known_priors, key=lambda pair: pair[0])
    else:
        confidence, place_type = max(known_priors, key=lambda pair: pair[0])

    readable_type = place_type.replace("_", " ")
    return confidence, f"based on {readable_type}"


# Derives confidence that one restriction is met, using the best evidence.
def restriction_confidence(
    restaurant: Restaurant, restriction: Restriction
) -> RestrictionFit:
    # Tier 1: an explicit first-party diet claim beats every inference.
    claimed_value = restaurant.diet_tags.get(restriction.value)
    if claimed_value in EXPLICIT_DIET_CONFIDENCE:
        label = RESTRICTION_LABELS.get(restriction, restriction.value)
        return RestrictionFit(
            restriction,
            EXPLICIT_DIET_CONFIDENCE[claimed_value],
            Evidence.EXPLICIT,
            EXPLICIT_DIET_REASON[claimed_value].format(label=label),
        )

    # Tier 2: a self-declared name is strong evidence.
    keyword_match = dietary_rules.keyword_evidence(
        restaurant.searchable_name, restriction
    )
    if keyword_match is not None:
        confidence, reason = keyword_match
        return RestrictionFit(restriction, confidence, Evidence.KEYWORD, reason)

    # Tier 3: cuisine priors from the knowledge table.
    cuisine_match = _cuisine_confidence(restaurant, restriction)
    if cuisine_match is not None:
        confidence, reason = cuisine_match
        return RestrictionFit(restriction, confidence, Evidence.CUISINE, reason)

    # Tier 4: nothing known, so stay neutral and say so.
    return RestrictionFit(
        restriction,
        dietary_rules.default_prior(restriction),
        Evidence.DEFAULT,
        "no cuisine information available",
    )


# Scores one guest by their single hardest-to-satisfy restriction.
def guest_confidence(restaurant: Restaurant, guest: Guest) -> GuestFit:
    restrictions = guest.effective_restrictions()
    if not restrictions:
        return GuestFit(guest.name, 1.0, [])

    fits = [
        restriction_confidence(restaurant, restriction)
        for restriction in sorted(restrictions, key=lambda item: item.value)
    ]
    weakest = min(fit.confidence for fit in fits)
    return GuestFit(guest.name, weakest, fits)


# Blends guest confidences so the worst-served guest dominates the result.
def group_fit_score(guest_fits: list[GuestFit]) -> float:
    if not guest_fits:
        return 1.0
    confidences = [fit.confidence for fit in guest_fits]
    lowest = min(confidences)
    average = sum(confidences) / len(confidences)
    return MIN_GUEST_WEIGHT * lowest + MEAN_GUEST_WEIGHT * average


# ---------------------------------------------------------------------------
# Secondary score components
# ---------------------------------------------------------------------------


# Normalizes a star rating to [0, 1], damped toward the prior by low counts.
def rating_score(rating: float | None, rating_count: int) -> float:
    if rating is None or rating <= 0:
        return 0.5
    total_weight = rating_count + RATING_PRIOR_COUNT
    damped = (
        rating * rating_count + RATING_PRIOR_MEAN * RATING_PRIOR_COUNT
    ) / total_weight
    return max(0.0, min(1.0, (damped - 1.0) / 4.0))


# Converts distance into a [0, 1] score that decays smoothly with range.
def distance_score(distance_meters: float, radius_meters: int) -> float:
    if radius_meters <= 0:
        return 0.5
    return math.exp(-distance_meters / (radius_meters * 0.6))


# Rewards restaurants matching party cuisine likes and penalizes dislikes.
def cuisine_preference_score(
    restaurant: Restaurant, liked: set[str], disliked: set[str]
) -> float:
    if not liked and not disliked:
        return 0.5
    haystack = f"{' '.join(restaurant.types)} {restaurant.searchable_name}"
    score = 0.5
    if any(term in haystack for term in liked):
        score += 0.5
    if any(term in haystack for term in disliked):
        score -= 0.5
    return max(0.0, min(1.0, score))


# Scores how well the price level fits the party's stated ceiling.
def price_fit_score(price_level: int | None, max_price_level: int | None) -> float:
    if max_price_level is None:
        return 0.5
    if price_level is None:
        return 0.4
    return 1.0 if price_level <= max_price_level else 0.0


# ---------------------------------------------------------------------------
# Top-level ranking
# ---------------------------------------------------------------------------


# Scores a single restaurant against the whole party and explains the result.
def score_restaurant(restaurant: Restaurant, party: Party) -> ScoredRestaurant:
    guest_fits = [guest_confidence(restaurant, guest) for guest in party.guests]
    group_fit = group_fit_score(guest_fits)
    distance = restaurant.distance_meters_from(party.latitude, party.longitude)

    # Only components with real data contribute, and the total is renormalized
    # by the weights actually used. A provider without ratings or prices (as
    # OpenStreetMap is) therefore shifts that influence onto group fit and
    # distance, instead of scoring every restaurant with the same dead
    # constant and letting it silently compress the spread.
    components: list[tuple[float, float]] = [
        (WEIGHT_GROUP_FIT, group_fit),
        (WEIGHT_DISTANCE, distance_score(distance, party.radius_meters)),
        (
            WEIGHT_CUISINE,
            cuisine_preference_score(
                restaurant, party.liked_cuisines(), party.disliked_cuisines()
            ),
        ),
    ]
    if restaurant.rating is not None:
        components.append(
            (WEIGHT_RATING, rating_score(restaurant.rating, restaurant.rating_count))
        )
    if party.max_price_level is not None and restaurant.price_level is not None:
        components.append(
            (WEIGHT_PRICE, price_fit_score(restaurant.price_level,
                                           party.max_price_level))
        )

    total_weight = sum(weight for weight, _ in components)
    total = sum(weight * value for weight, value in components) / total_weight

    warnings = _build_warnings(restaurant, party, guest_fits)
    return ScoredRestaurant(
        restaurant=restaurant,
        score=round(total, 4),
        group_fit=round(group_fit, 4),
        guest_fits=guest_fits,
        distance_meters=round(distance, 1),
        warnings=warnings,
    )


# Collects honest caveats to display alongside a result.
def _build_warnings(
    restaurant: Restaurant, party: Party, guest_fits: list[GuestFit]
) -> list[str]:
    warnings: list[str] = []

    if party.is_large_party:
        warnings.append(
            f"Party of {party.guest_count} - call ahead, seating is not verified."
        )

    for fit in guest_fits:
        limiting = fit.limiting_fit
        if limiting is None or fit.confidence >= 0.45:
            continue
        if limiting.restriction in ALLERGY_RESTRICTIONS:
            warnings.append(
                f"{fit.guest_name}: confirm {limiting.label} handling with the "
                f"kitchen before booking."
            )
        else:
            warnings.append(
                f"{fit.guest_name} may have limited {limiting.label} options."
            )

    if restaurant.rating_count and restaurant.rating_count < 15:
        warnings.append("Few reviews, so the rating is unreliable.")

    return warnings


# Ranks all candidates for a party and returns the best ones, worst dropped.
def rank_restaurants(
    restaurants: list[Restaurant], party: Party, limit: int = 5
) -> tuple[list[ScoredRestaurant], int]:
    scored = [score_restaurant(item, party) for item in restaurants]

    # Disqualify anywhere a guest almost certainly cannot eat.
    eligible = [
        candidate
        for candidate in scored
        if all(fit.confidence >= HARD_FLOOR for fit in candidate.guest_fits)
    ]
    excluded_count = len(scored) - len(eligible)

    # If the filter is too strict to return anything, fall back to the full
    # list rather than showing an empty page, and let warnings do the talking.
    pool = eligible if eligible else scored
    pool.sort(key=lambda candidate: candidate.score, reverse=True)
    return pool[:limit], excluded_count
