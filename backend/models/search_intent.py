"""What a user actually meant by their search text.

Parsing free text into this structure is what separates "match the letters
v-e-g-a-n against a name" from "find places that actually serve vegans".
A restaurant called Green Fork tagged `diet:vegan=only` should win a search
for "vegan"; a steakhouse called Vegan's Revenge should not.
"""

from dataclasses import dataclass, field

from .guest import Restriction


# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchIntent:
    """A parsed search: the diets, cuisines, and words the user asked for."""

    raw: str = ""
    # Dietary needs named in the query, e.g. "vegan" -> VEGAN.
    diets: frozenset[Restriction] = field(default_factory=frozenset)
    # OpenStreetMap `cuisine` tag values to match, e.g. {"sushi", "japanese"}.
    cuisines: frozenset[str] = field(default_factory=frozenset)
    # Our place types, derived from those cuisines, for scoring.
    place_types: frozenset[str] = field(default_factory=frozenset)
    # Words we could not interpret, matched against restaurant names.
    keywords: tuple[str, ...] = ()

    # Reports whether the query yielded nothing worth searching on.
    @property
    def is_empty(self) -> bool:
        return not (self.diets or self.cuisines or self.keywords)

    # Reports whether anything structured was understood, vs. raw words only.
    @property
    def is_structured(self) -> bool:
        return bool(self.diets or self.cuisines)
