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


def _fingerprint(*parts: str) -> str:
    """Hash an ordered list of strings unambiguously."""
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
