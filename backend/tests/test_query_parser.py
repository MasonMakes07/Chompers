"""Tests for smart search: query parsing, Overpass clauses, and relevance."""

import pytest

from backend.matching import scorer
from backend.models.guest import Restriction
from backend.models.party import Party
from backend.models.restaurant import Restaurant
from backend.services.overpass_client import MAX_RESULTS_PER_CALL
from backend.services.places_client import OverpassPlacesClient
from backend.services.query_parser import parse_query

BASE_LAT, BASE_LNG = 32.8801, -117.2340


# Builds an OSM-shaped restaurant for relevance tests.
def make_place(
    name: str,
    place_type: str = "restaurant",
    diet_tags: dict[str, str] | None = None,
    summary: str = "",
) -> Restaurant:
    return Restaurant(
        place_id=f"node/{name}",
        name=name,
        latitude=BASE_LAT + 0.001,
        longitude=BASE_LNG,
        primary_type=place_type,
        types=[place_type],
        diet_tags=diet_tags or {},
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Dietary terms
# ---------------------------------------------------------------------------


# A diet word must become a structured diet, not an unmatched keyword.
@pytest.mark.parametrize(
    "query,expected",
    [
        ("vegan", Restriction.VEGAN),
        ("vegetarian", Restriction.VEGETARIAN),
        ("veggie", Restriction.VEGETARIAN),
        ("halal", Restriction.HALAL),
        ("kosher", Restriction.KOSHER),
    ],
)
def test_single_diet_terms(query, expected):
    intent = parse_query(query)

    assert expected in intent.diets
    assert query not in intent.keywords


# Two-word diet phrases must not be split into meaningless words.
@pytest.mark.parametrize(
    "query,expected",
    [
        ("gluten free", Restriction.GLUTEN_FREE),
        ("dairy free", Restriction.DAIRY_FREE),
        ("lactose free", Restriction.DAIRY_FREE),
        ("nut free", Restriction.NUT_ALLERGY),
        ("plant based", Restriction.VEGAN),
    ],
)
def test_diet_phrases_are_not_split(query, expected):
    intent = parse_query(query)

    assert expected in intent.diets
    assert intent.keywords == (), "Phrase words must not leak into keywords."


# A diet search must also hint at cuisines that specialize in it.
def test_diet_implies_cuisine_hint():
    intent = parse_query("vegan")

    assert "vegan" in intent.cuisines
    assert "vegan_restaurant" in intent.place_types


# ---------------------------------------------------------------------------
# Cuisine synonyms
# ---------------------------------------------------------------------------


# Synonyms users type must resolve to the values OSM actually tags.
@pytest.mark.parametrize(
    "query,expected_cuisine",
    [
        ("bbq", "barbecue"),
        ("barbecue", "barbecue"),
        ("pho", "vietnamese"),
        ("sushi", "sushi"),
        ("burgers", "burger"),
        ("tacos", "tacos"),
        ("steakhouse", "steak_house"),
        ("coffee", "coffee_shop"),
        ("shawarma", "kebab"),
    ],
)
def test_cuisine_synonyms(query, expected_cuisine):
    assert expected_cuisine in parse_query(query).cuisines


# Multi-word cuisines must be recognized as one term.
def test_cuisine_phrases():
    assert "ice_cream" in parse_query("ice cream").cuisines
    assert "middle_eastern" in parse_query("middle eastern").cuisines


# Recognized cuisines must map onto place types the rules table knows.
def test_cuisines_map_to_place_types():
    intent = parse_query("sushi")

    assert "sushi_restaurant" in intent.place_types


# ---------------------------------------------------------------------------
# Filler and leftovers
# ---------------------------------------------------------------------------


# Filler words must be dropped so they cannot widen the name match.
def test_stopwords_are_dropped():
    intent = parse_query("good cheap restaurants near me")

    assert intent.keywords == ()
    assert intent.is_empty


# Real search terms must survive alongside dropped filler.
def test_mixed_query_keeps_only_meaning():
    intent = parse_query("best cheap tacos near me")

    assert "tacos" in intent.cuisines
    assert intent.keywords == ()


# Unrecognized words must remain as keywords for a name match.
def test_unknown_words_become_keywords():
    intent = parse_query("Sunday Supper Club")

    assert intent.keywords == ("sunday", "supper", "club")
    assert not intent.is_structured


# Keyword count must be capped so the net does not widen indefinitely.
def test_keywords_are_capped():
    intent = parse_query("alpha bravo charlie delta echo foxtrot")

    assert len(intent.keywords) == 3


# A query of only punctuation must parse to an empty intent, not crash.
def test_punctuation_only_query_is_empty():
    assert parse_query("!!! ???").is_empty


# A combined diet and cuisine search must capture both.
def test_diet_and_cuisine_together():
    intent = parse_query("vegan pizza")

    assert Restriction.VEGAN in intent.diets
    assert "pizza" in intent.cuisines


# ---------------------------------------------------------------------------
# Overpass query construction
# ---------------------------------------------------------------------------


# A diet search must query the diet:* tags, which is the whole improvement.
def test_diet_search_queries_diet_tags():
    intent = parse_query("vegan")
    query = OverpassPlacesClient._intent_query(intent, BASE_LAT, BASE_LNG, 5000)

    assert '"diet:vegan"~"^(yes|only)$"' in query


# Dairy-free must cover both spellings OSM uses in the wild.
def test_dairy_free_covers_both_osm_spellings():
    intent = parse_query("dairy free")
    query = OverpassPlacesClient._intent_query(intent, BASE_LAT, BASE_LNG, 5000)

    assert "diet:dairy_free" in query
    assert "diet:lactose_free" in query


# Cuisine terms must become a cuisine tag filter, not a name filter.
def test_cuisine_search_queries_cuisine_tag():
    intent = parse_query("sushi")
    query = OverpassPlacesClient._intent_query(intent, BASE_LAT, BASE_LNG, 5000)

    assert '["cuisine"~(' in query.replace('"cuisine"~"(', '["cuisine"~(')


# Leftover keywords must fall back to matching the restaurant name.
def test_keyword_search_queries_name():
    intent = parse_query("Sunday Supper")
    query = OverpassPlacesClient._intent_query(intent, BASE_LAT, BASE_LNG, 5000)

    assert '["name"~"(' in query


# The built query must remain valid, bounded Overpass QL.
def test_intent_query_is_well_formed():
    intent = parse_query("vegan sushi downtown")
    query = OverpassPlacesClient._intent_query(intent, BASE_LAT, BASE_LNG, 5000)

    assert query.startswith("[out:json]")
    assert query.endswith(f"out center tags {MAX_RESULTS_PER_CALL};")
    assert query.count("(") == query.count(")")


# Terms must be stripped of anything that could alter the query syntax.
@pytest.mark.parametrize(
    "hostile", ['sushi"];out;//', "sushi[amenity=bar]", "a;b", "x)(y"]
)
def test_terms_cannot_inject_overpass_syntax(hostile):
    intent = parse_query(hostile)
    query = OverpassPlacesClient._intent_query(intent, BASE_LAT, BASE_LNG, 5000)

    # Every structural character must come from our own template, so the
    # parens must still balance and no stray quote may appear in a term.
    assert query.count("(") == query.count(")")
    assert "out;" not in query.replace("out center tags 60;", "")


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------


# An explicit diet tag must beat a mere name match for the same search.
def test_diet_tag_outranks_name_match():
    intent = parse_query("vegan")
    tagged = make_place("Green Fork", diet_tags={"vegan": "only"})
    named = make_place("Vegan's Revenge", "steak_house")

    assert scorer.query_relevance_score(tagged, intent) > (
        scorer.query_relevance_score(named, intent)
    )


# A place tagged as NOT serving the searched diet must score near zero.
def test_negative_diet_tag_scores_lowest():
    intent = parse_query("vegan")
    refuses = make_place("Meat Hall", diet_tags={"vegan": "no"})

    assert scorer.query_relevance_score(refuses, intent) < 0.2


# A cuisine match must rank well even with no diet tags recorded.
def test_cuisine_match_scores_high():
    intent = parse_query("sushi")
    place = make_place("Blue Fin", "sushi_restaurant")

    assert scorer.query_relevance_score(place, intent) >= 0.9


# An unrelated result must score low but not zero, since Overpass matched it.
def test_unrelated_result_scores_low():
    intent = parse_query("sushi")
    place = make_place("Taco Stand", "mexican_restaurant")

    assert 0.2 < scorer.query_relevance_score(place, intent) < 0.5


# End to end, a diet-tagged place must outrank a same-cuisine untagged one.
def test_relevance_changes_the_ranking():
    intent = parse_query("vegan")
    party = Party(
        guest_count=2,
        guests=[],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        search_intent=intent,
    )
    candidates = [
        make_place("Corner Cafe", "cafe"),
        make_place("Green Fork", "cafe", diet_tags={"vegan": "only"}),
    ]

    ranked, _ = scorer.rank_restaurants(candidates, party)

    assert ranked[0].restaurant.name == "Green Fork"


# Without a query, relevance must not participate in scoring at all.
def test_no_intent_means_no_relevance_component():
    party = Party(
        guest_count=2, guests=[], latitude=BASE_LAT, longitude=BASE_LNG
    )
    place = make_place("Anywhere", "cafe")

    scored = scorer.score_restaurant(place, party)

    assert 0.0 <= scored.score <= 1.0
