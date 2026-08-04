"""Deterministic identifier derivation for domain records.

An identifier here is a pure function of the data it identifies. Re-observing
the same change produces the same id, which is what makes deduplication and
snapshot comparison possible later. Nothing random and nothing time-based goes
into an id: a timestamp would make the same observation look like a new one on
every run.
"""

import hashlib

# Length-prefixing each part before joining. A plain separator would let
# ("ab", "c") and ("a", "bc") hash identically; prefixing the length makes the
# encoding unambiguous whatever the parts contain.
_DIGEST_CHARS = 16
_CHANGE_EVENT_PREFIX = "ce-"
_FINDING_PREFIX = "f-"


def _fingerprint(*parts: str) -> str:
    """Hash an ordered list of strings unambiguously.

    Raises:
        TypeError: Any part was not a str. The length-prefix step alone rejects
            values with no ``__len__`` (int, None, float) but silently accepts
            any sized object -- a list, tuple, dict or bytes would each produce
            a digest. Checking the type explicitly closes that gap, so an id can
            only ever be derived from text.
    """
    for part in parts:
        if not isinstance(part, str):
            raise TypeError(
                f"id parts must be str, got {type(part).__name__}: {part!r}"
            )

    encoded = "".join(f"{len(part)}:{part}" for part in parts)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def derive_change_event_id(
    source_name: str,
    source_url: str,
    symbol: str,
    change_class: str,
    description: str,
) -> str:
    """Build the stable id for one observed change.

    Args:
        source_name: Which adapter observed it, e.g. "declared".
        source_url: Where it was observed.
        symbol: The API symbol affected.
        change_class: What kind of change it is.
        description: The human-readable detail. May be empty.

    Returns:
        A "ce-" prefixed identifier. The prefix is not decoration: ids from
        several record types end up side by side in logs and reports, and an
        unlabelled hex string tells a reader nothing.
    """
    digest = _fingerprint(source_name, source_url, symbol, change_class, description)
    return f"{_CHANGE_EVENT_PREFIX}{digest[:_DIGEST_CHARS]}"


def derive_finding_id(
    change_event_id: str,
    file_path: str,
    line: int,
    column: int | None,
    matched_symbol: str,
) -> str:
    """Build the stable id for one place a change affects a repository.

    Args:
        change_event_id: The ChangeEvent this finding was scanned for.
        file_path: POSIX-form path of the matching file.
        line: 1-based line number of the match.
        column: 0-based column of the match, or None when not known.
        matched_symbol: The literal text matched at that location.

    Returns:
        An "f-" prefixed identifier. Rescanning an unchanged repository for the
        same ChangeEvent produces the same finding ids, which is what lets a
        later run tell a new finding from one already seen.

    Raises:
        TypeError: `line` was not an int, or `column` was neither None nor an
            int. Both are rendered to str before :func:`_fingerprint` sees them,
            so its own type check cannot reach them -- without this, passing
            ``line=[1, 2]`` would render "[1, 2]" and return a valid-looking id.

    The numeric parts are rendered as text because :func:`_fingerprint` takes
    only strings. None becomes "none". That sentinel can only collide with a
    literal ``column="none"``, which the type check below rejects -- the check is
    load-bearing for the encoding, not merely defensive. Range checking is
    deliberately absent: CodeLocation.__post_init__ already enforces line >= 1
    and column >= 0, and repeating it here would be two places to keep in step.
    """
    # bool is a subclass of int, so a bare isinstance check would let True
    # through and silently render it as "True".
    if not isinstance(line, int) or isinstance(line, bool):
        raise TypeError(f"line must be an int, got {type(line).__name__}: {line!r}")

    if column is not None and (not isinstance(column, int) or isinstance(column, bool)):
        raise TypeError(
            f"column must be an int or None, got {type(column).__name__}: {column!r}"
        )

    digest = _fingerprint(
        change_event_id,
        file_path,
        str(line),
        "none" if column is None else str(column),
        matched_symbol,
    )
    return f"{_FINDING_PREFIX}{digest[:_DIGEST_CHARS]}"
