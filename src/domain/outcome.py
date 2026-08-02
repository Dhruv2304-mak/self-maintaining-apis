"""Terminal record of the Delivery engine -- Outcome, per ADR-0001's shared models.

What the human actually did: merged, modified, reverted, or closed. This is what
feeds calibration, which is why it is captured as its own record rather than as a
status column somewhere.

Frozen like every other model here: a status changing over time produces a NEW
Outcome referencing the same delivery_record_id, never a mutation of an existing
one. This is the same approach VerificationReport and TrustAssessment take to
"many over time" without introducing a mutable field.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Outcome:
    """One observation of what a human did with a delivered pull request.

    Args:
        outcome_id: Stable identifier for this record.
        delivery_record_id: Cross-reference to
            DeliveryRecord.delivery_record_id.
        status: What happened, e.g. "merged", "modified", "reverted", "closed".
            Free-form in this slice, not an enum.
        recorded_at: ISO-8601 timestamp string. Creation-only.
    """

    outcome_id: str
    delivery_record_id: str
    status: str
    recorded_at: str

    def __post_init__(self) -> None:
        for name, value in (
            ("outcome_id", self.outcome_id),
            ("delivery_record_id", self.delivery_record_id),
            ("status", self.status),
            ("recorded_at", self.recorded_at),
        ):
            if not value.strip():
                raise ValueError(
                    f"Outcome.{name} must be a non-empty string, got {value!r}"
                )
