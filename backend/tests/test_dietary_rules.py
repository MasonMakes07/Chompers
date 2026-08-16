"""Tests for the dietary knowledge table's integrity and its core claims."""

from backend.matching import dietary_rules
from backend.models.guest import Restriction


# Every row must carry exactly one value per restriction, all within [0, 1].
def test_table_is_well_formed():
    dietary_rules._validate_table()

    for cuisine_name, row in dietary_rules.CUISINE_PRIORS.items():
        assert len(row) == len(dietary_rules.RESTRICTION_ORDER), cuisine_name
        assert all(0.0 <= value <= 1.0 for value in row), cuisine_name


# The column order must cover every restriction the app supports, exactly once.
def test_column_order_covers_all_restrictions():
    assert set(dietary_rules.RESTRICTION_ORDER) == set(Restriction)
    assert len(dietary_rules.RESTRICTION_ORDER) == len(set(Restriction))


# Halal and kosher must never be inferred from an unknown restaurant type.
def test_certification_defaults_stay_low():
    assert dietary_rules.default_prior(Restriction.HALAL) < 0.2
    assert dietary_rules.default_prior(Restriction.KOSHER) < 0.2


# A dedicated vegan restaurant must be the strongest possible vegan signal.
def test_vegan_restaurant_is_maximally_confident():
    assert dietary_rules.cuisine_prior("vegan_restaurant", Restriction.VEGAN) == 1.0


# Steakhouses must be near-hopeless for vegans, which drives disqualification.
def test_steakhouse_is_hostile_to_vegans():
    prior = dietary_rules.cuisine_prior("steak_house", Restriction.VEGAN)

    assert prior is not None and prior < 0.1


# Vegetarian-friendly cuisines can still be dangerous for nut allergies.
def test_vegetarian_friendly_can_still_fail_nut_allergy():
    for cuisine in ("thai_restaurant", "indonesian_restaurant"):
        vegetarian = dietary_rules.cuisine_prior(cuisine, Restriction.VEGETARIAN)
        nut_safety = dietary_rules.cuisine_prior(cuisine, Restriction.NUT_ALLERGY)

        assert vegetarian is not None and nut_safety is not None
        assert vegetarian > 0.55
        assert nut_safety < 0.25, f"{cuisine} should be risky for nut allergies"


# Buffets must score poorly on allergies because utensils are shared.
def test_buffets_are_risky_for_allergies():
    nut_safety = dietary_rules.cuisine_prior(
        "buffet_restaurant", Restriction.NUT_ALLERGY
    )
    breadth = dietary_rules.cuisine_prior(
        "buffet_restaurant", Restriction.VEGETARIAN
    )

    assert breadth is not None and breadth > 0.6
    assert nut_safety is not None and nut_safety < 0.4


# An unrecognized type must report as unknown rather than silently defaulting.
def test_unknown_cuisine_is_reported_as_unknown():
    assert not dietary_rules.is_known_cuisine("laundromat")
    assert dietary_rules.cuisine_prior("laundromat", Restriction.VEGAN) is None


# Name keywords must be detected and must return their stated confidence.
def test_keyword_evidence_detection():
    match = dietary_rules.keyword_evidence("mama's kosher deli", Restriction.KOSHER)

    assert match is not None
    confidence, reason = match
    assert confidence > 0.9
    assert "kosher" in reason


# A keyword that does not apply to the asked restriction must not match.
def test_keyword_evidence_ignores_unrelated_restrictions():
    assert (
        dietary_rules.keyword_evidence("halal grill", Restriction.GLUTEN_FREE) is None
    )


# A vegan name must also grant vegetarian and dairy-free confidence.
def test_vegan_keyword_implies_related_restrictions():
    for restriction in (
        Restriction.VEGAN,
        Restriction.VEGETARIAN,
        Restriction.DAIRY_FREE,
    ):
        match = dietary_rules.keyword_evidence("the vegan spot", restriction)
        assert match is not None, restriction
        assert match[0] > 0.9
