"""Demo-mode substitution.

Every test here uses demo_mode=True: no client is built and no request is made.
The root conftest also scrubs ANTHROPIC_API_KEY and tests/unit/conftest.py stops
fixer.py's own load_dotenv from repopulating it.
"""

import pytest

from src.core.fixer import DEMO_NEW_CALL, DEMO_OLD_CALL, CodeFixer

pytestmark = pytest.mark.unit

BANNER_START = "# NOTE: produced by CodeFixer demo mode"


@pytest.fixture
def fixer():
    return CodeFixer(demo_mode=True)


def test_charge_create_becomes_payment_intent_create(fixer):
    result = fixer.fix_code("stripe.Charge.create(amount=1)\n", "Charge removed.")

    assert result == "stripe.PaymentIntent.create(amount=1)\n"


def test_surrounding_code_is_untouched(fixer):
    source = "import stripe\n\nx = 1\nstripe.Charge.create(amount=1)\nreturn x\n"

    result = fixer.fix_code(source, "Charge removed.")

    assert result.splitlines()[0] == "import stripe"
    assert "x = 1" in result
    assert result.splitlines()[-1] == "return x"


def test_multiple_occurrences_are_all_substituted(fixer):
    source = "a = stripe.Charge.create(1)\nb = stripe.Charge.create(2)\n"

    result = fixer.fix_code(source, "Charge removed.")

    assert result.count(DEMO_NEW_CALL) == 2
    assert DEMO_OLD_CALL not in result


def test_source_argument_is_renamed_and_confirm_added(fixer):
    result = fixer.fix_code("stripe.Charge.create(source=tok)\n", "Charge removed.")

    assert "payment_method=tok" in result
    assert "confirm=True" in result
    assert "source=tok" not in result


def test_multiline_source_argument_becomes_two_lines(fixer):
    source = "stripe.Charge.create(\n    amount=1,\n    source=tok,\n)\n"

    result = fixer.fix_code(source, "Charge removed.")

    assert "payment_method=tok,  # renamed from `source`" in result
    assert "confirm=True,  # charge now, like Charge.create did" in result


def test_single_line_source_arg_keeps_its_trailing_comment(fixer):
    source = "stripe.Charge.create(source=tok)  # legacy token\n"

    result = fixer.fix_code(source, "Charge removed.")

    assert "payment_method=tok" in result
    assert "confirm=True" in result
    assert "# legacy token" in result


def test_source_value_running_to_end_of_line_is_still_renamed(fixer):
    """No closing bracket or comma after the value -- the scan just runs out."""
    source = "stripe.Charge.create(\n    source=tok\n"

    result = fixer.fix_code(source, "Charge removed.")

    assert "payment_method=tok" in result


def test_input_with_no_occurrences_gets_the_demo_banner(fixer):
    """Characterization: 'unchanged' means unchanged CODE, plus a banner.

    The spec expected untouched input. The fixer instead prepends an honest
    three-line notice, because demo mode does not know how to fix this and says
    so rather than implying it did something.
    """
    result = fixer.fix_code("x = 1\n", "Some unrelated change.")

    assert result.startswith(BANNER_START)
    assert result.endswith("x = 1\n")


def test_running_twice_is_not_idempotent(fixer):
    """Characterization, and a real wart.

    The spec expected idempotence. After the first pass the code no longer
    contains stripe.Charge.create, so the second pass takes the "I don't know
    this change" branch and prepends the demo banner. Re-running the fixer on
    its own output therefore keeps accreting banners. Flagged in the summary.
    """
    once = fixer.fix_code("stripe.Charge.create(a=1)\n", "Charge removed.")
    twice = fixer.fix_code(once, "Charge removed.")

    assert once == "stripe.PaymentIntent.create(a=1)\n"
    assert twice.startswith(BANNER_START)
    assert twice.endswith("stripe.PaymentIntent.create(a=1)\n")


def test_the_code_itself_is_stable_across_a_second_pass(fixer):
    """The substitution does not re-fire; only the banner is added."""
    once = fixer.fix_code("stripe.Charge.create(a=1)\n", "Charge removed.")
    twice = fixer.fix_code(once, "Charge removed.")

    assert twice.count(DEMO_NEW_CALL) == 1
    assert "PaymentIntentIntent" not in twice


def test_banner_names_the_reported_change(fixer):
    result = fixer.fix_code("x = 1\n", "Widgets API retired.\nSecond line ignored.")

    assert "# Reported change: Widgets API retired." in result


def test_banner_falls_back_when_the_description_is_blank(fixer):
    result = fixer.fix_code("x = 1\n", "   ")

    assert "# Reported change: unspecified change" in result


def test_prose_mangling_is_deliberate_and_pinned(fixer):
    """CHARACTERIZATION -- this asserts known-bad output on purpose.

    Demo mode is a blind string substitution, so it rewrites a sentence into one
    that contradicts itself: "still uses the old Charges API, which was removed"
    becomes "...the modern PaymentIntents API, which was removed". This is
    documented intended behaviour -- see README.md, "A note on demo mode".

    If you made the fixer smarter and this test failed, you changed a documented
    property. Update the README first, then this test. Do not "fix" the mangling.
    """
    source = (
        "def charge():\n"
        '    """Still uses the old Charges API, which was removed."""\n'
        "    return stripe.Charge.create(amount=1)\n"
    )

    result = fixer.fix_code(source, "Charge removed.")

    assert "modern PaymentIntents API, which was removed" in result
    assert "old Charges API" not in result


def test_prose_mangling_only_fires_when_real_code_is_present(fixer):
    """The mangling needs stripe.Charge.create in the input to reach that branch.

    A docstring alone routes to the banner fallback and is left intact -- which
    is why the test above includes a real call.
    """
    source = '"""Still uses the old Charges API, which was removed."""\n'

    result = fixer.fix_code(source, "Charge removed.")

    assert "old Charges API" in result
    assert result.startswith(BANNER_START)


def test_empty_code_returns_an_error_string(fixer):
    assert fixer.fix_code("", "c") == "ERROR: No code was provided to fix."


def test_whitespace_only_code_returns_an_error_string(fixer):
    assert fixer.fix_code("   \n\t\n", "c") == "ERROR: No code was provided to fix."


def test_fix_code_always_returns_a_string(fixer):
    for source in ["stripe.Charge.create(1)\n", "x = 1\n", ""]:
        assert isinstance(fixer.fix_code(source, "c"), str)


def test_demo_mode_builds_no_client(fixer):
    assert fixer.demo_mode is True
    assert fixer._client is None


def test_demo_reason_records_an_explicit_request(fixer):
    assert fixer.demo_reason == "demo_mode=True was requested"


def test_missing_api_key_forces_demo_mode(monkeypatch):
    """The scrubbed environment must not produce a live client."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    built = CodeFixer()

    assert built.demo_mode is True
    assert built._client is None
    assert built.demo_reason == "no ANTHROPIC_API_KEY was found"
