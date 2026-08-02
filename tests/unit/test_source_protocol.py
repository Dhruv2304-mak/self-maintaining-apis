"""Unit tests for the SourceAdapter seam.

The point of a Protocol here is structural typing: an adapter conforms by having
the right shape, without inheriting from us or importing us. These tests check
that the seam actually discriminates -- that a class missing either member is
rejected -- because a protocol that accepts everything documents nothing.

Also covers the two contract rules that are checkable without a second adapter:
rule 5 (no side effects) and rule 6 (ids come from derive_change_event_id).
"""

import pytest

import src.sources.declared as declared_module
from src.domain.ids import derive_change_event_id
from src.sources.declared import SOURCE_NAME, DeclaredSource
from src.sources.protocol import SourceAdapter

pytestmark = pytest.mark.unit

FROZEN_TIME = "2026-08-02T12:00:00+00:00"


def make_source(**overrides):
    """Build a valid DeclaredSource, with named fields replaced."""
    kwargs = {
        "symbol": "vendor.Thing.method",
        "change_class": "removed",
        "description": "A description.",
        "source_url": "https://example.invalid/docs",
        "clock": lambda: FROZEN_TIME,
    }
    kwargs.update(overrides)
    return DeclaredSource(**kwargs)


# --- conformance ---------------------------------------------------------


def test_declared_source_satisfies_the_protocol():
    assert isinstance(make_source(), SourceAdapter)


def test_a_class_missing_fetch_change_events_is_not_an_adapter():
    class NoMethod:
        source_name = "incomplete"

    assert not isinstance(NoMethod(), SourceAdapter)


def test_a_class_missing_source_name_is_not_an_adapter():
    class NoName:
        def fetch_change_events(self):
            return ()

    assert not isinstance(NoName(), SourceAdapter)


def test_an_unrelated_class_is_not_an_adapter():
    class Unrelated:
        pass

    assert not isinstance(Unrelated(), SourceAdapter)


def test_a_foreign_class_conforms_without_inheriting_or_importing():
    """This is what structural typing buys: no base class, no coupling."""

    class ForeignAdapter:
        source_name = "foreign"

        def fetch_change_events(self):
            return ()

    assert isinstance(ForeignAdapter(), SourceAdapter)
    assert SourceAdapter not in ForeignAdapter.__mro__


def test_issubclass_is_unavailable_because_the_protocol_has_a_data_member():
    """Characterization of a typing rule, not a defect.

    `source_name` is a non-method member, so issubclass() is refused while
    isinstance() works. Worth pinning so nobody writes a conformance check on
    issubclass and is surprised.
    """
    with pytest.raises(TypeError, match="non-method members"):
        issubclass(DeclaredSource, SourceAdapter)


def test_source_name_is_declared():
    assert DeclaredSource.source_name == "declared"
    assert make_source().source_name == "declared"
    assert SOURCE_NAME == "declared"


# --- return shape (contract rule 1) --------------------------------------


def test_fetch_change_events_returns_a_tuple():
    result = make_source().fetch_change_events()

    assert isinstance(result, tuple)


def test_fetch_change_events_does_not_return_a_list():
    """Stated separately from the tuple check: a list is the likely mistake, and
    it would pass a truthiness or len() assertion unnoticed."""
    result = make_source().fetch_change_events()

    assert not isinstance(result, list)


# --- contract rule 5: no side effects ------------------------------------


def test_fetching_writes_no_files(tmp_path, monkeypatch):
    """chdir into an empty tmp_path first, so a stray relative-path write would
    land there and be caught rather than going somewhere unnoticed."""
    monkeypatch.chdir(tmp_path)
    assert not any(tmp_path.iterdir())

    make_source().fetch_change_events()

    assert not any(tmp_path.iterdir())


def test_fetching_twice_mutates_nothing_on_the_adapter():
    source = make_source()

    first = source.fetch_change_events()
    second = source.fetch_change_events()

    assert first == second


# --- contract rule 6: ids come from the shared deriver -------------------


def test_the_event_id_equals_the_deriver_called_directly():
    """If the adapter derived ids its own way, cross-adapter deduplication would
    silently stop working."""
    source = make_source()

    event = source.fetch_change_events()[0]

    assert event.change_event_id == derive_change_event_id(
        source_name=source.source_name,
        source_url=source.source_url,
        symbol=source.symbol,
        change_class=source.change_class,
        description=source.description,
    )


def test_the_adapter_module_never_reads_the_clock_itself():
    """Contract rule 4 (determinism) depends on the clock being injected. If
    declared.py imported datetime, it could read the wall clock directly."""
    assert not hasattr(declared_module, "datetime")
