"""Scorer tests. These run entirely on synthetic data - no network, no key."""

import pytest

from backend.matching import scorer
from backend.models.guest import Guest, Restriction
from backend.models.party import Party
from backend.models.restaurant import Restaurant

# All fixtures sit near the same point so distance never dominates ranking.
BASE_LAT, BASE_LNG = 32.8801, -117.2340


# Builds a Restaurant with sensible defaults for concise test cases.
def make_restaurant(
    name: str,
    primary_type: str,
    rating: float | None = 4.3,
    rating_count: int = 400,
    price_level: int | None = 2,
    lat_offset: float = 0.001,
    serves_vegetarian: bool | None = None,
    types: list[str] | None = None,
) -> Restaurant:
    return Restaurant(
        place_id=f"id_{name.lower().replace(' ', '_')}",
        name=name,
        latitude=BASE_LAT + lat_offset,
        longitude=BASE_LNG,
        primary_type=primary_type,
        types=types if types is not None else [primary_type, "restaurant"],
        rating=rating,
        rating_count=rating_count,
        price_level=price_level,
        serves_vegetarian=serves_vegetarian,
    )


# Builds a Party at the base coordinate from a list of guests.
def make_party(guests: list[Guest], guest_count: int | None = None) -> Party:
    return Party(
        guest_count=guest_count if guest_count is not None else max(1, len(guests)),
        guests=guests,
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        radius_meters=5000,
    )


# ---------------------------------------------------------------------------
# The headline behavior: nobody gets left behind
# ---------------------------------------------------------------------------


# The one vegan must outweigh four omnivores and a better steakhouse rating.
def test_one_vegan_outweighs_four_omnivores_and_a_better_rating():
    steakhouse = make_restaurant(
        "Prime Cut", "steak_house", rating=4.9, rating_count=1200
    )
    indian = make_restaurant(
        "Spice Route", "indian_restaurant", rating=4.2, rating_count=300
    )
    party = make_party(
        [
            Guest("Mason"),
            Guest("Alex"),
            Guest("Jordan"),
            Guest("Sam"),
            Guest("Maya", {Restriction.VEGAN}),
        ]
    )

    ranked, _ = scorer.rank_restaurants([steakhouse, indian], party)

    assert ranked[0].restaurant.name == "Spice Route", (
        "The vegan guest must dominate the ranking even against a "
        "higher-rated steakhouse."
    )


# With no restrictions at all, the higher-rated restaurant should win.
def test_without_restrictions_rating_decides():
    steakhouse = make_restaurant(
        "Prime Cut", "steak_house", rating=4.9, rating_count=1200
    )
    indian = make_restaurant(
        "Spice Route", "indian_restaurant", rating=4.2, rating_count=300
    )
    party = make_party([Guest("Mason"), Guest("Alex")])

    ranked, _ = scorer.rank_restaurants([steakhouse, indian], party)

    assert ranked[0].restaurant.name == "Prime Cut"


# A steakhouse must be disqualified outright for a vegan diner.
def test_hard_floor_disqualifies_impossible_restaurants():
    steakhouse = make_restaurant("Prime Cut", "steak_house")
    vegan_spot = make_restaurant("Green Fork", "vegan_restaurant")
    party = make_party([Guest("Maya", {Restriction.VEGAN})])

    ranked, excluded = scorer.rank_restaurants([steakhouse, vegan_spot], party)

    assert excluded == 1
    assert [item.restaurant.name for item in ranked] == ["Green Fork"]


# When every option is disqualified we still return something, with warnings.
def test_falls_back_rather_than_returning_nothing():
    party = make_party([Guest("Maya", {Restriction.VEGAN})])
    only_bad_options = [
        make_restaurant("Prime Cut", "steak_house"),
        make_restaurant("Smoke Pit", "barbecue_restaurant", lat_offset=0.002),
    ]

    ranked, excluded = scorer.rank_restaurants(only_bad_options, party)

    assert len(ranked) == 2
    assert excluded == 2
    assert ranked[0].warnings, "A fallback result must explain the problem."


# ---------------------------------------------------------------------------
# Allergies behave differently from diets
# ---------------------------------------------------------------------------


# Thai is vegetarian-friendly but must score poorly for a nut allergy.
def test_nut_allergy_penalizes_peanut_heavy_cuisine():
    thai = make_restaurant("Bangkok Garden", "thai_restaurant")

    vegetarian_fit = scorer.restriction_confidence(thai, Restriction.VEGETARIAN)
    nut_fit = scorer.restriction_confidence(thai, Restriction.NUT_ALLERGY)

    assert vegetarian_fit.confidence > 0.8
    assert nut_fit.confidence < 0.3


# Allergies take the most cautious prior when a place has several types.
def test_allergy_uses_most_cautious_cuisine_type():
    fusion = make_restaurant(
        "Pier Fusion",
        "seafood_restaurant",
        types=["seafood_restaurant", "american_restaurant", "restaurant"],
    )

    fit = scorer.restriction_confidence(fusion, Restriction.SHELLFISH_ALLERGY)

    assert fit.confidence == pytest.approx(0.15), (
        "Shellfish allergy must use the seafood prior, not the American one."
    )


# Diets take the most generous prior, since one good menu section suffices.
def test_diet_uses_most_generous_cuisine_type():
    fusion = make_restaurant(
        "Curry and Chops",
        "steak_house",
        types=["steak_house", "indian_restaurant", "restaurant"],
    )

    fit = scorer.restriction_confidence(fusion, Restriction.VEGETARIAN)

    assert fit.confidence == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Evidence tiers
# ---------------------------------------------------------------------------


# An explicit provider flag must override the cuisine prior entirely.
def test_explicit_flag_beats_cuisine_prior():
    steakhouse = make_restaurant(
        "Veg Friendly Chophouse", "steak_house", serves_vegetarian=True
    )

    fit = scorer.restriction_confidence(steakhouse, Restriction.VEGETARIAN)

    assert fit.evidence is scorer.Evidence.EXPLICIT
    assert fit.confidence > 0.8


# A name containing "halal" is stronger evidence than any cuisine prior.
def test_name_keyword_beats_cuisine_prior():
    grill = make_restaurant("Halal Grill House", "american_restaurant")

    fit = scorer.restriction_confidence(grill, Restriction.HALAL)

    assert fit.evidence is scorer.Evidence.KEYWORD
    assert fit.confidence > 0.9


# An unknown cuisine must fall back to the neutral prior and say so.
def test_unknown_cuisine_uses_default_evidence():
    mystery = make_restaurant("The Unknown", "restaurant", types=["point_of_interest"])

    fit = scorer.restriction_confidence(mystery, Restriction.VEGETARIAN)

    assert fit.evidence is scorer.Evidence.DEFAULT
    assert fit.reason == "no cuisine information available"


# Halal and kosher must never be assumed from an unrecognized restaurant.
def test_certification_restrictions_are_never_assumed():
    mystery = make_restaurant("The Unknown", "restaurant", types=["point_of_interest"])

    halal_fit = scorer.restriction_confidence(mystery, Restriction.HALAL)
    kosher_fit = scorer.restriction_confidence(mystery, Restriction.KOSHER)

    assert halal_fit.confidence < 0.2
    assert kosher_fit.confidence < 0.2


# ---------------------------------------------------------------------------
# Aggregation math
# ---------------------------------------------------------------------------


# The minimum must dominate the mean in the group blend.
def test_group_fit_is_dominated_by_worst_served_guest():
    fits = [
        scorer.GuestFit("A", 1.0),
        scorer.GuestFit("B", 1.0),
        scorer.GuestFit("C", 1.0),
        scorer.GuestFit("D", 0.1),
    ]

    blended = scorer.group_fit_score(fits)
    plain_mean = sum(fit.confidence for fit in fits) / len(fits)

    assert blended < plain_mean
    assert blended < 0.5


# Vegan must imply vegetarian so weaker vegetarian evidence still applies.
def test_vegan_implies_vegetarian():
    guest = Guest("Maya", {Restriction.VEGAN})

    assert Restriction.VEGETARIAN in guest.effective_restrictions()


# A guest is scored by their single hardest restriction, not the average.
def test_guest_scored_by_hardest_restriction():
    indian = make_restaurant("Spice Route", "indian_restaurant")
    guest = Guest("Sam", {Restriction.VEGETARIAN, Restriction.DAIRY_FREE})

    fit = scorer.guest_confidence(indian, guest)

    assert fit.confidence == pytest.approx(0.30), "Dairy is the binding limit."
    assert fit.limiting_fit.restriction is Restriction.DAIRY_FREE


# ---------------------------------------------------------------------------
# Rating, distance, price
# ---------------------------------------------------------------------------


# A perfect rating from few reviews must not beat a strong, well-reviewed one.
def test_rating_is_damped_by_review_count():
    barely_reviewed = scorer.rating_score(5.0, 3)
    well_reviewed = scorer.rating_score(4.6, 900)

    assert well_reviewed > barely_reviewed


# A missing rating must land at neutral rather than zero.
def test_missing_rating_is_neutral():
    assert scorer.rating_score(None, 0) == 0.5


# Closer restaurants must score strictly higher on distance.
def test_distance_score_decays_with_range():
    assert scorer.distance_score(100, 5000) > scorer.distance_score(4000, 5000)


# Exceeding the party's price ceiling must zero the price component.
def test_price_above_ceiling_scores_zero():
    assert scorer.price_fit_score(4, 2) == 0.0
    assert scorer.price_fit_score(1, 2) == 1.0
    assert scorer.price_fit_score(None, None) == 0.5


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


# An empty candidate list must not raise.
def test_empty_candidate_list():
    party = make_party([Guest("Mason")])

    ranked, excluded = scorer.rank_restaurants([], party)

    assert ranked == []
    assert excluded == 0


# A party with no guests described must still rank normally.
def test_party_with_no_guests():
    party = Party(guest_count=4, guests=[], latitude=BASE_LAT, longitude=BASE_LNG)
    restaurants = [make_restaurant("Any Place", "american_restaurant")]

    ranked, _ = scorer.rank_restaurants(restaurants, party)

    assert ranked[0].group_fit == 1.0


# One guest carrying every restriction at once must not crash the scorer.
def test_guest_with_every_restriction():
    party = make_party([Guest("Everything", set(Restriction))])
    restaurants = [make_restaurant("Green Fork", "vegan_restaurant")]

    ranked, _ = scorer.rank_restaurants(restaurants, party)

    assert 0.0 <= ranked[0].group_fit <= 1.0
    assert len(ranked[0].guest_fits[0].restriction_fits) == len(Restriction)


# A restaurant missing rating, price, and types must still score safely.
def test_restaurant_with_missing_fields():
    sparse = Restaurant(
        place_id="sparse",
        name="Mystery Spot",
        latitude=BASE_LAT,
        longitude=BASE_LNG,
        types=[],
        rating=None,
        rating_count=0,
        price_level=None,
    )
    party = make_party([Guest("Maya", {Restriction.VEGETARIAN})])

    ranked, _ = scorer.rank_restaurants([sparse], party)

    assert 0.0 <= ranked[0].score <= 1.0


# A large party must produce a call-ahead warning, since seating is unverified.
def test_large_party_triggers_call_ahead_warning():
    party = make_party([Guest("Mason")], guest_count=8)
    restaurants = [make_restaurant("Big Table", "american_restaurant")]

    ranked, _ = scorer.rank_restaurants(restaurants, party)

    assert any("call ahead" in warning.lower() for warning in ranked[0].warnings)


# The result limit must be respected exactly.
def test_limit_is_respected():
    party = make_party([Guest("Mason")])
    restaurants = [
        make_restaurant(f"Place {index}", "american_restaurant", lat_offset=index / 1e4)
        for index in range(12)
    ]

    ranked, _ = scorer.rank_restaurants(restaurants, party, limit=5)

    assert len(ranked) == 5


# Every score component must stay inside [0, 1] so weights stay meaningful.
def test_scores_stay_normalized():
    party = make_party(
        [Guest("Mason", {Restriction.GLUTEN_FREE}), Guest("Maya", {Restriction.VEGAN})]
    )
    restaurants = [
        make_restaurant("A", "thai_restaurant"),
        make_restaurant("B", "steak_house", lat_offset=0.02),
        make_restaurant("C", "vegan_restaurant", lat_offset=0.005),
    ]

    ranked, _ = scorer.rank_restaurants(restaurants, party)

    for candidate in ranked:
        assert 0.0 <= candidate.score <= 1.0
        assert 0.0 <= candidate.group_fit <= 1.0
