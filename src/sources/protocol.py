"""The source adapter seam: how a change gets into the system.

A source adapter answers one question -- "what changed?" -- and answers it with
:class:`~src.domain.change_event.ChangeEvent` objects. Everything else about a
source is its own business: one adapter reads a declaration made by the
operator, another will scrape a vendor's documentation, a third might consume a
webhook. None of that is visible past this seam.

This is a Protocol rather than a base class on purpose. Structural typing means
a future adapter satisfies this contract by having the right shape, without
importing anything from here and without inheriting from us. That is what makes
the seam genuinely swappable instead of only nominally so.

CONTRACT
--------
Every adapter, now and later, must hold to all six of these:

1. ``fetch_change_events`` returns a tuple, possibly empty. "Nothing found" is
   an empty tuple -- never None, never an exception.
2. Every emitted ChangeEvent's ``source_url`` identifies where that specific
   event actually came from.
3. **No adapter invents a symbol.** An adapter that cannot determine which API
   symbol a change concerns emits no event for it. Silence, not a placeholder.
4. Deterministic: the same inputs and the same clock produce the same output,
   ids included.
5. No side effects. No files written, no pull requests opened, no state mutated
   outside the adapter itself.
6. Ids come from :func:`src.domain.ids.derive_change_event_id`, so that ids
   produced by different adapters are comparable and can be deduplicated.

Rules 3 and 6 are the reason this contract is written before a second adapter
exists. They are the constraints that stop a future documentation scraper from
filling required fields with guesses when extraction fails.
"""

from typing import Protocol, runtime_checkable

from src.domain.change_event import ChangeEvent


@runtime_checkable
class SourceAdapter(Protocol):
    """One place changes can come from."""

    source_name: str
    """Short provenance label, e.g. "declared". Appears in logs and ids."""

    def fetch_change_events(self) -> tuple[ChangeEvent, ...]:
        """Return every change this source currently reports.

        Returns:
            A tuple of ChangeEvent, possibly empty. Never None.
        """
        ...
