"""Safety fixtures for all tests.

These fixtures establish the Phase 0 harness guarantees: no real credentials,
no .env leakage, no network access, and no working-tree mutation during tests.
Do not weaken or remove them without review.
"""

import importlib
import socket
import warnings
from pathlib import Path

import dotenv
import dotenv.main
import pytest
from pytest_socket import SocketBlockedError

from tests.helpers.tree_guard import diff, snapshot

SCRUBBED_ENV_VARS = [
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_PAT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
]

# Product modules that do `from dotenv import load_dotenv` at import time. Keep
# this in step with: grep -rn "from dotenv import" src/
DOTENV_IMPORTING_MODULES = [
    "src.core.fixer",
    "src.core.publisher",
]

_NO_DOTENV_CALLED = {"called": False}


def _noop_load_dotenv(*args, **kwargs):
    _NO_DOTENV_CALLED["called"] = True
    return False


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in SCRUBBED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("SELF_MAINTAINING_APIS_TESTING", "1")


@pytest.fixture(autouse=True)
def no_dotenv(clean_env, monkeypatch):
    monkeypatch.setattr(dotenv, "load_dotenv", _noop_load_dotenv)
    monkeypatch.setattr(dotenv.main, "load_dotenv", _noop_load_dotenv)
    monkeypatch.setattr(dotenv, "find_dotenv", lambda *args, **kwargs: "")

    # Patching the dotenv module is not enough on its own: a module that did
    # `from dotenv import load_dotenv` at import time holds its own reference to
    # the original function, so it must be patched in ITS namespace. Both of
    # these call load_dotenv() unconditionally in __init__, and the real .env
    # holds a working GitHub token, so missing one would hand a test live
    # credentials -- and, for CodeFixer, a real API client instead of demo mode.
    for module_name in DOTENV_IMPORTING_MODULES:
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "load_dotenv", _noop_load_dotenv)

    return _NO_DOTENV_CALLED


@pytest.fixture(autouse=True)
def assert_socket_disabled(pytestconfig):
    """Fail at setup if the socket block is not actually in force.

    Primary enforcement is --disable-socket in pytest.ini. This fixture exists to
    catch `pytest -p no:socket` or an edited addopts, which would silently remove
    the guarantee the rest of the harness depends on. Returns True so tests can
    assert the guard reported itself active.
    """
    if not pytestconfig.pluginmanager.hasplugin("socket"):
        pytest.fail(
            "pytest-socket plugin is not active; socket blocking is disabled. "
            "Ensure pytest.ini still contains --disable-socket and the plugin is installed."
        )

    # The probe is behavioural rather than an attribute check, so it cannot be
    # fooled by a plugin that is loaded but not actually patching. catch_warnings
    # suppresses the UserWarning pytest-socket raises alongside the error, which
    # would otherwise be recorded once per test.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except SocketBlockedError:
            return True

    probe.close()
    pytest.fail(
        "socket.socket() succeeded: the socket block is NOT in force. "
        "Refusing to run tests that could reach the network."
    )


@pytest.fixture(scope="session")
def fixtures_dir():
    return Path(__file__).resolve().parent / "fixtures"


def pytest_sessionstart(session):
    session._initial_tree_snapshot = snapshot(Path(session.config.rootpath))


def pytest_sessionfinish(session, exitstatus):
    final_snapshot = snapshot(Path(session.config.rootpath))
    added, removed, modified = diff(session._initial_tree_snapshot, final_snapshot)

    if added or removed or modified:
        print("\nERROR: project tree was modified during tests:")
        for path in sorted(added):
            print(f"  ADDED: {path}")
        for path in sorted(removed):
            print(f"  REMOVED: {path}")
        for path in sorted(modified):
            print(f"  MODIFIED: {path}")
        session.exitstatus = max(exitstatus, 1)
