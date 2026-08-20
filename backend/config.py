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
        self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        # "google" or "openstreetmap". Google gives ratings and price levels
        # but needs a billing account; OpenStreetMap needs nothing and stays
        # available as a fallback if a key is ever revoked.
        self.places_provider = os.getenv("PLACES_PROVIDER", "google").strip()
        # Enterprise dietary fields cut the free Google allowance from 5,000
        # calls a month to 1,000, and the cuisine priors cover most of the
        # same ground, so they stay opt-in.
        self.include_dietary_flags = (
            os.getenv("INCLUDE_DIETARY_FLAGS", "false").strip().lower() == "true"
        )
        self.overpass_url = os.getenv(
            "OVERPASS_URL", "https://overpass-api.de/api/interpreter"
        ).strip()
        # Independent mirrors with their own rate-limit slots. When the
        # primary is queueing or throttling, retrying elsewhere beats making
        # the user wait out a cooldown they did not cause.
        self.overpass_mirrors = self._parse_origins(
            os.getenv(
                "OVERPASS_MIRRORS",
                "https://overpass.kumi.systems/api/interpreter,"
                "https://overpass.private.coffee/api/interpreter",
            )
        )
        # Both Overpass and Nominatim require an identifying User-Agent.
        self.user_agent = os.getenv(
            "USER_AGENT", "Chompers/1.0 (group restaurant matcher)"
        ).strip()
        # Restrict geocoding to these ISO 3166-1 country codes so a typed
        # "San Francisco, CA" can never resolve to a same-named town abroad.
        # Nominatim reads a bare "CA" as Canada without this, and a misspelled
        # city can match a foreign place. Comma-separated; blank allows any
        # country for a future non-US deployment.
        self.geocode_country_codes = (
            os.getenv("GEOCODE_COUNTRY_CODES", "us").strip().lower()
        )
        self.allowed_origins = self._parse_origins(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
        )
        # A single user action can cost more than one request (naming the
        # location, then searching), and React StrictMode doubles effects in
        # development, so this has room above the one-per-search baseline.
        self.rate_limit_per_minute = self._parse_int(
            os.getenv("RATE_LIMIT_PER_MINUTE"), default=30, minimum=1
        )
        # Caps how many of that minute's allowance can land at once. A real
        # user searches a few times in ten seconds; a script fires hundreds.
        #
        # Derived from the per-minute limit rather than fixed, and clamped
        # below it: a burst cap at or above the minute cap can never fire
        # first, silently leaving floods unguarded.
        self.rate_limit_burst = min(
            self._parse_int(
                os.getenv("RATE_LIMIT_BURST"),
                default=max(3, self.rate_limit_per_minute // 3),
                minimum=1,
            ),
            max(1, self.rate_limit_per_minute - 1),
        )
        # Ceiling across every client. Per-IP limits alone do not protect the
        # upstream quota, since many addresses each get their own allowance.
        self.global_rate_limit_per_minute = self._parse_int(
            os.getenv("GLOBAL_RATE_LIMIT_PER_MINUTE"), default=120, minimum=1
        )
        # Bounds the rate-limit table so cycling source addresses cannot
        # grow it without limit.
        self.max_tracked_clients = self._parse_int(
            os.getenv("MAX_TRACKED_CLIENTS"), default=5_000, minimum=100
        )
        # Number of trusted reverse proxies in front of this app. Zero (the
        # default) means trust only the socket peer and ignore the spoofable
        # X-Forwarded-For header entirely. Set this to the real proxy hop
        # count only when every one of those hops is under your control, so
        # the client IP is read from the right of the chain where a forged
        # left-hand entry cannot reach it.
        self.trusted_proxy_count = self._parse_int(
            os.getenv("TRUSTED_PROXY_COUNT"), default=0, minimum=0
        )
        # Where cached Overpass responses live between runs. Without this the
        # cache dies on every reload, which in development is every edit.
        # Vercel's filesystem is read-only except for /tmp, so default the cache
        # there when running on Vercel (it sets the VERCEL env var). Local runs
        # keep the project-root cache, which survives reloads.
        default_cache_dir = (
            "/tmp/chompers-cache"
            if os.getenv("VERCEL")
            else os.path.join(_PROJECT_ROOT, ".cache", "places")
        )
        self.cache_dir = os.getenv("CACHE_DIR", default_cache_dir).strip()
        self.cache_ttl_seconds = self._parse_int(
            # OpenStreetMap is volunteer-edited: restaurants appear and close
            # on a scale of days, not minutes. A 15-minute TTL threw away
            # good data and paid a multi-second refetch for nothing.
            os.getenv("CACHE_TTL_SECONDS"),
            default=86_400,
            minimum=0,
        )
        self.max_request_bytes = 16 * 1024

    # Returns the primary endpoint followed by each configured mirror.
    @property
    def overpass_endpoints(self) -> list[str]:
        endpoints = [self.overpass_url]
        for mirror in self.overpass_mirrors:
            if mirror not in endpoints:
                endpoints.append(mirror)
        return endpoints

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
