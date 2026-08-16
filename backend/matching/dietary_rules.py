"""Dietary knowledge base: how well a cuisine accommodates each restriction.

Every value is a confidence in [0, 1] that a guest with that restriction can
get a real meal at a restaurant of that type. These are informed priors, not
verified facts, and the scorer labels them as inferences in the UI.

Two ideas drive the numbers:

1. Diets and allergies are different problems. A diet asks "is there something
   on the menu for me"; an allergy asks "will this kitchen make me sick". So
   Thai scores high for vegetarian but LOW for nut allergy (peanut-heavy
   kitchen, cross-contamination), and buffets score low for every allergy
   regardless of menu breadth because of shared serving utensils.

2. Absence of evidence is not evidence. Unknown cuisines get a neutral 0.5,
   except halal and kosher which get a low prior - those require active
   certification, so they must never be assumed from silence.
"""

from ..models.guest import Restriction

# Column order for every row in CUISINE_PRIORS below.
RESTRICTION_ORDER = (
    Restriction.VEGETARIAN,
    Restriction.VEGAN,
    Restriction.GLUTEN_FREE,
    Restriction.DAIRY_FREE,
    Restriction.NUT_ALLERGY,
    Restriction.SHELLFISH_ALLERGY,
    Restriction.HALAL,
    Restriction.KOSHER,
)

# Neutral prior for an unrecognized cuisine. Halal and kosher stay low because
# they require certification and cannot be inferred from an unknown type.
DEFAULT_PRIOR = (0.50, 0.35, 0.45, 0.45, 0.60, 0.65, 0.15, 0.08)

# Google Places type -> confidence per restriction, in RESTRICTION_ORDER:
#     veg   vegan  gf     dairy  nut    shell  halal  kosher
CUISINE_PRIORS: dict[str, tuple[float, ...]] = {
    # --- Explicitly diet-focused venues -----------------------------------
    "vegan_restaurant":
        (1.00, 1.00, 0.75, 1.00, 0.35, 1.00, 0.75, 0.35),
    "vegetarian_restaurant":
        (1.00, 0.80, 0.70, 0.50, 0.40, 1.00, 0.65, 0.30),

    # --- South and Southeast Asian ----------------------------------------
    # Indian: outstanding for vegetarians, poor for dairy (ghee, paneer,
    # cream) and poor for nut allergies (cashew-thickened gravies).
    "indian_restaurant":
        (0.95, 0.80, 0.60, 0.30, 0.30, 0.85, 0.55, 0.10),
    # Thai: coconut milk instead of dairy, but peanuts and shrimp paste are
    # near-universal, so both allergies score badly.
    "thai_restaurant":
        (0.85, 0.75, 0.75, 0.85, 0.20, 0.35, 0.20, 0.05),
    "vietnamese_restaurant":
        (0.65, 0.55, 0.70, 0.85, 0.25, 0.35, 0.15, 0.05),
    # Indonesian: satay and peanut sauce make this the worst nut-allergy case.
    "indonesian_restaurant":
        (0.60, 0.50, 0.60, 0.85, 0.15, 0.35, 0.65, 0.05),
    "asian_restaurant":
        (0.60, 0.45, 0.40, 0.80, 0.35, 0.40, 0.15, 0.05),

    # --- East Asian --------------------------------------------------------
    # Chinese: soy sauce sinks gluten-free; oyster sauce sinks shellfish.
    "chinese_restaurant":
        (0.65, 0.50, 0.30, 0.85, 0.30, 0.35, 0.15, 0.05),
    "cantonese_restaurant":
        (0.60, 0.45, 0.30, 0.85, 0.35, 0.30, 0.10, 0.05),
    "japanese_restaurant":
        (0.45, 0.30, 0.35, 0.85, 0.70, 0.40, 0.15, 0.05),
    "sushi_restaurant":
        (0.40, 0.30, 0.40, 0.85, 0.75, 0.25, 0.15, 0.05),
    "ramen_restaurant":
        (0.30, 0.20, 0.20, 0.80, 0.70, 0.40, 0.08, 0.03),
    "korean_restaurant":
        (0.45, 0.30, 0.40, 0.80, 0.60, 0.35, 0.10, 0.05),

    # --- Mediterranean and Middle Eastern ---------------------------------
    "mediterranean_restaurant":
        (0.85, 0.70, 0.60, 0.50, 0.45, 0.75, 0.55, 0.25),
    "middle_eastern_restaurant":
        (0.85, 0.70, 0.55, 0.50, 0.40, 0.85, 0.80, 0.20),
    "lebanese_restaurant":
        (0.85, 0.70, 0.55, 0.50, 0.40, 0.85, 0.75, 0.20),
    "turkish_restaurant":
        (0.70, 0.55, 0.50, 0.45, 0.45, 0.85, 0.75, 0.15),
    "afghani_restaurant":
        (0.65, 0.50, 0.45, 0.45, 0.35, 0.90, 0.85, 0.10),
    "greek_restaurant":
        (0.75, 0.55, 0.55, 0.35, 0.65, 0.65, 0.30, 0.10),

    # --- European ----------------------------------------------------------
    "italian_restaurant":
        (0.70, 0.35, 0.45, 0.25, 0.60, 0.55, 0.15, 0.05),
    "pizza_restaurant":
        (0.75, 0.30, 0.55, 0.20, 0.80, 0.85, 0.20, 0.10),
    # French: butter and cream in nearly everything.
    "french_restaurant":
        (0.35, 0.15, 0.35, 0.15, 0.55, 0.40, 0.08, 0.05),
    "spanish_restaurant":
        (0.50, 0.30, 0.55, 0.55, 0.50, 0.30, 0.10, 0.05),

    # --- Americas ----------------------------------------------------------
    "mexican_restaurant":
        (0.70, 0.55, 0.70, 0.40, 0.75, 0.70, 0.15, 0.05),
    "brazilian_restaurant":
        (0.30, 0.15, 0.60, 0.55, 0.75, 0.65, 0.10, 0.05),
    "american_restaurant":
        (0.50, 0.30, 0.55, 0.45, 0.75, 0.65, 0.10, 0.05),
    "steak_house":
        (0.15, 0.05, 0.70, 0.45, 0.80, 0.55, 0.08, 0.05),
    "barbecue_restaurant":
        (0.20, 0.10, 0.55, 0.50, 0.80, 0.80, 0.08, 0.03),
    "hamburger_restaurant":
        (0.45, 0.30, 0.40, 0.40, 0.80, 0.85, 0.12, 0.05),
    "diner":
        (0.45, 0.20, 0.35, 0.35, 0.75, 0.80, 0.08, 0.05),
    "seafood_restaurant":
        (0.20, 0.10, 0.55, 0.55, 0.75, 0.15, 0.25, 0.10),
    "african_restaurant":
        (0.70, 0.60, 0.60, 0.65, 0.40, 0.80, 0.50, 0.10),

    # --- Casual, cafe, and other formats ----------------------------------
    "fast_food_restaurant":
        (0.40, 0.25, 0.30, 0.35, 0.65, 0.85, 0.10, 0.05),
    "sandwich_shop":
        (0.55, 0.30, 0.40, 0.40, 0.70, 0.85, 0.15, 0.15),
    "deli":
        (0.55, 0.30, 0.40, 0.40, 0.70, 0.85, 0.15, 0.20),
    "cafe":
        (0.75, 0.55, 0.45, 0.70, 0.45, 0.90, 0.40, 0.20),
    "coffee_shop":
        (0.75, 0.55, 0.45, 0.70, 0.45, 0.90, 0.40, 0.20),
    "breakfast_restaurant":
        (0.65, 0.30, 0.40, 0.30, 0.70, 0.90, 0.15, 0.05),
    "brunch_restaurant":
        (0.65, 0.35, 0.45, 0.35, 0.70, 0.85, 0.15, 0.05),
    "bakery":
        (0.80, 0.35, 0.25, 0.20, 0.35, 0.95, 0.35, 0.20),
    "juice_shop":
        (0.90, 0.80, 0.80, 0.75, 0.40, 0.95, 0.60, 0.35),
    "ice_cream_shop":
        (0.85, 0.30, 0.35, 0.15, 0.30, 0.95, 0.40, 0.20),
    "dessert_shop":
        (0.85, 0.30, 0.35, 0.15, 0.30, 0.95, 0.40, 0.20),
    # Buffets: broad menus, but shared utensils make every allergy riskier.
    "buffet_restaurant":
        (0.70, 0.45, 0.50, 0.50, 0.30, 0.35, 0.15, 0.05),
    # Fine dining kitchens accommodate on request more reliably than most.
    "fine_dining_restaurant":
        (0.60, 0.45, 0.70, 0.60, 0.70, 0.55, 0.15, 0.08),
    "bar":
        (0.40, 0.20, 0.40, 0.40, 0.70, 0.65, 0.05, 0.03),
    "pub":
        (0.40, 0.20, 0.40, 0.40, 0.70, 0.65, 0.05, 0.03),
}

# Name keywords that are far stronger evidence than any cuisine prior. Each
# maps to the restrictions it confirms and the confidence it grants.
NAME_KEYWORDS: tuple[tuple[str, dict[Restriction, float], str], ...] = (
    ("vegan", {Restriction.VEGAN: 0.95, Restriction.VEGETARIAN: 0.98,
               Restriction.DAIRY_FREE: 0.95}, "'vegan' in the name"),
    ("plant based", {Restriction.VEGAN: 0.92, Restriction.VEGETARIAN: 0.96,
                     Restriction.DAIRY_FREE: 0.90}, "'plant based' in the name"),
    ("plant-based", {Restriction.VEGAN: 0.92, Restriction.VEGETARIAN: 0.96,
                     Restriction.DAIRY_FREE: 0.90}, "'plant-based' in the name"),
    ("vegetarian", {Restriction.VEGETARIAN: 0.95}, "'vegetarian' in the name"),
    ("halal", {Restriction.HALAL: 0.95}, "'halal' in the name"),
    ("kosher", {Restriction.KOSHER: 0.95}, "'kosher' in the name"),
    ("gluten free", {Restriction.GLUTEN_FREE: 0.90}, "'gluten free' in the name"),
    ("gluten-free", {Restriction.GLUTEN_FREE: 0.90}, "'gluten-free' in the name"),
)


# ---------------------------------------------------------------------------
# Table integrity
# ---------------------------------------------------------------------------


# Verifies every prior row has one value per restriction, all within [0, 1].
def _validate_table() -> None:
    expected_width = len(RESTRICTION_ORDER)
    rows = [("DEFAULT_PRIOR", DEFAULT_PRIOR), *CUISINE_PRIORS.items()]
    for cuisine_name, row in rows:
        if len(row) != expected_width:
            raise ValueError(
                f"{cuisine_name} has {len(row)} priors, expected {expected_width}"
            )
        if any(not 0.0 <= value <= 1.0 for value in row):
            raise ValueError(f"{cuisine_name} has a prior outside [0, 1]")


_validate_table()

# Pre-zipped lookup so scoring never rebuilds dicts inside its hot loop.
_PRIOR_LOOKUP: dict[str, dict[Restriction, float]] = {
    cuisine_name: dict(zip(RESTRICTION_ORDER, row))
    for cuisine_name, row in CUISINE_PRIORS.items()
}
_DEFAULT_LOOKUP: dict[Restriction, float] = dict(
    zip(RESTRICTION_ORDER, DEFAULT_PRIOR)
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


# Returns the cuisine prior for one restriction, or None if type is unknown.
def cuisine_prior(place_type: str, restriction: Restriction) -> float | None:
    priors = _PRIOR_LOOKUP.get(place_type)
    return None if priors is None else priors.get(restriction)


# Returns the neutral fallback confidence for an unrecognized restaurant type.
def default_prior(restriction: Restriction) -> float:
    return _DEFAULT_LOOKUP.get(restriction, 0.5)


# Finds name-keyword evidence, returning (confidence, reason) if any matches.
def keyword_evidence(
    searchable_name: str, restriction: Restriction
) -> tuple[float, str] | None:
    best_match: tuple[float, str] | None = None
    for keyword, granted, reason in NAME_KEYWORDS:
        if keyword in searchable_name and restriction in granted:
            confidence = granted[restriction]
            if best_match is None or confidence > best_match[0]:
                best_match = (confidence, reason)
    return best_match


# Reports whether a Google place type is described in the knowledge table.
def is_known_cuisine(place_type: str) -> bool:
    return place_type in _PRIOR_LOOKUP
