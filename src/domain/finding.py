"""Output of the Impact Analysis engine -- Finding, per ADR-0001's shared models.

Where a ChangeEvent affects a specific repository. CodeLocation lives here rather
than in its own module because it is substructure of a Finding, not a
boundary-crossing model in its own right: a location has no identity or lifecycle
outside the Finding that reports it, so it is embedded rather than referenced by
ID.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodeLocation:
    """A single point in the scanned codebase.

    Args:
        file_path: POSIX-form path (forward slashes), relative to the repository.
        line: 1-based line number. Must be >= 1.
        column: 0-based column, or None when the column is not known. Must be
            >= 0 when present.
        snippet: The matched line's text. May be empty -- a blank line is a
            legitimate location.
    """

    file_path: str
    line: int
    column: int | None
    snippet: str

    def __post_init__(self) -> None:
        if not self.file_path.strip():
            raise ValueError(
                f"CodeLocation.file_path must be a non-empty string, "
                f"got {self.file_path!r}"
            )

        # 1-based: line 0 is not a place in a file.
        if self.line < 1:
            raise ValueError(
                f"CodeLocation.line is 1-based and must be >= 1, got {self.line!r}"
            )

        # 0-based, so 0 is valid and only negatives are rejected. None means
        # "column not known" and is distinct from column 0.
        if self.column is not None and self.column < 0:
            raise ValueError(
                f"CodeLocation.column is 0-based and must be >= 0 when given, "
                f"got {self.column!r}"
            )


@dataclass(frozen=True, slots=True)
class Finding:
    """One place in the user's repository affected by one ChangeEvent.

    Args:
        finding_id: Stable identifier for this finding.
        change_event_id: Cross-reference to ChangeEvent.change_event_id. An ID
            string, never an embedded ChangeEvent.
        location: Where in the repository. Embedded, per the module docstring.
        matched_symbol: The literal symbol text found at that location, which may
            differ from the ChangeEvent's symbol (e.g. an aliased import).
    """

    finding_id: str
    change_event_id: str
    location: CodeLocation
    matched_symbol: str

    def __post_init__(self) -> None:
        for name, value in (
            ("finding_id", self.finding_id),
            ("change_event_id", self.change_event_id),
            ("matched_symbol", self.matched_symbol),
        ):
            if not value.strip():
                raise ValueError(
                    f"Finding.{name} must be a non-empty string, got {value!r}"
                )

        # A boundary type, so checked by class rather than duck-typed: anything
        # that merely happens to have .file_path and .line is not a CodeLocation.
        if not isinstance(self.location, CodeLocation):
            raise TypeError(
                f"Finding.location must be a CodeLocation, got "
                f"{type(self.location).__name__}"
            )
