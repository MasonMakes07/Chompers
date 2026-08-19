"""Chooses the places provider and re-exports the shared pieces.

Everything else in the app imports from here, so swapping providers is a
config change rather than a code change. The choice is deliberate: Google
gives ratings and richer data but needs a billing account, while
OpenStreetMap needs nothing at all and stays available as a working fallback.
"""

from ..config import get_settings
from .google_places_client import GooglePlacesClient
from .overpass_client import OverpassPlacesClient
from .places_base import BasePlacesClient, PlacesError, mark_retryable

GOOGLE = "google"
OPENSTREETMAP = "openstreetmap"

__all__ = [
    "BasePlacesClient",
    "GooglePlacesClient",
    "OverpassPlacesClient",
    "PlacesError",
    "create_places_client",
    "mark_retryable",
]


# Builds the client for the configured provider, defaulting to Google and
# falling back to OpenStreetMap when no API key is available.
def create_places_client() -> BasePlacesClient:
    settings = get_settings()
    provider = (settings.places_provider or GOOGLE).strip().lower()

    if provider == OPENSTREETMAP:
        return OverpassPlacesClient()

    # Asking for Google without a key would fail on the first search with a
    # confusing error, so fall back to the provider that always works.
    if not settings.has_api_key:
        return OverpassPlacesClient()

    return GooglePlacesClient(
        include_dietary_flags=settings.include_dietary_flags
    )
