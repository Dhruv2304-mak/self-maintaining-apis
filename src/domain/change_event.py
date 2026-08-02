"""Output of the Change Intelligence engine -- ChangeEvent, per ADR-0001's shared models.

What the vendor changed, classified, with provenance. Data only: no fetching, no
normalising, no classifying happens here -- this records the result of that work.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """One detected change in a vendor API.

    Args:
        change_event_id: Stable identifier for this event.
        symbol: The API symbol affected, e.g. "stripe.Charge.create".
        change_class: What kind of change this is, e.g. "removed", "renamed",
            "signature_changed". A free-form string in this slice, not an enum.
        description: Human-readable detail. May be empty.
        source_url: Where the change was detected -- the provenance the ADR
            requires this model to carry.
        detected_at: ISO-8601 timestamp string. Creation-only; nothing here is
            revised after creation, so there is no companion update timestamp.
            This slice does not parse it as a date, only require it to be present.
    """

    change_event_id: str
    symbol: str
    change_class: str
    description: str
    source_url: str
    detected_at: str

    def __post_init__(self) -> None:
        # `description` is deliberately absent: it is the one field permitted to
        # be empty, because a change can be detected without prose attached.
        for name, value in (
            ("change_event_id", self.change_event_id),
            ("symbol", self.symbol),
            ("change_class", self.change_class),
            ("source_url", self.source_url),
            ("detected_at", self.detected_at),
        ):
            if not value.strip():
                raise ValueError(
                    f"ChangeEvent.{name} must be a non-empty string, "
                    f"got {value!r}"
                )
