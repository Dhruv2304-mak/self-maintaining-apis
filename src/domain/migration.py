"""Output of the Migration Synthesis engine -- Migration, per ADR-0001's shared models.

An immutable proposal: patch + reasoning + provenance. It records "at this moment,
given this evidence, this is the change we propose" and never changes afterwards.
Everything mutable lives in separate records that reference migration_id --
VerificationReport, TrustAssessment, DeliveryRecord, Outcome.

Five fields are deliberately ABSENT, each an explicit ADR-0001 exclusion rather
than an oversight:

* confidence            -- "confidence ... do not live on the Migration"
* verification_report   -- same sentence; reports reference the migration instead
* affected_files        -- "removed -- derivable from the patch, and duplicated
                           state drifts"
* updated_at            -- "a mutable updated_at implies mutation"
* source_api/target_api -- "referenced by ChangeEvent ID rather than copied",
                           satisfied here by carrying only change_event_id
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    """A proposed fix for one Finding, immutable from creation.

    Args:
        migration_id: Stable identifier for this proposal.
        change_event_id: Cross-reference to the ChangeEvent that produced it.
        finding_id: Cross-reference to the Finding that produced it.
        patch_id: Cross-reference to the Patch carrying the actual change.
        base_commit_hash: The repository commit this proposal was computed
            against -- the commit-level anchor. Per-file anchors live on the
            referenced Patch's FileDiffs, not here.
        migration_class: Categorical label, e.g. "method_rename",
            "parameter_removal". This is what makes historical priors computable,
            so it is required rather than optional. Free-form in this slice.
        model_identity: Which model and version produced this proposal.
        prompt_version: Which prompt version produced it. Together with
            model_identity this is the provenance needed to re-score history.
        reasoning: The natural-language explanation of why the change is correct.
            A first-class deliverable with its own quality bar, not a debug
            string -- so it is required non-empty, at the same validation tier as
            an ID.
        created_at: ISO-8601 timestamp string. Creation-only. There is no
            companion update timestamp, by design.
    """

    migration_id: str
    change_event_id: str
    finding_id: str
    patch_id: str
    base_commit_hash: str
    migration_class: str
    model_identity: str
    prompt_version: str
    reasoning: str
    created_at: str

    def __post_init__(self) -> None:
        # Every field on this model is required non-empty -- including reasoning,
        # per the ADR's elevation of it above a debug string.
        for name, value in (
            ("migration_id", self.migration_id),
            ("change_event_id", self.change_event_id),
            ("finding_id", self.finding_id),
            ("patch_id", self.patch_id),
            ("base_commit_hash", self.base_commit_hash),
            ("migration_class", self.migration_class),
            ("model_identity", self.model_identity),
            ("prompt_version", self.prompt_version),
            ("reasoning", self.reasoning),
            ("created_at", self.created_at),
        ):
            if not value.strip():
                raise ValueError(
                    f"Migration.{name} must be a non-empty string, got {value!r}"
                )
