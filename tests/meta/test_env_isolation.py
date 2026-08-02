"""Proves credential environment variables and .env never reach a test.

The variable list is repeated literally here rather than imported from
tests/conftest.py on purpose: a test that imports the constant cannot notice the
constant shrinking.
"""

import importlib
import os

import dotenv
import pytest

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


@pytest.mark.parametrize("module_name", ["src.core.fixer", "src.core.publisher"])
def test_product_modules_hold_the_patched_load_dotenv(module_name):
    """Every module that bound load_dotenv at import time must be patched.

    These modules did `from dotenv import load_dotenv`, so they keep their own
    reference; patching the dotenv module alone does not reach them.
    """
    module = importlib.import_module(module_name)

    assert module.load_dotenv() is False


def test_constructing_codefixer_does_not_repopulate_the_environment():
    """CodeFixer.__init__ calls load_dotenv() unconditionally.

    Unpatched, that reads the real .env and a recovered ANTHROPIC_API_KEY would
    silently take the fixer out of demo mode and into a live API client.
    """
    from src.core.fixer import CodeFixer

    built = CodeFixer()

    for var in SCRUBBED:
        assert var not in os.environ, f"constructing CodeFixer restored {var}"
    assert built.demo_mode is True
    assert built._client is None


def test_constructing_prpublisher_does_not_repopulate_the_environment():
    """publisher.py binds load_dotenv the same way and reads a GitHub token."""
    from src.core.publisher import PRPublisher

    built = PRPublisher("owner/repo")

    for var in SCRUBBED:
        assert var not in os.environ, f"constructing PRPublisher restored {var}"
    # No token recovered means no live GitHub calls are possible.
    assert built.dry_run is True
    assert built.dry_run_reason == "no GITHUB_TOKEN was found"
