"""Unit tests for the ChangeEvent domain model.

Tests the model in isolation. Nothing consumes these types yet, so there is
deliberately no test of how an engine would use one.
"""

import dataclasses

import pytest

from src.domain.change_event import ChangeEvent

pytestmark = pytest.mark.unit

REQUIRED_TEXT_FIELDS = [
    "change_event_id",
    "symbol",
    "change_class",
    "source_url",
    "detected_at",
]


def make(**overrides):
    """Build a valid ChangeEvent, with named fields replaced."""
    kwargs = {
        "change_event_id": "ce-001",
        "symbol": "stripe.Charge.create",
        "change_class": "removed",
        "description": "The Charge API was removed in favour of PaymentIntent.",
        "source_url": "https://example.invalid/changelog#charge-removed",
        "detected_at": "2026-08-02T10:15:00Z",
    }
    kwargs.update(overrides)
    return ChangeEvent(**kwargs)


def test_valid_construction_reads_back_every_field():
    event = make()

    assert event.change_event_id == "ce-001"
    assert event.symbol == "stripe.Charge.create"
    assert event.change_class == "removed"
    assert event.description == (
        "The Charge API was removed in favour of PaymentIntent."
    )
    assert event.source_url == "https://example.invalid/changelog#charge-removed"
    assert event.detected_at == "2026-08-02T10:15:00Z"


def test_instance_is_frozen():
    event = make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.symbol = "something.else"


def test_instance_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_TEXT_FIELDS)
def test_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


def test_description_may_be_empty():
    """The one field permitted to be empty: a change can be detected without prose."""
    assert make(description="").description == ""
