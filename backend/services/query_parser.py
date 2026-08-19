"""Turns free-text searches into structured SearchIntent.

Three jobs, in order of how much they improve results:

1. Recognize dietary terms. "vegan" must find places tagged `diet:vegan`,
   not just places with "vegan" in the name.
2. Expand cuisine synonyms. "BBQ" and "barbecue" are the same search; so are
   "pho" and Vietnamese. OSM tags one spelling, users type the other.
3. Drop filler. "good cheap restaurants near me" carries one useful word.
   Matching the rest against restaurant names only adds noise.
"""

import re

from ..models.guest import Restriction
from ..models.search_intent import SearchIntent
from .osm_tags import CUISINE_TO_TYPE

# Multi-word diet phrases, checked before single tokens so "gluten free"
# is never split into two meaningless keywords.
DIET_PHRASES: dict[str, Restriction] = {
    "gluten free": Restriction.GLUTEN_FREE,
    "dairy free": Restriction.DAIRY_FREE,
    "lactose free": Restriction.DAIRY_FREE,
    "nut free": Restriction.NUT_ALLERGY,
    "shellfish free": Restriction.SHELLFISH_ALLERGY,
    "plant based": Restriction.VEGAN,
}

# Single words naming a dietary need.
DIET_TERMS: dict[str, Restriction] = {
    "vegan": Restriction.VEGAN,
    "vegetarian": Restriction.VEGETARIAN,
    "veggie": Restriction.VEGETARIAN,
    "glutenfree": Restriction.GLUTEN_FREE,
    "gf": Restriction.GLUTEN_FREE,
    "halal": Restriction.HALAL,
    "kosher": Restriction.KOSHER,
}

# A diet term is also a cuisine hint: searching "vegan" should surface
# vegan_restaurant places even when no diet tag was recorded.
DIET_CUISINE_HINTS: dict[Restriction, set[str]] = {
    Restriction.VEGAN: {"vegan"},
    Restriction.VEGETARIAN: {"vegetarian", "vegan"},
    Restriction.HALAL: {"kebab", "turkish", "middle_eastern", "afghan"},
    Restriction.KOSHER: {"deli"},
}

# Multi-word cuisine phrases, checked before single tokens.
CUISINE_PHRASES: dict[str, set[str]] = {
    "ice cream": {"ice_cream"},
    "fine dining": {"fine_dining"},
    "middle eastern": {"middle_eastern", "lebanese"},
    "fried chicken": {"chicken"},
    "fish and chips": {"fish_and_chips", "seafood"},
    "dim sum": {"dim_sum", "cantonese", "chinese"},
    "hot pot": {"chinese"},
    "food truck": {"burger", "tacos"},
}

# Single-word cuisine synonyms mapped to OSM `cuisine` tag values.
CUISINE_TERMS: dict[str, set[str]] = {
    # East and Southeast Asian
    "sushi": {"sushi", "japanese"},
    "japanese": {"japanese", "sushi"},
    "ramen": {"ramen", "noodle", "japanese"},
    "noodle": {"noodle", "ramen", "asian"},
    "noodles": {"noodle", "ramen", "asian"},
    "chinese": {"chinese", "cantonese"},
    "thai": {"thai"},
    "korean": {"korean"},
    "vietnamese": {"vietnamese"},
    "pho": {"vietnamese"},
    "asian": {"asian"},
    "indian": {"indian"},
    "curry": {"indian", "thai"},
    # Latin American
    "mexican": {"mexican", "tacos"},
    "taco": {"tacos", "mexican"},
    "tacos": {"tacos", "mexican"},
    "burrito": {"mexican"},
    "burritos": {"mexican"},
    "brazilian": {"brazilian"},
    "peruvian": {"peruvian"},
    "caribbean": {"caribbean"},
    # European
    "italian": {"italian", "pizza", "pasta"},
    "pizza": {"pizza", "italian"},
    "pasta": {"pasta", "italian"},
    "french": {"french"},
    "spanish": {"spanish", "tapas"},
    "tapas": {"tapas", "spanish"},
    "greek": {"greek"},
    "mediterranean": {"mediterranean", "greek"},
    # Middle Eastern
    "lebanese": {"lebanese", "middle_eastern"},
    "falafel": {"falafel", "middle_eastern"},
    "shawarma": {"kebab", "middle_eastern"},
    "kebab": {"kebab", "turkish"},
    "turkish": {"turkish", "kebab"},
    # American
    "american": {"american"},
    "burger": {"burger", "american"},
    "burgers": {"burger", "american"},
    "bbq": {"barbecue", "bbq"},
    "barbecue": {"barbecue", "bbq"},
    "steak": {"steak_house"},
    "steakhouse": {"steak_house"},
    "wings": {"wings", "chicken"},
    "chicken": {"chicken"},
    "diner": {"diner"},
    "sandwich": {"sandwich", "deli"},
    "sandwiches": {"sandwich", "deli"},
    "sub": {"sandwich"},
    "subs": {"sandwich"},
    "deli": {"deli", "sandwich"},
    # Seafood
    "seafood": {"seafood", "fish"},
    "fish": {"fish", "seafood"},
    "oysters": {"oyster", "seafood"},
    # African
    "african": {"african"},
    "ethiopian": {"ethiopian", "african"},
    "moroccan": {"moroccan"},
    # Cafe, bakery, sweets
    "coffee": {"coffee_shop", "cafe"},
    "cafe": {"cafe", "coffee_shop"},
    "bakery": {"bakery"},
    "pastry": {"bakery"},
    "breakfast": {"breakfast"},
    "brunch": {"brunch", "breakfast"},
    "dessert": {"dessert", "cake"},
    "desserts": {"dessert", "cake"},
    "donut": {"donut"},
    "donuts": {"donut"},
    "juice": {"juice"},
    "smoothie": {"juice", "smoothie"},
    "smoothies": {"juice", "smoothie"},
    "salad": {"salad"},
    "salads": {"salad"},
    "soup": {"soup"},
    "buffet": {"buffet"},
}

# Filler that would only add noise if matched against restaurant names.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "any", "are", "around", "at", "best", "by", "cheap",
        "close", "dinner", "eat", "food", "for", "get", "good", "great", "here",
        "in", "is", "lunch", "me", "my", "near", "nearby", "nice", "now", "of",
        "on", "open", "or", "place", "places", "restaurant", "restaurants",
        "some", "spot", "spots", "the", "to", "tonight", "top", "want", "with",
    }
)

# Keeping a few words is enough to find a name; more just widens the net.
MAX_KEYWORDS = 3


# ---------------------------------------------------------------------------


# Reduces raw input to lowercase word tokens, discarding punctuation.
def _tokenize(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


# Parses free text into the diets, cuisines, and keywords it refers to.
def parse_query(text: str) -> SearchIntent:
    tokens = _tokenize(text)
    if not tokens:
        return SearchIntent(raw=text.strip())

    diets: set[Restriction] = set()
    cuisines: set[str] = set()
    keywords: list[str] = []

    index = 0
    while index < len(tokens):
        # Two-word phrases win over single tokens, so "gluten free" is not
        # read as the unrelated words "gluten" and "free".
        pair = " ".join(tokens[index : index + 2]) if index + 1 < len(tokens) else ""

        if pair and pair in DIET_PHRASES:
            diets.add(DIET_PHRASES[pair])
            index += 2
            continue
        if pair and pair in CUISINE_PHRASES:
            cuisines |= CUISINE_PHRASES[pair]
            index += 2
            continue

        token = tokens[index]
        if token in DIET_TERMS:
            diets.add(DIET_TERMS[token])
        elif token in CUISINE_TERMS:
            cuisines |= CUISINE_TERMS[token]
        elif token not in STOPWORDS and len(token) > 1:
            keywords.append(token)
        index += 1

    # A named diet also hints at cuisines that specialize in it.
    for diet in diets:
        cuisines |= DIET_CUISINE_HINTS.get(diet, set())

    place_types = {
        CUISINE_TO_TYPE[cuisine]
        for cuisine in cuisines
        if cuisine in CUISINE_TO_TYPE
    }

    return SearchIntent(
        raw=text.strip(),
        diets=frozenset(diets),
        cuisines=frozenset(cuisines),
        place_types=frozenset(place_types),
        keywords=tuple(keywords[:MAX_KEYWORDS]),
    )
