"""Output of the Delivery engine -- DeliveryRecord, per ADR-0001's shared models.

The pull request we opened. Zero or one per migration: if delivery never happened,
no DeliveryRecord exists for that migration at all, so there is no "not delivered"
or otherwise empty representation to model here.

Forge-agnostic. The forge is carried as data rather than assumed, which is what
lets one forge be swapped for another without changing this boundary.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """The record of one delivery of one Migration to a forge.

    Args:
        delivery_record_id: Stable identifier for this record.
        migration_id: Cross-reference to Migration.migration_id.
        assessment_id: Cross-reference to the TrustAssessment whose decision
            authorised this delivery. Delivery is conditional on policy, so the
            authorising assessment is recorded rather than implied.
        forge: Which forge this went to, e.g. "github". Data, not a hardcoded
            assumption.
        external_url: The pull request's URL (or the forge's equivalent).
        opened_at: ISO-8601 timestamp string. Creation-only.
    """

    delivery_record_id: str
    migration_id: str
    assessment_id: str
    forge: str
    external_url: str
    opened_at: str

    def __post_init__(self) -> None:
        for name, value in (
            ("delivery_record_id", self.delivery_record_id),
            ("migration_id", self.migration_id),
            ("assessment_id", self.assessment_id),
            ("forge", self.forge),
            ("external_url", self.external_url),
            ("opened_at", self.opened_at),
        ):
            if not value.strip():
                raise ValueError(
                    f"DeliveryRecord.{name} must be a non-empty string, "
                    f"got {value!r}"
                )
