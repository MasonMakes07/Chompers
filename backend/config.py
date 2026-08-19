"""Application configuration loaded from environment variables.

The Google API key is read here and nowhere else, so it can never leak into
a module that is serialized back to the browser.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)

# Load backend/.env first, then fall back to the project-root .env, so the key
# is found wherever it was placed. Existing values are never overwritten.
for _env_path in (
    os.path.join(_BACKEND_DIR, ".env"),
    os.path.join(_PROJECT_ROOT, ".env"),
):
    if os.path.isfile(_env_path):
        load_dotenv(_env_path, override=False)


# ---------------------------------------------------------------------------


class Settings:
    """Holds every runtime setting, validated once at process startup."""

    # Reads and validates all environment variables for this process.
    def __init__(self) -> None:
        # Retained but unused: the app now runs on OpenStreetMap, which needs
        # no key at all. Kept so a Google provider could be restored later.
        self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        self.overpass_url = os.getenv(
            "OVERPASS_URL", "https://overpass-api.de/api/interpreter"
        ).strip()
        # Both Overpass and Nominatim require an identifying User-Agent.
        self.user_agent = os.getenv(
            "USER_AGENT", "Chompers/1.0 (group restaurant matcher)"
        ).strip()
        self.allowed_origins = self._parse_origins(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
        )
        self.rate_limit_per_minute = self._parse_int(
            os.getenv("RATE_LIMIT_PER_MINUTE"), default=10, minimum=1
        )
        self.cache_ttl_seconds = self._parse_int(
            os.getenv("CACHE_TTL_SECONDS"), default=900, minimum=0
        )
        self.max_request_bytes = 16 * 1024

    # Splits a comma-separated origin list into clean individual entries.
    @staticmethod
    def _parse_origins(raw_origins: str) -> list[str]:
        return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]

    # Converts an env string to a bounded int, falling back on bad input.
    @staticmethod
    def _parse_int(raw_value: str | None, default: int, minimum: int) -> int:
        try:
            parsed_value = int(raw_value) if raw_value is not None else default
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed_value)

    # Raises immediately if the API key is missing, rather than at first search.
    def require_api_key(self) -> str:
        if not self.google_maps_api_key:
            raise RuntimeError(
                "GOOGLE_MAPS_API_KEY is not set. Copy .env.example to "
                "backend/.env and add your key."
            )
        return self.google_maps_api_key

    # Reports whether live Google calls are possible in this environment.
    @property
    def has_api_key(self) -> bool:
        return bool(self.google_maps_api_key)


# ---------------------------------------------------------------------------


# Returns the single cached Settings instance for the whole application.
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
