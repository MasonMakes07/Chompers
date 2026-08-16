"""Restaurant model: a provider-agnostic normalized place.

Nothing downstream of this class knows the data came from Google, which is
what allows a different provider to be swapped in later.
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------


@dataclass
class Restaurant:
    """A single candidate restaurant, normalized from a provider response."""

    place_id: str
    name: str
    latitude: float
    longitude: float
    address: str = ""
    primary_type: str = ""
    types: list[str] = field(default_factory=list)
    rating: float | None = None
    rating_count: int = 0
    price_level: int | None = None
    open_now: bool | None = None
    serves_vegetarian: bool | None = None
    maps_uri: str = ""
    summary: str = ""

    # Lowercases type and name data once so matching never re-normalizes.
    def __post_init__(self) -> None:
        self.types = [place_type.lower() for place_type in self.types]
        self.primary_type = self.primary_type.lower()
        if self.primary_type and self.primary_type not in self.types:
            self.types.insert(0, self.primary_type)

    # Returns the lowercase name, used for keyword evidence like "vegan".
    @property
    def searchable_name(self) -> str:
        return f"{self.name} {self.summary}".lower()

    # Computes great-circle distance in meters from a given coordinate.
    def distance_meters_from(self, latitude: float, longitude: float) -> float:
        earth_radius_meters = 6_371_000.0
        lat1, lat2 = math.radians(latitude), math.radians(self.latitude)
        delta_lat = math.radians(self.latitude - latitude)
        delta_lng = math.radians(self.longitude - longitude)
        haversine = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
        )
        return 2 * earth_radius_meters * math.asin(math.sqrt(haversine))
