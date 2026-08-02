"""Unit tests for the Migration domain model.

Includes tests asserting the ABSENCE of five fields. Those are explicit ADR-0001
exclusions, and a test that pins an absence is the only thing that stops a later
change from quietly reintroducing them.
"""

import dataclasses

import pytest

from src.domain.migration import Migration

pytestmark = pytest.mark.unit

REQUIRED_TEXT_FIELDS = [
    "migration_id",
    "change_event_id",
    "finding_id",
    "patch_id",
    "base_commit_hash",
    "migration_class",
    "model_identity",
    "prompt_version",
    "reasoning",
    "created_at",
]

FORBIDDEN_FIELDS = [
    "confidence",
    "verification_report",
    "verification_reports",
    "affected_files",
    "updated_at",
    "source_api",
    "target_api",
]


def make(**overrides):
    """Build a valid Migration, with named fields replaced."""
    kwargs = {
        "migration_id": "m-001",
        "change_event_id": "ce-001",
        "finding_id": "f-001",
        "patch_id": "p-001",
        "base_commit_hash": "9089a8d8d4bb93259c9b9c4f9e585595cefc203c",
        "migration_class": "method_rename",
        "model_identity": "claude-sonnet-5",
        "prompt_version": "v3",
        "reasoning": "Charge.create was removed; PaymentIntent.create is the "
        "documented replacement and takes payment_method rather than source.",
        "created_at": "2026-08-02T10:20:00Z",
    }
    kwargs.update(overrides)
    return Migration(**kwargs)


def test_valid_construction_reads_back_every_field():
    migration = make()

    assert migration.migration_id == "m-001"
    assert migration.change_event_id == "ce-001"
    assert migration.finding_id == "f-001"
    assert migration.patch_id == "p-001"
    assert migration.base_commit_hash == "9089a8d8d4bb93259c9b9c4f9e585595cefc203c"
    assert migration.migration_class == "method_rename"
    assert migration.model_identity == "claude-sonnet-5"
    assert migration.prompt_version == "v3"
    assert migration.reasoning.startswith("Charge.create was removed")
    assert migration.created_at == "2026-08-02T10:20:00Z"


def test_instance_is_frozen():
    migration = make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        migration.reasoning = "rewritten after the fact"


def test_instance_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_TEXT_FIELDS)
def test_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


def test_reasoning_is_required_at_the_same_tier_as_an_id():
    """Reasoning is a first-class deliverable, not a debug string, so an empty
    one is refused exactly as an empty ID would be."""
    with pytest.raises(ValueError) as excinfo:
        make(reasoning="")

    assert "reasoning" in str(excinfo.value)


@pytest.mark.parametrize("forbidden", FORBIDDEN_FIELDS)
def test_forbidden_field_is_absent(forbidden):
    """Each of these is an explicit ADR-0001 exclusion, not an oversight."""
    field_names = {f.name for f in dataclasses.fields(Migration)}

    assert forbidden not in field_names


def test_the_field_set_is_exactly_the_ten_specified_fields():
    """Guards both directions at once: nothing missing, nothing extra."""
    field_names = [f.name for f in dataclasses.fields(Migration)]

    assert field_names == REQUIRED_TEXT_FIELDS


def test_no_field_has_a_default():
    """Every Migration field is required; the slice's only default is elsewhere."""
    for declared in dataclasses.fields(Migration):
        assert declared.default is dataclasses.MISSING
        assert declared.default_factory is dataclasses.MISSING
