"""Shared test setup."""

import pytest

from backend.config import get_settings
from backend.middleware import reset_rate_limits


# Clears rate-limit state before each test so one flood cannot 429 the rest.
@pytest.fixture(autouse=True)
def _clear_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


# Points the response cache at a throwaway directory for every test.
#
# Without this the on-disk cache is shared across the whole suite, so one
# test's cached search silently satisfies another's and any test asserting
# that an upstream call happened fails for the wrong reason.
@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path / "places-cache"))
    yield
