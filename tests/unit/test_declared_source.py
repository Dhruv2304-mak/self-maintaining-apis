"""Unit tests for DeclaredSource -- a change asserted by the operator.

The adapter's whole job is to pass the caller's declaration through into a typed
ChangeEvent without inventing anything. So most of these tests are about values
arriving unchanged, and about validation being delegated to ChangeEvent rather
than reimplemented here.
"""

import dataclasses
import inspect

import pytest

from src.domain.change_event import ChangeEvent
from src.sources.declared import SOURCE_NAME, DeclaredSource

pytestmark = pytest.mark.unit

FROZEN_TIME = "2026-08-02T12:00:00+00:00"

SYMBOL = "vendor.Thing.method"
CHANGE_CLASS = "removed"
DESCRIPTION = "Thing.method was removed; use Thing.other instead."
SOURCE_URL = "https://example.invalid/docs"

# Fields ChangeEvent requires to be non-empty. description is excluded on
# purpose -- it is the one field allowed to be blank.
REQUIRED_FIELDS = ["symbol", "change_class", "source_url"]
ALL_INIT_FIELDS = ["symbol", "change_class", "description", "source_url", "clock"]


def frozen_clock():
    return FROZEN_TIME


def make(**overrides):
    """Build a valid DeclaredSource, with named fields replaced."""
    kwargs = {
        "symbol": SYMBOL,
        "change_class": CHANGE_CLASS,
        "description": DESCRIPTION,
        "source_url": SOURCE_URL,
        "clock": frozen_clock,
    }
    kwargs.update(overrides)
    return DeclaredSource(**kwargs)


def fetch_one(**overrides):
    """Fetch and return the single event, for the common case."""
    return make(**overrides).fetch_change_events()[0]


# --- the five inputs map through ----------------------------------------


def test_symbol_maps_through():
    assert fetch_one().symbol == SYMBOL


def test_change_class_maps_through():
    assert fetch_one().change_class == CHANGE_CLASS


def test_description_maps_through():
    assert fetch_one().description == DESCRIPTION


def test_source_url_maps_through():
    assert fetch_one().source_url == SOURCE_URL


def test_clock_maps_through_to_detected_at():
    assert fetch_one().detected_at == FROZEN_TIME


def test_source_url_on_the_event_equals_the_declared_one():
    """Contract rule 2: source_url identifies where this event came from."""
    declared = "https://example.invalid/some/other/page#anchor"

    assert fetch_one(source_url=declared).source_url == declared


# --- shape of the return value ------------------------------------------


def test_exactly_one_event_is_returned():
    """A declaration reports one change; the tuple is for the seam's sake."""
    assert len(make().fetch_change_events()) == 1


def test_the_returned_item_is_a_change_event():
    assert isinstance(fetch_one(), ChangeEvent)


# --- the clock is injected, not read ------------------------------------


def test_the_clock_is_called_exactly_once_per_fetch():
    calls = []

    def counting_clock():
        calls.append(1)
        return FROZEN_TIME

    make(clock=counting_clock).fetch_change_events()

    assert len(calls) == 1


def test_the_clock_is_not_called_during_construction():
    """Construction records the declaration; nothing happens until fetch."""
    calls = []

    make(clock=lambda: calls.append(1) or FROZEN_TIME)

    assert calls == []


def test_two_fetches_with_a_fixed_clock_are_equal():
    """Contract rule 4: same inputs and same clock, same output."""
    source = make()

    assert source.fetch_change_events() == source.fetch_change_events()


def test_no_wall_clock_patching_is_needed_to_get_a_stable_event():
    """The point of injecting the clock: this test freezes time without touching
    datetime, monkeypatch, or any module-level global."""
    event = fetch_one(clock=lambda: "1999-12-31T23:59:59+00:00")

    assert event.detected_at == "1999-12-31T23:59:59+00:00"


def test_the_id_ignores_the_clock():
    """Two observations of the same change are the same change, whenever seen."""
    early = fetch_one(clock=lambda: "2020-01-01T00:00:00+00:00")
    late = fetch_one(clock=lambda: "2030-01-01T00:00:00+00:00")

    assert early.change_event_id == late.change_event_id
    assert early.detected_at != late.detected_at


# --- validation is delegated to ChangeEvent -----------------------------


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", REQUIRED_FIELDS)
def test_an_empty_required_field_raises_value_error(field_name, bad_value):
    """Raised by ChangeEvent, not reimplemented in the adapter."""
    with pytest.raises(ValueError) as excinfo:
        fetch_one(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


def test_validation_happens_at_fetch_time_not_construction_time():
    """Documented behaviour: nothing is validated until fetch."""
    source = make(symbol="   ")

    with pytest.raises(ValueError):
        source.fetch_change_events()


def test_an_empty_description_is_accepted():
    assert fetch_one(description="").description == ""


def test_a_whitespace_only_description_is_accepted():
    assert fetch_one(description="   ").description == "   "


@pytest.mark.parametrize("field_name", ALL_INIT_FIELDS)
def test_none_in_any_field_raises_type_error(field_name):
    """The four strings fail the id's length-prefix step; clock=None fails
    because it is not callable. Both surface as TypeError."""
    with pytest.raises(TypeError):
        fetch_one(**{field_name: None})


# --- constructor contract ------------------------------------------------


def test_init_has_no_default_arguments():
    """A default here would be the module asserting something about the world.
    Every value must be the caller's declaration."""
    parameters = inspect.signature(DeclaredSource.__init__).parameters

    for name, parameter in parameters.items():
        if name == "self":
            continue
        assert parameter.default is inspect.Parameter.empty, (
            f"{name} must not have a default"
        )


def test_init_accepts_exactly_the_five_declared_fields():
    parameters = [
        name
        for name in inspect.signature(DeclaredSource.__init__).parameters
        if name != "self"
    ]

    assert parameters == ALL_INIT_FIELDS


def test_source_name_constant_matches_the_class_attribute():
    assert DeclaredSource.source_name == SOURCE_NAME


# --- the emitted event is immutable -------------------------------------


def test_the_event_is_frozen():
    event = fetch_one()

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.symbol = "something.else"


def test_the_event_has_no_dict_because_slots_are_in_force():
    assert not hasattr(fetch_one(), "__dict__")


def test_the_event_id_is_prefixed_and_nineteen_characters():
    event_id = fetch_one().change_event_id

    assert event_id.startswith("ce-")
    assert len(event_id) == 19
