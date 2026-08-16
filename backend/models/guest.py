"""Guest model: one person in the dining party and what they cannot eat."""

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------


class Restriction(str, Enum):
    """Every dietary restriction the matcher understands."""

    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_ALLERGY = "nut_allergy"
    SHELLFISH_ALLERGY = "shellfish_allergy"
    HALAL = "halal"
    KOSHER = "kosher"


# Restrictions that are medical rather than dietary. These are scored more
# harshly because the failure mode is an allergic reaction, not a dull meal.
ALLERGY_RESTRICTIONS = frozenset(
    {Restriction.NUT_ALLERGY, Restriction.SHELLFISH_ALLERGY}
)

# Human-readable labels used in the "why this ranked" explanations.
RESTRICTION_LABELS = {
    Restriction.VEGETARIAN: "vegetarian",
    Restriction.VEGAN: "vegan",
    Restriction.GLUTEN_FREE: "gluten-free",
    Restriction.DAIRY_FREE: "dairy-free",
    Restriction.NUT_ALLERGY: "nut allergy",
    Restriction.SHELLFISH_ALLERGY: "shellfish allergy",
    Restriction.HALAL: "halal",
    Restriction.KOSHER: "kosher",
}


# ---------------------------------------------------------------------------


@dataclass
class Guest:
    """One diner, their hard restrictions, and their soft cuisine tastes."""

    name: str
    restrictions: set[Restriction] = field(default_factory=set)
    liked_cuisines: set[str] = field(default_factory=set)
    disliked_cuisines: set[str] = field(default_factory=set)

    # Normalizes cuisine preferences to lowercase so matching is consistent.
    def __post_init__(self) -> None:
        self.name = self.name.strip() or "Guest"
        self.liked_cuisines = {c.strip().lower() for c in self.liked_cuisines if c}
        self.disliked_cuisines = {
            c.strip().lower() for c in self.disliked_cuisines if c
        }

    # Reports whether this guest has any restriction at all.
    @property
    def has_restrictions(self) -> bool:
        return bool(self.restrictions)

    # Returns the guest's restrictions that are allergies, not preferences.
    @property
    def allergies(self) -> set[Restriction]:
        return self.restrictions & ALLERGY_RESTRICTIONS

    # Vegan implies vegetarian, so expand it to avoid missing weaker evidence.
    def effective_restrictions(self) -> set[Restriction]:
        expanded = set(self.restrictions)
        if Restriction.VEGAN in expanded:
            expanded.add(Restriction.VEGETARIAN)
        return expanded
