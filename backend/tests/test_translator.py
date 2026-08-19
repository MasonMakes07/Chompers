"""Tests for the frontend/backend boundary and request validation."""

import pytest
from pydantic import ValidationError

from backend import translator
from backend.matching.scorer import Evidence, rank_restaurants
from backend.models.guest import Restriction
from backend.models.restaurant import Restaurant
from backend.schemas import GuestRequest, SearchRequest
from backend.services.places_client import PlacesClient

BASE_LAT, BASE_LNG = 32.8801, -117.2340


# ---------------------------------------------------------------------------
# Request validation and input sanitization
# ---------------------------------------------------------------------------


# A request without coordinates or a typed location must be rejected.
def test_search_requires_a_location():
    with pytest.raises(ValidationError):
        SearchRequest(guest_count=2)


# Coordinates alone must be a valid search.
def test_coordinates_are_sufficient():
    request = SearchRequest(guest_count=2, latitude=BASE_LAT, longitude=BASE_LNG)

    assert request.radius_meters == 5000


# A typed location alone must be a valid search.
def test_location_query_is_sufficient():
    request = SearchRequest(guest_count=2, location_query="92093")

    assert request.location_query == "92093"


# Guest counts outside the supported range must be rejected.
@pytest.mark.parametrize("guest_count", [0, -1, 21, 500])
def test_guest_count_is_bounded(guest_count):
    with pytest.raises(ValidationError):
        SearchRequest(
            guest_count=guest_count, latitude=BASE_LAT, longitude=BASE_LNG
        )


# Out-of-range coordinates must be rejected before any API call is spent.
def test_coordinates_are_bounded():
    with pytest.raises(ValidationError):
        SearchRequest(guest_count=2, latitude=999.0, longitude=BASE_LNG)


# Search radius must stay within the supported band.
@pytest.mark.parametrize("radius", [10, 100_000])
def test_radius_is_bounded(radius):
    with pytest.raises(ValidationError):
        SearchRequest(
            guest_count=2,
            latitude=BASE_LAT,
            longitude=BASE_LNG,
            radius_meters=radius,
        )


# Code-like input in a guest name must be rejected outright, not escaped.
@pytest.mark.parametrize(
    "hostile_name",
    [
        "<script>alert(1)</script>",
        "Bob<img src=x onerror=alert(1)>",
        "${process.env.GOOGLE_MAPS_API_KEY}",
        "{{constructor.constructor('x')()}}",
    ],
)
def test_code_like_names_are_rejected(hostile_name):
    with pytest.raises(ValidationError):
        GuestRequest(name=hostile_name)


# Code-like input in the location field must be rejected too.
def test_code_like_location_is_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(guest_count=2, location_query="92093'; DROP TABLE users --")


# An ordinary name with punctuation must still be accepted.
def test_normal_names_are_accepted():
    guest = GuestRequest(name="  Mary-Anne O'Brien  ")

    assert guest.name == "Mary-Anne O'Brien"


# An empty name must fall back to a safe default rather than failing.
def test_blank_name_defaults():
    assert GuestRequest(name="   ").name == "Guest"


# Cuisine terms must be lowercased, trimmed, and emptied entries dropped.
def test_cuisine_terms_are_normalized():
    guest = GuestRequest(name="Sam", liked_cuisines=["  THAI ", "", "Sushi"])

    assert guest.liked_cuisines == ["thai", "sushi"]


# ---------------------------------------------------------------------------
# Frontend -> backend conversion
# ---------------------------------------------------------------------------


# A wire request must convert into a domain Party with guests intact.
def test_party_from_request():
    payload = SearchRequest(
        guest_count=3,
        guests=[
            GuestRequest(name="Maya", restrictions=[Restriction.VEGAN]),
            GuestRequest(name="Mason"),
        ],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        max_price_level=2,
    )

    party = translator.party_from_request(payload, BASE_LAT, BASE_LNG)

    assert party.guest_count == 3
    assert len(party.guests) == 2
    assert Restriction.VEGAN in party.guests[0].restrictions
    assert party.max_price_level == 2


# Headcount must never fall below the number of described guests.
def test_guest_count_cannot_undercount_guests():
    payload = SearchRequest(
        guest_count=1,
        guests=[GuestRequest(name="A"), GuestRequest(name="B")],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
    )

    party = translator.party_from_request(payload, BASE_LAT, BASE_LNG)

    assert party.guest_count == 2


# ---------------------------------------------------------------------------
# Backend -> frontend conversion
# ---------------------------------------------------------------------------


# Confidence values must map onto the three UI status words.
@pytest.mark.parametrize(
    "confidence,expected",
    [(0.95, "good"), (0.75, "good"), (0.6, "limited"), (0.45, "limited"),
     (0.2, "risky"), (0.0, "risky")],
)
def test_confidence_to_status(confidence, expected):
    assert translator.confidence_to_status(confidence) == expected


# Only explicit provider evidence may be presented to the user as verified.
def test_only_explicit_evidence_is_marked_verified():
    from backend.matching.scorer import EVIDENCE_IS_VERIFIED

    assert EVIDENCE_IS_VERIFIED[Evidence.EXPLICIT] is True
    for inferred in (Evidence.KEYWORD, Evidence.CUISINE, Evidence.DEFAULT):
        assert EVIDENCE_IS_VERIFIED[inferred] is False


# Cuisine labels must render as readable text, not raw Google type strings.
def test_readable_cuisine():
    assert (
        translator.readable_cuisine(["indian_restaurant", "restaurant"], "")
        == "Indian Restaurant"
    )
    assert translator.readable_cuisine([], "") == "Restaurant"


# A full response must serialize cleanly and carry its caveat note.
def test_build_search_response():
    from backend.models.guest import Guest
    from backend.models.party import Party

    party = Party(
        guest_count=2,
        guests=[Guest("Maya", {Restriction.VEGAN})],
        latitude=BASE_LAT,
        longitude=BASE_LNG,
    )
    restaurants = [
        Restaurant(
            place_id="a",
            name="Green Fork",
            latitude=BASE_LAT,
            longitude=BASE_LNG,
            primary_type="vegan_restaurant",
            types=["vegan_restaurant"],
            rating=4.5,
            rating_count=200,
        )
    ]
    ranked, excluded = rank_restaurants(restaurants, party)

    response = translator.build_search_response(
        ranked, "your current location", len(restaurants), excluded
    )

    assert len(response.results) == 1
    assert response.results[0].cuisine == "Vegan Restaurant"
    assert response.results[0].guest_fits[0].status == "good"
    assert any("Confirm with" in note for note in response.notes)


# An empty result set must still explain itself rather than returning silence.
def test_empty_response_explains_itself():
    response = translator.build_search_response([], "92093", 0, 0)

    assert response.results == []
    assert any("widening" in note for note in response.notes)


# ---------------------------------------------------------------------------
# Overpass response normalization
# ---------------------------------------------------------------------------


# A realistic Overpass node must normalize into a Restaurant correctly.
def test_normalize_osm_node():
    raw_element = {
        "type": "node",
        "id": 12345,
        "lat": 32.88,
        "lon": -117.23,
        "tags": {
            "name": "Spice Route",
            "amenity": "restaurant",
            "cuisine": "indian",
            "addr:housenumber": "123",
            "addr:street": "Main St",
            "addr:city": "San Diego",
            "diet:vegetarian": "yes",
        },
    }

    restaurant = PlacesClient.normalize_place(raw_element)

    assert restaurant.name == "Spice Route"
    assert restaurant.place_id == "node/12345"
    assert "indian_restaurant" in restaurant.types
    assert restaurant.diet_tags["vegetarian"] == "yes"
    assert "123 Main St" in restaurant.address
    # OpenStreetMap has no ratings or prices; inventing them would be a lie.
    assert restaurant.rating is None
    assert restaurant.price_level is None


# Ways and relations carry a center rather than lat/lon and must still work.
def test_normalize_osm_way_uses_center():
    raw_element = {
        "type": "way",
        "id": 999,
        "center": {"lat": 32.88, "lon": -117.23},
        "tags": {"name": "Big Hall", "amenity": "restaurant"},
    }

    restaurant = PlacesClient.normalize_place(raw_element)

    assert restaurant is not None
    assert restaurant.latitude == 32.88
    assert restaurant.place_id == "way/999"


# Unnamed places are noise on a results page and must be dropped.
def test_normalize_drops_unnamed_places():
    assert PlacesClient.normalize_place({"type": "node", "id": 1, "tags": {}}) is None


# An element with no usable coordinates must be dropped, not defaulted to 0,0.
def test_normalize_drops_places_without_coordinates():
    element = {"type": "node", "id": 1, "tags": {"name": "Ghost Diner"}}

    assert PlacesClient.normalize_place(element) is None
