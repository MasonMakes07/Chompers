"""Party model: the whole group, its location, and its shared search settings."""

from dataclasses import dataclass, field

from .guest import Guest, Restriction
from .search_intent import SearchIntent

# Above this headcount most restaurants want advance notice, so results carry
# a "call ahead" notice. Google exposes no capacity field, so this is advice,
# not a verified fact about the restaurant.
LARGE_PARTY_THRESHOLD = 6


# ---------------------------------------------------------------------------


@dataclass
class Party:
    """A dining group: headcount, guests with restrictions, and search area."""

    guest_count: int
    guests: list[Guest] = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    radius_meters: int = 5000
    max_price_level: int | None = None
    # What the user typed, parsed. None for a plain group search.
    search_intent: SearchIntent | None = None

    # Guarantees headcount is at least the number of described guests.
    def __post_init__(self) -> None:
        self.guest_count = max(1, self.guest_count, len(self.guests))

    # Returns every distinct restriction present anywhere in the party.
    def combined_restrictions(self) -> set[Restriction]:
        combined: set[Restriction] = set()
        for guest in self.guests:
            combined |= guest.effective_restrictions()
        return combined

    # Returns only the guests who actually constrain the search.
    def restricted_guests(self) -> list[Guest]:
        return [guest for guest in self.guests if guest.has_restrictions]

    # Reports whether this group is large enough to warrant calling ahead.
    @property
    def is_large_party(self) -> bool:
        return self.guest_count >= LARGE_PARTY_THRESHOLD

    # Collects cuisine likes across the whole party for soft ranking.
    def liked_cuisines(self) -> set[str]:
        liked: set[str] = set()
        for guest in self.guests:
            liked |= guest.liked_cuisines
        return liked

    # Collects cuisine dislikes across the whole party for soft ranking.
    def disliked_cuisines(self) -> set[str]:
        disliked: set[str] = set()
        for guest in self.guests:
            disliked |= guest.disliked_cuisines
        return disliked
