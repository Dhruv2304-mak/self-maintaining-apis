"""Unit tests for the TrustAssessment domain model.

This is the only model in the slice with a defaulted field, so the default gets
its own test, kept distinct from passing an explicit empty tuple.
"""

import dataclasses
import math

import pytest

from src.domain.trust_assessment import TrustAssessment

pytestmark = pytest.mark.unit

REQUIRED_TEXT_FIELDS = [
    "assessment_id",
    "migration_id",
    "decision",
    "policy_reason",
    "assessed_at",
]


def make(**overrides):
    """Build a valid TrustAssessment, with named fields replaced."""
    kwargs = {
        "assessment_id": "ta-001",
        "migration_id": "m-001",
        "confidence": 0.82,
        "decision": "deliver",
        "policy_reason": "Symbol check passed and the diff is three lines, within "
        "the expected size for a method rename.",
        "assessed_at": "2026-08-02T10:30:00Z",
        "report_ids": ("vr-001", "vr-002"),
    }
    kwargs.update(overrides)
    return TrustAssessment(**kwargs)


def test_valid_construction_reads_back_every_field():
    assessment = make()

    assert assessment.assessment_id == "ta-001"
    assert assessment.migration_id == "m-001"
    assert assessment.confidence == 0.82
    assert assessment.decision == "deliver"
    assert assessment.policy_reason.startswith("Symbol check passed")
    assert assessment.assessed_at == "2026-08-02T10:30:00Z"
    assert assessment.report_ids == ("vr-001", "vr-002")


def test_instance_is_frozen():
    assessment = make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        assessment.decision = "suppress"


def test_instance_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_TEXT_FIELDS)
def test_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


# --- confidence ---------------------------------------------------------


def test_confidence_none_means_unknown_and_is_accepted():
    """None is distinct from a low value: it means no confidence was established."""
    assert make(confidence=None).confidence is None


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, -1.0, 2.5])
def test_confidence_accepts_real_numbers_including_out_of_range_ones(value):
    """This slice validates shape, not range: no 0.0-1.0 rule is specified."""
    assert make(confidence=value).confidence == value


def test_confidence_nan_is_rejected():
    """NaN would pass an isinstance(x, float) check while meaning nothing."""
    with pytest.raises(ValueError) as excinfo:
        make(confidence=float("nan"))

    assert "NaN" in str(excinfo.value)


def test_confidence_nan_via_math_nan_is_also_rejected():
    with pytest.raises(ValueError):
        make(confidence=math.nan)


@pytest.mark.parametrize("infinity", [float("inf"), float("-inf")])
def test_infinity_is_not_rejected_because_only_nan_is_specified(infinity):
    """Characterization: the spec names NaN only, so infinities pass. Pinned so a
    later change to that rule is a visible decision rather than a silent one."""
    assert make(confidence=infinity).confidence == infinity


# --- report_ids ---------------------------------------------------------


def test_report_ids_defaults_to_an_empty_tuple_when_not_passed():
    """The one default in the whole slice."""
    assessment = TrustAssessment(
        assessment_id="ta-002",
        migration_id="m-001",
        confidence=None,
        decision="suppress",
        policy_reason="No verification was possible in this environment.",
        assessed_at="2026-08-02T10:35:00Z",
    )

    assert assessment.report_ids == ()


def test_report_ids_explicit_empty_tuple_is_accepted():
    """Distinct case from the default: policy may decide with zero reports."""
    assert make(report_ids=()).report_ids == ()


def test_report_ids_as_a_list_is_rejected():
    with pytest.raises(TypeError) as excinfo:
        make(report_ids=["vr-001"])

    assert "tuple" in str(excinfo.value)


def test_report_ids_as_an_empty_list_is_still_rejected():
    """An empty tuple is fine; an empty list is not."""
    with pytest.raises(TypeError):
        make(report_ids=[])


@pytest.mark.parametrize("not_a_tuple", ["vr-001", {"vr-001"}, None, 1])
def test_report_ids_must_be_a_tuple(not_a_tuple):
    with pytest.raises(TypeError):
        make(report_ids=not_a_tuple)


# --- field shape --------------------------------------------------------


def test_confidence_and_decision_both_exist_on_this_model():
    """Both belong here, unlike on Migration or VerificationReport."""
    field_names = {f.name for f in dataclasses.fields(TrustAssessment)}

    assert "confidence" in field_names
    assert "decision" in field_names


def test_report_ids_is_the_only_field_with_a_default():
    defaulted = [
        f.name
        for f in dataclasses.fields(TrustAssessment)
        if f.default is not dataclasses.MISSING
        or f.default_factory is not dataclasses.MISSING
    ]

    assert defaulted == ["report_ids"]
