"""Unit tests for derive_finding_id and the str type check in _fingerprint.

The type check is shared: it guards every id deriver, so tightening it here is
what stops a list or a dict from ever producing an id that looks valid.
"""

import pytest

from src.domain.ids import _fingerprint, derive_change_event_id, derive_finding_id

pytestmark = pytest.mark.unit

VALID = {
    "change_event_id": "ce-testtesttesttes",
    "file_path": "examples/payment.py",
    "line": 25,
    "column": 11,
    "matched_symbol": "stripe.Charge.create",
}


def derive(**overrides):
    kwargs = dict(VALID)
    kwargs.update(overrides)
    return derive_finding_id(**kwargs)


# --- shape ---------------------------------------------------------------


def test_id_starts_with_the_f_prefix():
    assert derive().startswith("f-")


def test_id_is_eighteen_characters():
    """Two characters of prefix plus a 16-character digest."""
    assert len(derive()) == 18


def test_id_body_is_lowercase_hex():
    assert all(character in "0123456789abcdef" for character in derive()[2:])


def test_the_finding_prefix_cannot_be_confused_with_a_change_event_id():
    """Prefixes exist so the two are distinguishable side by side in a log."""
    finding_id = derive()
    event_id = derive_change_event_id("declared", "u", "s", "c", "d")

    assert not finding_id.startswith(event_id[:3])
    assert not event_id.startswith(finding_id[:2])


# --- determinism and participation ---------------------------------------


def test_same_inputs_produce_the_same_id():
    assert derive() == derive()


@pytest.mark.parametrize(
    ("field_name", "different"),
    [
        ("change_event_id", "ce-somethingelse1"),
        ("file_path", "examples/other.py"),
        ("line", 26),
        ("column", 12),
        ("matched_symbol", "stripe.Refund.create"),
    ],
)
def test_changing_any_single_input_changes_the_id(field_name, different):
    assert derive(**{field_name: different}) != derive()


def test_all_five_inputs_yield_five_distinct_ids():
    """Guards against two inputs being accidentally interchangeable."""
    ids = {
        derive(change_event_id="ce-x"),
        derive(file_path="x"),
        derive(line=999),
        derive(column=999),
        derive(matched_symbol="x"),
    }

    assert len(ids) == 5


# --- the None column ------------------------------------------------------


def test_a_none_column_is_accepted():
    """None means "column not known", which is a legitimate CodeLocation state."""
    assert derive(column=None).startswith("f-")


def test_none_column_differs_from_every_numeric_column():
    none_id = derive(column=None)

    assert none_id != derive(column=0)
    assert none_id != derive(column=11)


def test_none_column_cannot_collide_with_a_stringified_int():
    """None is rendered "none", which no str(int) can equal."""
    assert derive(column=None) == derive(column=None)


# --- the numeric half of the type guard ----------------------------------


@pytest.mark.parametrize("bad", ["1", 1.5, [1], {"a": 1}, b"1", None, True, False])
def test_line_rejects_every_non_int(bad):
    """line and column are rendered to str before _fingerprint sees them, so its
    own type check cannot reach them. Without this guard, line=[1, 2] renders
    "[1, 2]" and returns a perfectly valid-looking id."""
    with pytest.raises(TypeError, match="line must be an int"):
        derive(line=bad)


@pytest.mark.parametrize("bad", ["1", 1.5, [1], {"a": 1}, b"1", True, False])
def test_column_rejects_every_non_int_except_none(bad):
    with pytest.raises(TypeError, match="column must be an int or None"):
        derive(column=bad)


@pytest.mark.parametrize("field_name", ["line", "column"])
def test_bool_is_rejected_despite_being_an_int_subclass(field_name):
    """A bare isinstance(x, int) check would let True through and render "True"."""
    with pytest.raises(TypeError):
        derive(**{field_name: True})


@pytest.mark.parametrize(
    ("field_name", "bad", "type_name"),
    [("line", [1, 2], "list"), ("column", "0", "str"), ("line", 1.5, "float")],
)
def test_the_numeric_type_error_names_the_offending_type(field_name, bad, type_name):
    with pytest.raises(TypeError) as excinfo:
        derive(**{field_name: bad})

    assert type_name in str(excinfo.value)


def test_a_string_column_cannot_collide_with_the_none_sentinel():
    """The type check is what closes the sentinel collision, not the encoding.

    None is rendered as the literal "none", so a caller passing column="none"
    would otherwise produce the same digest as column=None. Rejecting str is
    therefore load-bearing for the encoding's unambiguity, not merely defensive.
    Relaxing the check reopens the collision.
    """
    with pytest.raises(TypeError, match="column must be an int or None"):
        derive(column="none")


def test_zero_is_a_valid_column_and_is_not_confused_with_none():
    """0 is falsy, so a truthiness check here would misread it as absent."""
    assert derive(column=0) != derive(column=None)
    assert derive(column=0).startswith("f-")


# --- line and column are rendered distinctly ------------------------------


def test_line_and_column_are_not_interchangeable():
    """Swapping them must change the id, or the digest is blind to which is which."""
    swapped = derive(line=VALID["column"], column=VALID["line"])

    assert swapped != derive()


def test_a_multi_digit_boundary_does_not_collide():
    """Length-prefixing protects the numeric parts too: (1, 23) != (12, 3)."""
    assert derive(line=1, column=23) != derive(line=12, column=3)


# --- the shared str type check --------------------------------------------


@pytest.mark.parametrize("bad", [123, None, 1.5, True, [], (), {}, b"x", set()])
def test_fingerprint_rejects_every_non_string_part(bad):
    with pytest.raises(TypeError, match="must be str"):
        _fingerprint("ok", bad)


@pytest.mark.parametrize("bad", [[], {}, b"x"])
def test_a_sized_non_string_is_rejected_by_both_derivers(bad):
    """The gap the isinstance check closed: sized objects used to pass."""
    with pytest.raises(TypeError):
        derive(file_path=bad)
    with pytest.raises(TypeError):
        derive_change_event_id("declared", "u", bad, "c", "d")


def test_the_error_names_the_offending_type():
    """An actionable message beats a bare TypeError from deep inside hashlib."""
    with pytest.raises(TypeError) as excinfo:
        _fingerprint("ok", ["a", "b"])

    assert "list" in str(excinfo.value)


def test_the_check_happens_before_hashing():
    """Nothing should be hashed if any part is invalid.

    A bad part late in the list must still be rejected, which only happens if
    every part is checked up front rather than as it is encoded.
    """
    with pytest.raises(TypeError):
        _fingerprint("a", "b", "c", "d", 5)


def test_a_str_subclass_is_still_accepted():
    """isinstance, not type equality -- a str subclass is still text."""

    class PathLike(str):
        pass

    assert derive(file_path=PathLike("examples/payment.py")) == derive()
