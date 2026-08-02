"""Unit tests for main.py's wiring of the declared source into the pipeline.

Scope is the seam only: that build_change_event assembles a ChangeEvent from the
parsed arguments, that the three new flags override the module constants, and
that threading change_description through build_pr_body changed nothing. No
end-to-end run happens here.
"""

from datetime import datetime

import pytest

from src.domain.change_event import ChangeEvent
from src.main import (
    CHANGE_DESCRIPTION,
    DECLARED_CHANGE_CLASS,
    DECLARED_SYMBOL,
    DOCS_URL,
    build_change_event,
    build_pr_body,
    parse_args,
    utc_now_iso,
)

pytestmark = pytest.mark.unit

FROZEN_TIME = "2026-08-02T12:00:00+00:00"


def frozen_clock():
    return FROZEN_TIME


def result_fixture(demo_mode=True):
    """A minimal fix_files_from_findings-shaped result, for build_pr_body."""
    return {
        "changes": {"examples/payment.py": "fixed contents\n"},
        "match_counts": {"examples/payment.py": 3},
        "examined": 1,
        "changed": 1,
        "skipped": 0,
        "failed": 0,
        "demo_mode": demo_mode,
        "model": "claude-sonnet-5",
    }


# --- build_change_event --------------------------------------------------


def test_build_change_event_returns_a_change_event_carrying_the_description():
    event = build_change_event(parse_args([]), clock=frozen_clock)

    assert isinstance(event, ChangeEvent)
    assert event.description == CHANGE_DESCRIPTION


def test_default_symbol_comes_from_the_module_constant():
    event = build_change_event(parse_args([]), clock=frozen_clock)

    assert event.symbol == DECLARED_SYMBOL


def test_default_change_class_comes_from_the_module_constant():
    event = build_change_event(parse_args([]), clock=frozen_clock)

    assert event.change_class == DECLARED_CHANGE_CLASS


def test_default_source_url_comes_from_docs_url():
    event = build_change_event(parse_args([]), clock=frozen_clock)

    assert event.source_url == DOCS_URL


def test_symbol_flag_overrides_the_default():
    args = parse_args(["--symbol", "vendor.Other.method"])

    event = build_change_event(args, clock=frozen_clock)

    assert event.symbol == "vendor.Other.method"
    assert event.symbol != DECLARED_SYMBOL


def test_change_class_flag_overrides_the_default():
    args = parse_args(["--change-class", "signature_changed"])

    event = build_change_event(args, clock=frozen_clock)

    assert event.change_class == "signature_changed"


def test_source_url_flag_overrides_the_default():
    args = parse_args(["--source-url", "https://example.invalid/other"])

    event = build_change_event(args, clock=frozen_clock)

    assert event.source_url == "https://example.invalid/other"


def test_build_change_event_uses_the_injected_clock():
    event = build_change_event(parse_args([]), clock=frozen_clock)

    assert event.detected_at == FROZEN_TIME


# --- build_pr_body is unchanged by the new parameter ---------------------


def test_demo_body_is_identical_with_the_default_and_with_an_explicit_value():
    result = result_fixture(demo_mode=True)

    assert build_pr_body(result) == build_pr_body(result, CHANGE_DESCRIPTION)


def test_live_body_is_identical_with_the_default_and_with_an_explicit_value():
    result = result_fixture(demo_mode=False)

    assert build_pr_body(result) == build_pr_body(result, CHANGE_DESCRIPTION)


def test_a_custom_description_reaches_the_body():
    """Proves the parameter is actually used, so the two tests above are not
    passing merely because the argument is ignored."""
    result = result_fixture()

    body = build_pr_body(result, "A totally different breaking change.")

    assert "A totally different breaking change." in body
    assert CHANGE_DESCRIPTION not in body


# --- utc_now_iso ---------------------------------------------------------


def test_utc_now_iso_returns_a_timezone_aware_utc_iso_string():
    stamp = utc_now_iso()

    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


# --- parse_args with no argv --------------------------------------------


def test_parse_args_with_no_argv_still_yields_the_declared_defaults(monkeypatch):
    """argv=None reads sys.argv, which under pytest holds pytest's own flags, so
    it is replaced with a bare program name first."""
    monkeypatch.setattr("sys.argv", ["src.main"])

    args = parse_args()

    assert args.symbol == DECLARED_SYMBOL
    assert args.change_class == DECLARED_CHANGE_CLASS
    assert args.source_url == DOCS_URL
