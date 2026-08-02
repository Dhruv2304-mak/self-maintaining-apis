"""Output of the Verification engine -- VerificationReport, per ADR-0001's shared models.

Evidence from one verification run. Verification returns observations, never a
judgement, so this model deliberately carries NO pass/fail field and NO confidence
score:

* A boolean or enum result would be the verdict-in-verification mistake ADR-0001's
  first decision rejects. A signal's finding goes into `observation` as raw fact,
  and Trust & Policy interprets it.
* Confidence is computed downstream by Trust & Policy, never self-reported here.

A migration may have many reports over time -- one per verification run -- which is
why each carries its own created_at rather than overwriting a field on the
Migration.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """One observation about one Migration, from one verification signal.

    Args:
        report_id: Stable identifier for this report.
        migration_id: Cross-reference to Migration.migration_id.
        signal_name: Which signal produced this, e.g. "symbol_check",
            "static_analysis", "sandboxed_test_execution". Free-form in this slice.
        observation: Raw factual description of what was found. Required
            non-empty: a report that observed nothing is not a report.
        created_at: ISO-8601 timestamp string. Creation-only. Needed per-report so
            many runs against one migration remain orderable.
    """

    report_id: str
    migration_id: str
    signal_name: str
    observation: str
    created_at: str

    def __post_init__(self) -> None:
        for name, value in (
            ("report_id", self.report_id),
            ("migration_id", self.migration_id),
            ("signal_name", self.signal_name),
            ("observation", self.observation),
            ("created_at", self.created_at),
        ):
            if not value.strip():
                raise ValueError(
                    f"VerificationReport.{name} must be a non-empty string, "
                    f"got {value!r}"
                )
