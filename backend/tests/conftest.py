"""Shared test setup."""

import pytest

from backend.middleware import reset_rate_limits


# Clears rate-limit state before each test so one flood cannot 429 the rest.
@pytest.fixture(autouse=True)
def _clear_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()
