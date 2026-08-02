"""Unit tests for derive_change_event_id -- the identity rule for ChangeEvents.

An id here is a pure function of the data it identifies, which is what makes
deduplication and snapshot comparison possible later. These tests pin that
property from both directions: the same inputs must always agree, and every
input must actually participate in the digest.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.domain.ids import _fingerprint, derive_change_event_id

pytestmark = pytest.mark.unit

VALID = {
    "source_name": "declared",
    "source_url": "https://example.invalid/docs",
    "symbol": "vendor.Thing.method",
    "change_class": "removed",
    "description": "A description.",
}

ID_INPUTS = ["source_name", "source_url", "symbol", "change_class", "description"]

# Inputs and digest for the cross-process test. Hardcoded on purpose: a value
# computed in the test would agree with itself no matter what the function did.
FROZEN_INPUTS = {
    "source_name": "declared",
    "source_url": "https://example.invalid/docs",
    "symbol": "vendor.Thing.method",
    "change_class": "removed",
    "description": "A fixed description for the cross-process test.",
}
FROZEN_DIGEST = "ce-c403fa85b0ebcbf7"

REPO_ROOT = Path(__file__).resolve().parents[2]


def derive(**overrides):
    """Derive an id from the valid baseline, with named inputs replaced."""
    kwargs = dict(VALID)
    kwargs.update(overrides)
    return derive_change_event_id(**kwargs)


# --- determinism --------------------------------------------------------


def test_same_inputs_produce_the_same_id():
    assert derive() == derive()


def test_the_id_does_not_change_across_many_calls():
    assert len({derive() for _ in range(25)}) == 1


# --- every input participates -------------------------------------------


@pytest.mark.parametrize("field_name", ID_INPUTS)
def test_changing_any_single_input_changes_the_id(field_name):
    """If an input did not reach the digest, the id would be blind to it."""
    baseline = derive()

    changed = derive(**{field_name: VALID[field_name] + "-different"})

    assert changed != baseline


def test_all_five_inputs_together_yield_five_distinct_ids():
    """Guards against two inputs being accidentally interchangeable."""
    ids = {derive(**{name: "SENTINEL"}) for name in ID_INPUTS}

    assert len(ids) == len(ID_INPUTS)


# --- shape --------------------------------------------------------------


def test_empty_description_still_yields_an_id():
    """description is the one input allowed to be empty."""
    assert derive(description="")


def test_id_starts_with_the_ce_prefix():
    assert derive().startswith("ce-")


def test_id_is_nineteen_characters():
    """Three characters of prefix plus a 16-character digest."""
    assert len(derive()) == 19


def test_id_body_is_lowercase_hex():
    body = derive()[3:]

    assert all(character in "0123456789abcdef" for character in body)


# --- unambiguous encoding ------------------------------------------------


def test_length_prefixing_prevents_a_boundary_collision():
    """("ab","c") and ("a","bc") must not hash alike.

    A plain separator would let the two join to the same string. Length-
    prefixing each part is what makes the encoding unambiguous.
    """
    left = derive_change_event_id("ab", "c", "s", "k", "d")
    right = derive_change_event_id("a", "bc", "s", "k", "d")

    assert left != right


def test_fingerprint_itself_is_unambiguous_at_the_boundary():
    assert _fingerprint("ab", "c") != _fingerprint("a", "bc")


def test_fingerprint_is_order_sensitive():
    assert _fingerprint("a", "b") != _fingerprint("b", "a")


# --- wrong types ---------------------------------------------------------


@pytest.mark.parametrize("field_name", ID_INPUTS)
def test_a_non_string_input_raises_type_error(field_name):
    """An int has no len(), so the length-prefix step rejects it."""
    with pytest.raises(TypeError):
        derive(**{field_name: 123})


@pytest.mark.parametrize("field_name", ID_INPUTS)
def test_none_input_raises_type_error(field_name):
    with pytest.raises(TypeError):
        derive(**{field_name: None})


def test_a_sized_non_string_is_accepted_rather_than_rejected():
    """Characterization, not endorsement.

    The guard is `len(part)` inside an f-string, so it rejects values with no
    __len__ (int, None, float, bool) but silently accepts any sized object -- a
    list, tuple, dict or bytes all produce an id. Nothing in this slice type-
    checks for str. Pinned so that tightening it later is a visible decision.
    """
    assert derive(symbol=[]) != derive(symbol=())


# --- awkward but legitimate strings --------------------------------------


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("unicode", "café — naïve \U0001f600"),
        ("newlines", "line1\nline2\r\nline3"),
        ("tabs", "a\tb\tc"),
        ("padding", "  padded  "),
    ],
)
def test_awkward_strings_produce_a_stable_id(label, value):
    """Non-ASCII and whitespace must not make the digest wobble."""
    first = derive(description=value)
    second = derive(description=value)

    assert first == second
    assert len(first) == 19


def test_whitespace_is_significant_and_not_stripped():
    """The id identifies the data as given, so padding is part of it."""
    assert derive(description="x") != derive(description=" x ")


# --- across processes ----------------------------------------------------


def test_two_separate_interpreter_runs_agree_with_a_hardcoded_digest():
    """The id must not depend on anything process-local.

    Python randomises str hashing per process (PYTHONHASHSEED), so a digest
    built on hash() rather than sha256 would pass in-process and fail here.
    The expected value is hardcoded rather than recomputed, because a computed
    expectation would agree with a broken implementation.
    """
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from src.domain.ids import derive_change_event_id;"
        f"print(derive_change_event_id(**{FROZEN_INPUTS!r}), end='')"
    )
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "random"

    completed = subprocess.run(
        [sys.executable, "-c", code, str(REPO_ROOT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        check=True,
    )

    assert completed.stdout == FROZEN_DIGEST
    assert derive_change_event_id(**FROZEN_INPUTS) == FROZEN_DIGEST
