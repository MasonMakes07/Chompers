"""Tests for the OpenStreetMap provider layer: tag mapping and query safety."""

import pytest

from backend.matching import scorer
from backend.models.guest import Guest, Restriction
from backend.models.party import Party
from backend.models.restaurant import Restaurant
from backend.services import osm_tags
from backend.services.geocoder import Geocoder
from backend.services.places_client import PlacesClient

BASE_LAT, BASE_LNG = 32.8801, -117.2340


# ---------------------------------------------------------------------------
# Cuisine mapping - the bridge that keeps dietary_rules.py working
# ---------------------------------------------------------------------------


# OSM cuisine values must map onto the place types the rules table knows.
@pytest.mark.parametrize(
    "cuisine,expected_type",
    [
        ("indian", "indian_restaurant"),
        ("thai", "thai_restaurant"),
        ("pizza", "pizza_restaurant"),
        ("burger", "hamburger_restaurant"),
        ("kebab", "turkish_restaurant"),
        ("sushi", "sushi_restaurant"),
        ("vegan", "vegan_restaurant"),
        ("steak_house", "steak_house"),
    ],
)
def test_cuisine_maps_to_known_place_type(cuisine, expected_type):
    types = osm_tags.place_types_from_tags(
        {"amenity": "restaurant", "cuisine": cuisine}
    )

    assert expected_type in types


# Every mapped type must actually exist in the dietary knowledge table.
def test_every_mapped_type_is_known_to_the_rules_table():
    from backend.matching import dietary_rules

    unknown = {
        place_type
        for place_type in osm_tags.CUISINE_TO_TYPE.values()
        if not dietary_rules.is_known_cuisine(place_type)
        and place_type != "restaurant"
    }

    assert unknown == set(), f"Unmapped types would silently score neutral: {unknown}"


# Semicolon-separated cuisines must all be considered, cuisine before amenity.
def test_multi_value_cuisine_is_split():
    types = osm_tags.place_types_from_tags(
        {"amenity": "restaurant", "cuisine": "italian;pizza"}
    )

    assert types[:2] == ["italian_restaurant", "pizza_restaurant"]


# An unmappable cuisine must fall back to the amenity, never crash.
def test_unknown_cuisine_falls_back_to_amenity():
    types = osm_tags.place_types_from_tags(
        {"amenity": "cafe", "cuisine": "moon_rocks"}
    )

    assert types == ["cafe"]


# A place with no usable tags at all must still produce a generic type.
def test_no_tags_yields_generic_type():
    assert osm_tags.place_types_from_tags({}) == ["restaurant"]


# ---------------------------------------------------------------------------
# Diet tags - OSM's real advantage over the Google provider
# ---------------------------------------------------------------------------


# Structured diet:* tags must be read into the restriction vocabulary.
def test_diet_tags_are_extracted():
    claims = osm_tags.diet_tags_from_tags(
        {
            "diet:vegan": "only",
            "diet:gluten_free": "yes",
            "diet:halal": "no",
        }
    )

    assert claims["vegan"] == "only"
    assert claims["gluten_free"] == "yes"
    assert claims["halal"] == "no"


# A vegan kitchen is vegetarian too, even when nobody tagged it that way.
def test_vegan_implies_vegetarian_claim():
    claims = osm_tags.diet_tags_from_tags({"diet:vegan": "only"})

    assert claims["vegetarian"] == "yes"


# lactose_free must feed dairy_free, since OSM uses both spellings.
def test_lactose_free_maps_to_dairy_free():
    claims = osm_tags.diet_tags_from_tags({"diet:lactose_free": "yes"})

    assert claims["dairy_free"] == "yes"


# Conflicting tags for one restriction must resolve to the strongest claim.
def test_conflicting_diet_values_take_the_strongest():
    claims = osm_tags.diet_tags_from_tags(
        {"diet:dairy_free": "no", "diet:lactose_free": "only"}
    )

    assert claims["dairy_free"] == "only"


# Junk diet values must be ignored rather than trusted.
def test_unknown_diet_values_are_ignored():
    assert osm_tags.diet_tags_from_tags({"diet:vegan": "maybe"}) == {}


# An explicit OSM tag must outrank the cuisine prior for the same restriction.
def test_explicit_diet_tag_beats_cuisine_prior():
    steakhouse = Restaurant(
        place_id="node/1",
        name="Chophouse",
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        types=["steak_house"],
        diet_tags={"vegan": "yes"},
    )

    fit = scorer.restriction_confidence(steakhouse, Restriction.VEGAN)

    assert fit.evidence is scorer.Evidence.EXPLICIT
    assert fit.confidence > 0.85


# A "no" tag must be trusted and sink the restaurant for that guest.
def test_negative_diet_tag_disqualifies():
    place = Restaurant(
        place_id="node/2",
        name="Meat Hall",
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        types=["indian_restaurant"],
        diet_tags={"vegetarian": "no"},
    )
    party = Party(
        guest_count=1,
        guests=[Guest("Maya", {Restriction.VEGETARIAN})],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
    )

    ranked, excluded = scorer.rank_restaurants([place], party)

    assert excluded == 1
    assert ranked[0].warnings


# ---------------------------------------------------------------------------
# Overpass query safety
# ---------------------------------------------------------------------------


# Term escaping must strip everything that could break out of the query.
@pytest.mark.parametrize(
    "hostile",
    [
        'sushi"];out;//',
        "sushi\\",
        "out count;",
        "sushi[amenity=bar]",
        "(.a;.b;)",
    ],
)
def test_escaped_term_contains_no_overpass_syntax(hostile):
    term = PlacesClient._escape_term(hostile)

    for dangerous in ('"', "\\", "[", "]", "(", ")", ";", "/", " "):
        assert dangerous not in term


# Ordinary cuisine values must survive escaping untouched.
def test_escaped_term_keeps_valid_cuisine_values():
    assert PlacesClient._escape_term("steak_house") == "steak_house"
    assert PlacesClient._escape_term("ice_cream") == "ice_cream"


# A term of pure punctuation must escape to nothing, not to broken syntax.
def test_escaped_punctuation_only_term_is_empty():
    assert PlacesClient._escape_term("!!!???") == ""


# The generated nearby query must be valid Overpass QL with bounded output.
def test_nearby_query_is_bounded():
    query = PlacesClient._nearby_query(BASE_LAT, BASE_LNG, 5000)

    assert query.startswith("[out:json]")
    assert f"around:5000,{BASE_LAT},{BASE_LNG}" in query
    assert query.rstrip().endswith(";")


# ---------------------------------------------------------------------------
# Reverse geocoding labels
# ---------------------------------------------------------------------------


# A full address must render as neighborhood, city, state.
def test_reverse_label_prefers_neighborhood_city_state():
    label = Geocoder._label_from_address(
        {
            "neighbourhood": "La Jolla",
            "city": "San Diego",
            "ISO3166-2-lvl4": "US-CA",
        },
        "",
    )

    assert label == "La Jolla, San Diego, CA"


# A missing neighborhood must simply drop that line, not leave a gap.
def test_reverse_label_without_neighborhood():
    label = Geocoder._label_from_address(
        {"city": "Portland", "ISO3166-2-lvl4": "US-OR"}, ""
    )

    assert label == "Portland, OR"


# Towns and villages must stand in when there is no city key.
def test_reverse_label_falls_back_through_city_keys():
    label = Geocoder._label_from_address(
        {"village": "Cambria", "ISO3166-2-lvl4": "US-CA"}, ""
    )

    assert label == "Cambria, CA"


# A duplicated name must not be repeated in the label.
def test_reverse_label_deduplicates_parts():
    label = Geocoder._label_from_address(
        {"neighbourhood": "Brooklyn", "city": "Brooklyn", "state": "New York"}, ""
    )

    assert label == "Brooklyn, New York"


# Outside the US there is no ISO subdivision code, so use the state name.
def test_reverse_label_uses_state_name_without_iso_code():
    label = Geocoder._label_from_address(
        {"city": "Kyoto", "state": "Kyoto Prefecture"}, ""
    )

    assert label == "Kyoto, Kyoto Prefecture"


# An address with nothing usable must fall back to the display name.
def test_reverse_label_falls_back_to_display_name():
    label = Geocoder._label_from_address(
        {}, "Some Road, Some County, Some Region, 12345, Country"
    )

    assert label != ""
    assert "Some Road" in label


# With no address and no display name at all, the label must still be safe.
def test_reverse_label_never_returns_empty():
    assert Geocoder._label_from_address({}, "") == "your location"


# ---------------------------------------------------------------------------
# Ranking without ratings
# ---------------------------------------------------------------------------


# Builds an OSM-shaped restaurant, which never has a rating or price.
def make_osm_restaurant(name: str, place_type: str, lat_offset: float = 0.001):
    return Restaurant(
        place_id=f"node/{name}",
        name=name,
        latitude=BASE_LAT + lat_offset,
        longitude=BASE_LNG,
        primary_type=place_type,
        types=[place_type],
        rating=None,
        rating_count=0,
        price_level=None,
    )


# Ranking must still work end to end when no candidate has a rating.
def test_ranking_works_without_any_ratings():
    party = Party(
        guest_count=5,
        guests=[Guest("Maya", {Restriction.VEGAN})],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
    )
    candidates = [
        make_osm_restaurant("Prime Cut", "steak_house"),
        make_osm_restaurant("Spice Route", "indian_restaurant", 0.002),
    ]

    ranked, _ = scorer.rank_restaurants(candidates, party)

    assert ranked[0].restaurant.name == "Spice Route"
    assert 0.0 <= ranked[0].score <= 1.0


# Missing ratings must not compress scores toward a dead neutral constant.
def test_missing_ratings_do_not_flatten_the_spread():
    party = Party(guest_count=2, guests=[], latitude=BASE_LAT, longitude=BASE_LNG)
    near = make_osm_restaurant("Near", "italian_restaurant", 0.0005)
    far = make_osm_restaurant("Far", "italian_restaurant", 0.03)

    ranked, _ = scorer.rank_restaurants([near, far], party)

    assert ranked[0].restaurant.name == "Near"
    assert ranked[0].score - ranked[1].score > 0.05, (
        "Distance must still separate results once rating weight is dropped."
    )


# Scores must stay normalized even though components are being dropped.
def test_scores_stay_normalized_without_ratings():
    party = Party(
        guest_count=3,
        guests=[Guest("Sam", {Restriction.GLUTEN_FREE})],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        max_price_level=2,
    )
    candidates = [
        make_osm_restaurant("A", "thai_restaurant"),
        make_osm_restaurant("B", "vegan_restaurant", 0.004),
    ]

    ranked, _ = scorer.rank_restaurants(candidates, party)

    for candidate in ranked:
        assert 0.0 <= candidate.score <= 1.0
