"""Unit tests for the VerificationReport domain model.

The absence tests here matter as much as the presence ones: verification emits
evidence and never a verdict, so a pass/fail or confidence field appearing on this
model would be the exact mistake ADR-0001's first decision rejects.
"""

import dataclasses

import pytest

from src.domain.verification_report import VerificationReport

pytestmark = pytest.mark.unit

REQUIRED_TEXT_FIELDS = [
    "report_id",
    "migration_id",
    "signal_name",
    "observation",
    "created_at",
]

VERDICT_SHAPED_FIELDS = [
    "passed",
    "failed",
    "success",
    "ok",
    "result",
    "status",
    "verdict",
    "confidence",
]


def make(**overrides):
    """Build a valid VerificationReport, with named fields replaced."""
    kwargs = {
        "report_id": "vr-001",
        "migration_id": "m-001",
        "signal_name": "symbol_check",
        "observation": "stripe.PaymentIntent.create exists in stripe 12.4.0 and "
        "accepts payment_method and confirm.",
        "created_at": "2026-08-02T10:25:00Z",
    }
    kwargs.update(overrides)
    return VerificationReport(**kwargs)


def test_valid_construction_reads_back_every_field():
    report = make()

    assert report.report_id == "vr-001"
    assert report.migration_id == "m-001"
    assert report.signal_name == "symbol_check"
    assert report.observation.startswith("stripe.PaymentIntent.create exists")
    assert report.created_at == "2026-08-02T10:25:00Z"


def test_instance_is_frozen():
    report = make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.observation = "rewritten"


def test_instance_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_TEXT_FIELDS)
def test_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


def test_observation_is_required_because_a_report_that_saw_nothing_is_not_a_report():
    with pytest.raises(ValueError) as excinfo:
        make(observation="   ")

    assert "observation" in str(excinfo.value)


@pytest.mark.parametrize("forbidden", VERDICT_SHAPED_FIELDS)
def test_no_verdict_shaped_or_confidence_field_exists(forbidden):
    """Judgement belongs to Trust & Policy; confidence is calibrated there too."""
    field_names = {f.name for f in dataclasses.fields(VerificationReport)}

    assert forbidden not in field_names


def test_the_field_set_is_exactly_the_five_specified_fields():
    field_names = [f.name for f in dataclasses.fields(VerificationReport)]

    assert field_names == REQUIRED_TEXT_FIELDS


def test_no_field_is_a_boolean_so_nothing_can_be_read_as_pass_or_fail():
    for declared in dataclasses.fields(VerificationReport):
        assert declared.type is not bool
        assert declared.type != "bool"


def test_two_reports_for_one_migration_are_independent_records():
    """A migration verified twice has two reports, not one overwritten field."""
    first = make(report_id="vr-001", created_at="2026-08-02T10:25:00Z")
    second = make(report_id="vr-002", created_at="2026-08-02T11:00:00Z")

    assert first.migration_id == second.migration_id
    assert first.report_id != second.report_id
    assert first.created_at != second.created_at
