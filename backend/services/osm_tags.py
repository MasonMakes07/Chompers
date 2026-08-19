"""Translates OpenStreetMap tags into the vocabulary the scorer already uses.

This module is the bridge that let us swap providers cheaply. OSM describes a
restaurant with `amenity` and `cuisine` tags; `dietary_rules.py` is written
against Google-style place types like `indian_restaurant`. Mapping one to the
other here means the entire 47-cuisine knowledge table, the scorer, and the
frontend keep working untouched.

OSM also has one real advantage over Google: `diet:*` tags are structured,
first-party data covering six of our eight restrictions, where Google exposed
only a single vegetarian boolean. Those become tier-1 EXPLICIT evidence.
"""

from ..models.guest import Restriction

# OSM `amenity` / `shop` value -> our place type.
AMENITY_TO_TYPE: dict[str, str] = {
    "restaurant": "restaurant",
    "fast_food": "fast_food_restaurant",
    "cafe": "cafe",
    "bar": "bar",
    "pub": "pub",
    "ice_cream": "ice_cream_shop",
    "bakery": "bakery",
    "food_court": "buffet_restaurant",
    "biergarten": "pub",
}

# OSM `cuisine` value -> our place type. OSM cuisine is a free-ish list, so
# this covers the common values and anything unmatched falls back to the
# generic amenity type, which the scorer treats as an unknown cuisine.
CUISINE_TO_TYPE: dict[str, str] = {
    # Diet-focused
    "vegan": "vegan_restaurant",
    "vegetarian": "vegetarian_restaurant",
    # South and Southeast Asian
    "indian": "indian_restaurant",
    "pakistani": "indian_restaurant",
    "bangladeshi": "indian_restaurant",
    "nepalese": "indian_restaurant",
    "sri_lankan": "indian_restaurant",
    "thai": "thai_restaurant",
    "vietnamese": "vietnamese_restaurant",
    "indonesian": "indonesian_restaurant",
    "malaysian": "indonesian_restaurant",
    "filipino": "asian_restaurant",
    "asian": "asian_restaurant",
    # East Asian
    "chinese": "chinese_restaurant",
    "cantonese": "cantonese_restaurant",
    "szechuan": "chinese_restaurant",
    "dim_sum": "cantonese_restaurant",
    "japanese": "japanese_restaurant",
    "sushi": "sushi_restaurant",
    "ramen": "ramen_restaurant",
    "noodle": "ramen_restaurant",
    "korean": "korean_restaurant",
    # Mediterranean and Middle Eastern
    "mediterranean": "mediterranean_restaurant",
    "middle_eastern": "middle_eastern_restaurant",
    "arab": "middle_eastern_restaurant",
    "lebanese": "lebanese_restaurant",
    "syrian": "middle_eastern_restaurant",
    "kebab": "turkish_restaurant",
    "turkish": "turkish_restaurant",
    "persian": "middle_eastern_restaurant",
    "afghan": "afghani_restaurant",
    "greek": "greek_restaurant",
    "falafel": "middle_eastern_restaurant",
    # European
    "italian": "italian_restaurant",
    "pizza": "pizza_restaurant",
    "pasta": "italian_restaurant",
    "french": "french_restaurant",
    "crepe": "french_restaurant",
    "spanish": "spanish_restaurant",
    "tapas": "spanish_restaurant",
    "portuguese": "spanish_restaurant",
    "german": "american_restaurant",
    "russian": "american_restaurant",
    # Americas
    "mexican": "mexican_restaurant",
    "tex-mex": "mexican_restaurant",
    "tacos": "mexican_restaurant",
    "brazilian": "brazilian_restaurant",
    "peruvian": "brazilian_restaurant",
    "cuban": "brazilian_restaurant",
    "caribbean": "african_restaurant",
    "american": "american_restaurant",
    "burger": "hamburger_restaurant",
    "steak_house": "steak_house",
    "barbecue": "barbecue_restaurant",
    "bbq": "barbecue_restaurant",
    "chicken": "american_restaurant",
    "wings": "american_restaurant",
    "diner": "diner",
    # African
    "african": "african_restaurant",
    "ethiopian": "african_restaurant",
    "moroccan": "middle_eastern_restaurant",
    # Seafood
    "seafood": "seafood_restaurant",
    "fish": "seafood_restaurant",
    "fish_and_chips": "seafood_restaurant",
    "oyster": "seafood_restaurant",
    # Casual formats
    "sandwich": "sandwich_shop",
    "deli": "deli",
    "coffee_shop": "coffee_shop",
    "cafe": "cafe",
    "bakery": "bakery",
    "breakfast": "breakfast_restaurant",
    "brunch": "brunch_restaurant",
    "ice_cream": "ice_cream_shop",
    "dessert": "dessert_shop",
    "cake": "dessert_shop",
    "donut": "dessert_shop",
    "juice": "juice_shop",
    "smoothie": "juice_shop",
    "salad": "juice_shop",
    "soup": "restaurant",
    "buffet": "buffet_restaurant",
    "fine_dining": "fine_dining_restaurant",
}

# OSM `diet:*` key suffix -> the restriction it speaks to. OSM has no tag for
# nut or shellfish allergy, so those stay on cuisine priors.
DIET_TAG_TO_RESTRICTION: dict[str, Restriction] = {
    "vegetarian": Restriction.VEGETARIAN,
    "vegan": Restriction.VEGAN,
    "gluten_free": Restriction.GLUTEN_FREE,
    "dairy_free": Restriction.DAIRY_FREE,
    "lactose_free": Restriction.DAIRY_FREE,
    "halal": Restriction.HALAL,
    "kosher": Restriction.KOSHER,
}

# Values OSM uses for diet tags, ranked so a stronger claim wins a conflict.
DIET_VALUE_STRENGTH: dict[str, int] = {
    "no": 0,
    "limited": 1,
    "yes": 2,
    "only": 3,
}


# ---------------------------------------------------------------------------


# Splits an OSM multi-value tag such as "italian;pizza" into clean parts.
def split_tag_values(raw_value: str) -> list[str]:
    return [
        part.strip().lower().replace(" ", "_")
        for part in raw_value.split(";")
        if part.strip()
    ]


# Derives our place types from a place's OSM tags, most specific first.
def place_types_from_tags(tags: dict[str, str]) -> list[str]:
    types: list[str] = []

    for cuisine_value in split_tag_values(tags.get("cuisine", "")):
        mapped_type = CUISINE_TO_TYPE.get(cuisine_value)
        if mapped_type is not None and mapped_type not in types:
            types.append(mapped_type)

    # The amenity is the fallback, appended last so cuisine stays primary.
    amenity_type = AMENITY_TO_TYPE.get(
        tags.get("amenity", "") or tags.get("shop", "")
    )
    if amenity_type is not None and amenity_type not in types:
        types.append(amenity_type)

    return types or ["restaurant"]


# Extracts structured diet:* claims, keeping the strongest value per conflict.
def diet_tags_from_tags(tags: dict[str, str]) -> dict[str, str]:
    claims: dict[str, str] = {}

    for tag_key, tag_value in tags.items():
        if not tag_key.startswith("diet:"):
            continue
        restriction = DIET_TAG_TO_RESTRICTION.get(tag_key[len("diet:"):])
        if restriction is None:
            continue

        normalized_value = tag_value.strip().lower()
        if normalized_value not in DIET_VALUE_STRENGTH:
            continue

        existing = claims.get(restriction.value)
        if existing is None or (
            DIET_VALUE_STRENGTH[normalized_value] > DIET_VALUE_STRENGTH[existing]
        ):
            claims[restriction.value] = normalized_value

    # A vegan-only kitchen is vegetarian-only too, even when untagged.
    if claims.get(Restriction.VEGAN.value) in ("yes", "only"):
        claims.setdefault(Restriction.VEGETARIAN.value, "yes")

    return claims


# Assembles a readable street address from the separate OSM addr:* tags.
def address_from_tags(tags: dict[str, str]) -> str:
    street = " ".join(
        part
        for part in (tags.get("addr:housenumber", ""), tags.get("addr:street", ""))
        if part
    ).strip()
    city_parts = [
        tags.get("addr:city", ""),
        tags.get("addr:state", ""),
        tags.get("addr:postcode", ""),
    ]
    city = " ".join(part for part in city_parts if part).strip()

    return ", ".join(part for part in (street, city) if part)
