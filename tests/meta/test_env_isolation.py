"""Proves credential environment variables and .env never reach a test.

The variable list is repeated literally here rather than imported from
tests/conftest.py on purpose: a test that imports the constant cannot notice the
constant shrinking.
"""

import os

import dotenv

SCRUBBED = [
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_PAT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
]

_CONTAMINANT = "fake-token-set-at-import-time"

# Runs at import, before any fixture. This makes the scrub test deterministic:
# the value provably existed and provably had to be removed, rather than the
# test merely observing a variable that was never set.
os.environ["GITHUB_TOKEN"] = _CONTAMINANT


def test_scrubbed_variables_absent():
    for var in SCRUBBED:
        assert var not in os.environ, f"{var} leaked into the test environment"


def test_preexisting_value_is_actually_removed():
    assert os.environ.get("GITHUB_TOKEN") != _CONTAMINANT
    assert "GITHUB_TOKEN" not in os.environ


def test_sentinel_present():
    assert os.environ.get("SELF_MAINTAINING_APIS_TESTING") == "1"


def test_dotenv_load_dotenv_is_a_noop():
    assert not dotenv.load_dotenv()
    for var in SCRUBBED:
        assert var not in os.environ, f"load_dotenv repopulated {var}"


def test_dotenv_main_load_dotenv_is_a_noop():
    assert not dotenv.main.load_dotenv()
    for var in SCRUBBED:
        assert var not in os.environ, f"dotenv.main.load_dotenv repopulated {var}"


def test_dotenv_find_dotenv_returns_empty():
    assert dotenv.find_dotenv() == ""
