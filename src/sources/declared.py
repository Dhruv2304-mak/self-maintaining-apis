"""The declared source adapter -- a change asserted by the operator.

This is the first implementation of :class:`~src.sources.protocol.SourceAdapter`
and the simplest one possible: somebody tells us what changed, and we record it
along with where they say it is documented.

That is weaker evidence than reading the vendor's own documentation, and it is
meant to be. It is also honest: the provenance is "an operator asserted this",
which is a real and attributable source rather than a value invented to fill a
required field. A documentation adapter will sit alongside this one later; this
adapter does not go away when it arrives, because a human overriding the
scraper is a legitimate thing to want.

Every value comes from the caller. This module holds no opinion about which API
changed, so nothing here needs editing when the change being tracked is a
different one.
"""

from typing import Callable

from src.domain.change_event import ChangeEvent
from src.domain.ids import derive_change_event_id

SOURCE_NAME = "declared"


class DeclaredSource:
    """A single change, as declared by whoever ran the tool.

    Example:
        source = DeclaredSource(
            symbol="stripe.Charge.create",
            change_class="removed",
            description="The Charge API has been removed...",
            source_url="https://stripe.com/docs/upgrades",
            clock=utc_now_iso,
        )
        events = source.fetch_change_events()
    """

    source_name = SOURCE_NAME

    def __init__(
        self,
        symbol: str,
        change_class: str,
        description: str,
        source_url: str,
        clock: Callable[[], str],
    ) -> None:
        """Record the declaration. Nothing is validated until fetch time.

        Args:
            symbol: The API symbol affected, e.g. "stripe.Charge.create".
            change_class: What kind of change, e.g. "removed".
            description: Human-readable detail. May be empty.
            source_url: Where the change is documented.
            clock: Called with no arguments, returns an ISO-8601 timestamp.
                Injected rather than read from the system so that the same
                declaration produces the same event under test.

        Note:
            No argument has a default. A default here would be this module
            making a claim about the world, which is exactly what it must not
            do -- every value is the caller's assertion, not ours.
        """
        self.symbol = symbol
        self.change_class = change_class
        self.description = description
        self.source_url = source_url
        self.clock = clock

    def fetch_change_events(self) -> tuple[ChangeEvent, ...]:
        """Build the one ChangeEvent this declaration describes.

        Returns:
            A tuple holding exactly one ChangeEvent. It is a tuple rather than
            a bare event because the seam is shaped for sources that report
            many changes; a declaration simply happens to report one.

        Raises:
            ValueError: A required field was empty or whitespace-only. Raised
                by ChangeEvent itself, not re-implemented here.
            TypeError: A field was not a string.
        """
        event = ChangeEvent(
            change_event_id=derive_change_event_id(
                source_name=self.source_name,
                source_url=self.source_url,
                symbol=self.symbol,
                change_class=self.change_class,
                description=self.description,
            ),
            symbol=self.symbol,
            change_class=self.change_class,
            description=self.description,
            source_url=self.source_url,
            detected_at=self.clock(),
        )
        return (event,)
