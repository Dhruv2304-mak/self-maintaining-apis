"""Output of the Migration Synthesis engine -- Patch, per ADR-0001's shared models.

A structured diff, base-hash anchored, multi-file. This is a data record of an
intended change; it never touches the filesystem. FileDiff lives here rather than
in its own module because it is substructure of a Patch, with no independent
existence outside one.

Anchoring is per-file, via FileDiff.base_file_hash -- the content hash of the base
file each hunk was computed against. There is deliberately no repository-level
hash on Patch: that single commit-level anchor lives on Migration, and duplicating
it here would recreate the duplicated-state problem the ADR cites when removing
`affected files`.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileDiff:
    """One file's structured change within a Patch.

    Args:
        file_path: POSIX-form path (forward slashes) of the file being changed.
        base_file_hash: Content hash of the base file the hunks were computed
            against. Without it a patch cannot be checked for drift, so it is
            required. This slice does not validate the hash's format -- only that
            one was supplied.
        hunks: Ordered sequence of hunks, each a unified-diff hunk fragment (the
            "@@ ... @@" header plus its lines). A tuple, never a list. Must hold
            at least one hunk: a FileDiff with none is not a change.

    A hunk is stored as opaque text and not decomposed further into line ranges
    or per-line objects. "An ordered set of hunks" is the smallest unit ADR-0001
    names, and going below it would be modelling an engine's internals.
    """

    file_path: str
    base_file_hash: str
    hunks: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("file_path", self.file_path),
            ("base_file_hash", self.base_file_hash),
        ):
            if not value.strip():
                raise ValueError(
                    f"FileDiff.{name} must be a non-empty string, got {value!r}"
                )

        # Type before emptiness, deliberately: an empty list must report the
        # wrong-type problem (TypeError), not the empty-sequence one, because
        # `not []` is also true and would otherwise mask it.
        if not isinstance(self.hunks, tuple):
            raise TypeError(
                f"FileDiff.hunks must be a tuple, got {type(self.hunks).__name__}"
            )

        if not self.hunks:
            raise ValueError(
                "FileDiff.hunks must contain at least one hunk; a FileDiff with "
                "no hunks is not a change"
            )


@dataclass(frozen=True, slots=True)
class Patch:
    """A multi-file structured diff produced by Migration Synthesis.

    Args:
        patch_id: Stable identifier for this patch.
        file_diffs: One FileDiff per touched file. A tuple, never a list. Must
            hold at least one entry: a patch changing no files is not meaningful.
            One API change affects many call sites, which is why this is
            multi-file rather than single-file.

    There is no `reversible` flag. Reversibility is a property the base-hash-
    anchored, structured-hunk shape enables, not a fact stored about an instance.
    """

    patch_id: str
    file_diffs: tuple[FileDiff, ...]

    def __post_init__(self) -> None:
        if not self.patch_id.strip():
            raise ValueError(
                f"Patch.patch_id must be a non-empty string, got {self.patch_id!r}"
            )

        # Type before emptiness, for the reason given in FileDiff.__post_init__.
        if not isinstance(self.file_diffs, tuple):
            raise TypeError(
                f"Patch.file_diffs must be a tuple, got "
                f"{type(self.file_diffs).__name__}"
            )

        if not self.file_diffs:
            raise ValueError(
                "Patch.file_diffs must contain at least one FileDiff; a patch "
                "with no file changes is not meaningful"
            )

        for index, file_diff in enumerate(self.file_diffs):
            if not isinstance(file_diff, FileDiff):
                raise TypeError(
                    f"Patch.file_diffs[{index}] must be a FileDiff, got "
                    f"{type(file_diff).__name__}"
                )
