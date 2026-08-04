"""The ChangeEvent's symbol drives the scan; --keywords is an opt-in widening.

Why this matters beyond tidiness: a Finding means "one place affected by ONE
ChangeEvent". When the search terms came from a constant unrelated to the event,
every match was stamped with the declared event's id regardless of whether it
had anything to do with that event -- a `requests.get` hit carrying the Stripe
Charge removal's id is a false record, and Steps 4 and 5 consume these.

main() is not called here: it drives the whole pipeline and writes files. These
tests exercise parse_args plus the same term-selection rule main() applies, and
one end-to-end scan over an examples/-shaped tree.
"""

import pytest

import src.main as main_module
from src.core.scanner import CodebaseScanner
from src.main import select_search_terms

pytestmark = pytest.mark.unit

SYMBOL = "stripe.Charge.create"

# Shaped like examples/payment.py: a bare import, then two real call sites.
PAYMENT_LIKE = (
    "import stripe\n"
    "\n"
    "\n"
    "def charge(amount, token):\n"
    "    return stripe.Charge.create(amount=amount, source=token)\n"
    "\n"
    "\n"
    "def charge_again(amount, token):\n"
    "    return stripe.Charge.create(amount=amount, source=token)\n"
)


@pytest.fixture
def event():
    args = main_module.parse_args([])
    return main_module.build_change_event(args, clock=lambda: "2026-08-02T00:00:00Z")


# --- the default path -----------------------------------------------------


def test_keywords_defaults_to_none_rather_than_a_constant():
    """A non-None default would make the symbol-driven path unreachable."""
    assert main_module.parse_args([]).keywords is None


def test_default_search_terms_are_exactly_the_events_symbol(event):
    args = main_module.parse_args([])

    assert select_search_terms(args, event) == [SYMBOL]


def test_main_no_longer_defines_a_keyword_constant():
    """DEFAULT_KEYWORDS was a second, independent answer to "what changed"."""
    assert not hasattr(main_module, "DEFAULT_KEYWORDS")


def test_the_symbol_default_tracks_an_overridden_symbol(event):
    """The default follows the event, not a hardcoded string."""
    args = main_module.parse_args(["--symbol", "vendor.Thing.gone"])
    built = main_module.build_change_event(args, clock=lambda: "2026-08-02T00:00:00Z")

    assert select_search_terms(args, built) == ["vendor.Thing.gone"]


# --- the explicit path ----------------------------------------------------


def test_explicit_keywords_are_used_verbatim(event):
    args = main_module.parse_args(["--keywords", "stripe", "requests.get"])

    assert select_search_terms(args, event) == ["stripe", "requests.get"]


def test_the_symbol_is_not_silently_appended_to_explicit_keywords(event):
    """Widening is the caller's decision; we do not quietly add to it."""
    args = main_module.parse_args(["--keywords", "requests.get"])

    terms = select_search_terms(args, event)

    assert terms == ["requests.get"]
    assert SYMBOL not in terms


def test_a_single_explicit_keyword_is_still_a_list(event):
    args = main_module.parse_args(["--keywords", "stripe"])

    assert select_search_terms(args, event) == ["stripe"]


# --- the printed line matches what was searched ---------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], SYMBOL),
        (["--keywords", "stripe"], "stripe"),
        (["--keywords", "stripe", "requests.get"], "stripe, requests.get"),
    ],
)
def test_the_printed_line_lists_exactly_the_terms_searched(event, argv, expected):
    """One value feeds both the search and the print, so they cannot diverge."""
    args = main_module.parse_args(argv)

    terms = select_search_terms(args, event)

    assert ", ".join(terms) == expected


# --- end to end over examples/-shaped input -------------------------------


def test_a_bare_import_no_longer_matches_but_both_call_sites_do(tmp_path, event):
    """The 3-to-2 drop, asserted directly.

    "import stripe" does not contain the dotted symbol, so it is no longer
    reported. The two lines the fixer actually rewrites still are.
    """
    (tmp_path / "payment.py").write_text(PAYMENT_LIKE, encoding="utf-8")

    findings = CodebaseScanner(str(tmp_path)).scan(event, [event.symbol])

    assert [f.location.line for f in findings] == [5, 9]
    assert all(SYMBOL in f.location.snippet for f in findings)
    assert not any(f.location.snippet == "import stripe" for f in findings)


def test_widening_to_the_package_name_restores_the_import_match(tmp_path, event):
    """Proving the old behaviour is still reachable, just no longer the default."""
    (tmp_path / "payment.py").write_text(PAYMENT_LIKE, encoding="utf-8")

    findings = CodebaseScanner(str(tmp_path)).scan(event, ["stripe"])

    assert [f.location.line for f in findings] == [1, 5, 9]


def test_every_default_path_finding_relates_to_the_event(tmp_path, event):
    """The defect this amendment fixes: no unrelated match carries the event id."""
    (tmp_path / "payment.py").write_text(PAYMENT_LIKE, encoding="utf-8")
    (tmp_path / "http.py").write_text(
        "import requests\nrequests.get('https://example.invalid')\n", encoding="utf-8"
    )

    findings = CodebaseScanner(str(tmp_path)).scan(event, [event.symbol])

    assert findings
    assert all(f.matched_symbol == SYMBOL for f in findings)
    assert not any("requests" in f.location.file_path for f in findings)
