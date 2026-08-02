"""Output of the Trust & Policy engine -- TrustAssessment, per ADR-0001's shared models.

Calibrated confidence at a point in time, plus the decision that confidence
supports. ADR-0001 describes this engine's output as "TrustAssessment + Decision";
its "Shared models" list enumerates exactly eight models and Decision is not among
them, so the decision is a field here rather than a ninth model.

Confidence is calibrated by this engine. It is never self-reported by a model, and
it deliberately does not appear on Migration or VerificationReport.

No calibration logic lives here -- calibration rules and signal weighting are a
separate future record per ADR-0001's Notes. This model only holds the result.

A migration may have many assessments over time -- one per evaluation -- so each
carries its own assessed_at rather than mutating a shared field.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TrustAssessment:
    """One policy evaluation of one Migration.

    Args:
        assessment_id: Stable identifier for this assessment.
        migration_id: Cross-reference to Migration.migration_id.
        confidence: Calibrated confidence, or None for "unknown". None is
            distinct from a low numeric value: it means no confidence could be
            established, not that confidence is poor. NaN is rejected -- it would
            pass an isinstance(x, float) check while meaning nothing.
        decision: What policy decided, e.g. "deliver", "suppress". Free-form in
            this slice, not an enum.
        policy_reason: Human-readable justification. Required non-empty, because
            this engine owns the user-facing explanation of uncertainty.
        assessed_at: ISO-8601 timestamp string. Creation-only.
        report_ids: Cross-references to VerificationReport.report_id. A tuple,
            never a list. May legitimately be empty: policy can decide with zero
            reports, e.g. when no verification was possible.

    NOTE ON FIELD ORDER: the specification's table lists report_ids third, but it
    is the one field in this slice with a default, and an ordinary dataclass
    requires defaulted fields to follow required ones. It is therefore declared
    last. Nothing else about it changes.
    """

    assessment_id: str
    migration_id: str
    confidence: float | None
    decision: str
    policy_reason: str
    assessed_at: str
    report_ids: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        for name, value in (
            ("assessment_id", self.assessment_id),
            ("migration_id", self.migration_id),
            ("decision", self.decision),
            ("policy_reason", self.policy_reason),
            ("assessed_at", self.assessed_at),
        ):
            if not value.strip():
                raise ValueError(
                    f"TrustAssessment.{name} must be a non-empty string, "
                    f"got {value!r}"
                )

        # None is a valid, meaningful value here, so only a real number is
        # checked. NaN is the one float that must be refused.
        if self.confidence is not None and math.isnan(self.confidence):
            raise ValueError(
                "TrustAssessment.confidence must not be NaN; use None to mean "
                "'unknown'"
            )

        # An empty tuple is fine; a list is not, even an empty one.
        if not isinstance(self.report_ids, tuple):
            raise TypeError(
                f"TrustAssessment.report_ids must be a tuple, got "
                f"{type(self.report_ids).__name__}"
            )
