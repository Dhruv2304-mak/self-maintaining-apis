"""Unit tests for the DeliveryRecord domain model."""

import dataclasses

import pytest

from src.domain.delivery_record import DeliveryRecord

pytestmark = pytest.mark.unit

REQUIRED_TEXT_FIELDS = [
    "delivery_record_id",
    "migration_id",
    "assessment_id",
    "forge",
    "external_url",
    "opened_at",
]


def make(**overrides):
    """Build a valid DeliveryRecord, with named fields replaced."""
    kwargs = {
        "delivery_record_id": "dr-001",
        "migration_id": "m-001",
        "assessment_id": "ta-001",
        "forge": "github",
        "external_url": "https://github.com/owner/repo/pull/7",
        "opened_at": "2026-08-02T10:40:00Z",
    }
    kwargs.update(overrides)
    return DeliveryRecord(**kwargs)


def test_valid_construction_reads_back_every_field():
    record = make()

    assert record.delivery_record_id == "dr-001"
    assert record.migration_id == "m-001"
    assert record.assessment_id == "ta-001"
    assert record.forge == "github"
    assert record.external_url == "https://github.com/owner/repo/pull/7"
    assert record.opened_at == "2026-08-02T10:40:00Z"


def test_instance_is_frozen():
    record = make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        record.external_url = "https://example.invalid/other"


def test_instance_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_TEXT_FIELDS)
def test_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


@pytest.mark.parametrize("forge", ["github", "gitlab", "gitea", "bitbucket"])
def test_forge_is_data_rather_than_a_hardcoded_assumption(forge):
    """Forge-agnostic: no forge name is privileged by the model."""
    assert make(forge=forge).forge == forge


def test_the_field_set_is_exactly_the_six_specified_fields():
    field_names = [f.name for f in dataclasses.fields(DeliveryRecord)]

    assert field_names == REQUIRED_TEXT_FIELDS


def test_no_field_has_a_default():
    """A DeliveryRecord exists only when delivery happened, so there is no
    'not delivered' representation and nothing to default."""
    for declared in dataclasses.fields(DeliveryRecord):
        assert declared.default is dataclasses.MISSING
        assert declared.default_factory is dataclasses.MISSING
