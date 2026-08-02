"""Unit tests for the Finding domain model and its embedded CodeLocation."""

import dataclasses

import pytest

from src.domain.finding import CodeLocation, Finding

pytestmark = pytest.mark.unit

FINDING_REQUIRED_TEXT_FIELDS = ["finding_id", "change_event_id", "matched_symbol"]


def make_location(**overrides):
    """Build a valid CodeLocation, with named fields replaced."""
    kwargs = {
        "file_path": "examples/payment.py",
        "line": 12,
        "column": 4,
        "snippet": "    return stripe.Charge.create(amount=amount)",
    }
    kwargs.update(overrides)
    return CodeLocation(**kwargs)


def make_finding(**overrides):
    """Build a valid Finding, with named fields replaced."""
    kwargs = {
        "finding_id": "f-001",
        "change_event_id": "ce-001",
        "location": make_location(),
        "matched_symbol": "stripe.Charge.create",
    }
    kwargs.update(overrides)
    return Finding(**kwargs)


# --- CodeLocation -------------------------------------------------------


def test_location_valid_construction_reads_back_every_field():
    location = make_location()

    assert location.file_path == "examples/payment.py"
    assert location.line == 12
    assert location.column == 4
    assert location.snippet == "    return stripe.Charge.create(amount=amount)"


def test_location_is_frozen():
    location = make_location()

    with pytest.raises(dataclasses.FrozenInstanceError):
        location.line = 99


def test_location_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make_location(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_location_file_path_rejects_empty_or_whitespace(bad_value):
    with pytest.raises(ValueError) as excinfo:
        make_location(file_path=bad_value)

    assert "file_path" in str(excinfo.value)


@pytest.mark.parametrize("bad_line", [0, -1, -100])
def test_location_line_below_one_is_rejected(bad_line):
    """Lines are 1-based, so 0 is not a place in a file."""
    with pytest.raises(ValueError) as excinfo:
        make_location(line=bad_line)

    assert "line" in str(excinfo.value)


def test_location_line_one_is_accepted_as_the_boundary():
    assert make_location(line=1).line == 1


@pytest.mark.parametrize("bad_column", [-1, -50])
def test_location_negative_column_is_rejected(bad_column):
    with pytest.raises(ValueError) as excinfo:
        make_location(column=bad_column)

    assert "column" in str(excinfo.value)


def test_location_column_zero_is_accepted_because_columns_are_zero_based():
    assert make_location(column=0).column == 0


def test_location_column_none_means_unknown_and_is_accepted():
    assert make_location(column=None).column is None


def test_location_snippet_may_be_empty_because_a_blank_line_is_a_location():
    assert make_location(snippet="").snippet == ""


# --- Finding ------------------------------------------------------------


def test_finding_valid_construction_reads_back_every_field():
    location = make_location()
    finding = make_finding(location=location)

    assert finding.finding_id == "f-001"
    assert finding.change_event_id == "ce-001"
    assert finding.location is location
    assert finding.matched_symbol == "stripe.Charge.create"


def test_finding_is_frozen():
    finding = make_finding()

    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.matched_symbol = "other"


def test_finding_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make_finding(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", FINDING_REQUIRED_TEXT_FIELDS)
def test_finding_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make_finding(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


@pytest.mark.parametrize(
    "not_a_location",
    [
        "examples/payment.py",
        {"file_path": "examples/payment.py", "line": 12},
        12,
        None,
        ("examples/payment.py", 12),
    ],
)
def test_finding_location_must_be_a_code_location_instance(not_a_location):
    """A boundary type, checked by class rather than duck-typed."""
    with pytest.raises(TypeError) as excinfo:
        make_finding(location=not_a_location)

    assert "CodeLocation" in str(excinfo.value)


def test_finding_rejects_a_lookalike_that_merely_has_the_right_attributes():
    """Proves the check is isinstance, not attribute sniffing."""

    class NotACodeLocation:
        file_path = "examples/payment.py"
        line = 12
        column = 4
        snippet = ""

    with pytest.raises(TypeError):
        make_finding(location=NotACodeLocation())
