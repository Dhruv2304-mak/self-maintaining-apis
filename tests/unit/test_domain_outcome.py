"""Unit tests for the Outcome domain model."""

import dataclasses

import pytest

from src.domain.outcome import Outcome

pytestmark = pytest.mark.unit

REQUIRED_TEXT_FIELDS = [
    "outcome_id",
    "delivery_record_id",
    "status",
    "recorded_at",
]


def make(**overrides):
    """Build a valid Outcome, with named fields replaced."""
    kwargs = {
        "outcome_id": "o-001",
        "delivery_record_id": "dr-001",
        "status": "merged",
        "recorded_at": "2026-08-02T11:00:00Z",
    }
    kwargs.update(overrides)
    return Outcome(**kwargs)


def test_valid_construction_reads_back_every_field():
    outcome = make()

    assert outcome.outcome_id == "o-001"
    assert outcome.delivery_record_id == "dr-001"
    assert outcome.status == "merged"
    assert outcome.recorded_at == "2026-08-02T11:00:00Z"


def test_instance_is_frozen():
    outcome = make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.status = "reverted"


def test_instance_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_TEXT_FIELDS)
def test_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


@pytest.mark.parametrize("status", ["merged", "modified", "reverted", "closed"])
def test_each_documented_status_is_accepted(status):
    """Free-form string in this slice, so these are examples rather than an enum."""
    assert make(status=status).status == status


def test_a_status_change_over_time_is_a_new_record_not_a_mutation():
    """Frozen, so 'many over time' works the way it does for VerificationReport
    and TrustAssessment: another record against the same delivery."""
    merged = make(outcome_id="o-001", status="merged", recorded_at="2026-08-02T11:00:00Z")
    reverted = make(
        outcome_id="o-002", status="reverted", recorded_at="2026-08-03T09:00:00Z"
    )

    assert merged.delivery_record_id == reverted.delivery_record_id
    assert merged.status == "merged"
    assert reverted.status == "reverted"


def test_the_field_set_is_exactly_the_four_specified_fields():
    field_names = [f.name for f in dataclasses.fields(Outcome)]

    assert field_names == REQUIRED_TEXT_FIELDS


def test_no_mutable_timestamp_field_exists():
    field_names = {f.name for f in dataclasses.fields(Outcome)}

    assert "updated_at" not in field_names
