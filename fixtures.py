"""Loads the JSON fixtures that stand in for the claims back end."""

import json
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).parent / "insurance_claims" / "fixtures"


@lru_cache(maxsize=None)
def load(name):
    """Read a fixture by file name. Cached, so treat the result as read-only."""
    with open(FIXTURES / name) as f:
        return json.load(f)
