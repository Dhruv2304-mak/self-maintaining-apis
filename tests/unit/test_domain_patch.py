"""Unit tests for the Patch domain model and its embedded FileDiff."""

import dataclasses

import pytest

from src.domain.patch import FileDiff, Patch

pytestmark = pytest.mark.unit

HUNK = (
    "@@ -10,3 +10,4 @@\n"
    "-    return stripe.Charge.create(amount=amount, source=token)\n"
    "+    return stripe.PaymentIntent.create(\n"
    "+        amount=amount, payment_method=token, confirm=True\n"
    "+    )\n"
)
SECOND_HUNK = "@@ -30,1 +31,1 @@\n-# old Charges API\n+# modern PaymentIntents API\n"

FILE_DIFF_REQUIRED_TEXT_FIELDS = ["file_path", "base_file_hash"]


def make_file_diff(**overrides):
    """Build a valid FileDiff, with named fields replaced."""
    kwargs = {
        "file_path": "examples/payment.py",
        "base_file_hash": "e3b0c44298fc1c149afbf4c8996fb924",
        "hunks": (HUNK,),
    }
    kwargs.update(overrides)
    return FileDiff(**kwargs)


def make_patch(**overrides):
    """Build a valid Patch, with named fields replaced."""
    kwargs = {
        "patch_id": "p-001",
        "file_diffs": (make_file_diff(),),
    }
    kwargs.update(overrides)
    return Patch(**kwargs)


# --- FileDiff -----------------------------------------------------------


def test_file_diff_valid_construction_reads_back_every_field():
    file_diff = make_file_diff()

    assert file_diff.file_path == "examples/payment.py"
    assert file_diff.base_file_hash == "e3b0c44298fc1c149afbf4c8996fb924"
    assert file_diff.hunks == (HUNK,)


def test_file_diff_preserves_hunk_order():
    """Hunks are an ordered sequence, so order must survive construction."""
    file_diff = make_file_diff(hunks=(HUNK, SECOND_HUNK))

    assert file_diff.hunks == (HUNK, SECOND_HUNK)
    assert file_diff.hunks[0] == HUNK


def test_file_diff_is_frozen():
    file_diff = make_file_diff()

    with pytest.raises(dataclasses.FrozenInstanceError):
        file_diff.file_path = "other.py"


def test_file_diff_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make_file_diff(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field_name", FILE_DIFF_REQUIRED_TEXT_FIELDS)
def test_file_diff_required_field_rejects_empty_or_whitespace(field_name, bad_value):
    with pytest.raises(ValueError) as excinfo:
        make_file_diff(**{field_name: bad_value})

    assert field_name in str(excinfo.value)


def test_file_diff_empty_hunks_tuple_is_rejected():
    """A FileDiff with no hunks is not a change."""
    with pytest.raises(ValueError) as excinfo:
        make_file_diff(hunks=())

    assert "hunks" in str(excinfo.value)


def test_file_diff_hunks_as_a_list_is_rejected():
    with pytest.raises(TypeError) as excinfo:
        make_file_diff(hunks=[HUNK])

    assert "tuple" in str(excinfo.value)


def test_file_diff_empty_list_of_hunks_reports_the_type_problem_not_the_empty_one():
    """Type is checked first, so an empty list is a TypeError rather than a
    ValueError -- `not []` is true and would otherwise mask the wrong type."""
    with pytest.raises(TypeError):
        make_file_diff(hunks=[])


@pytest.mark.parametrize("not_a_tuple", [HUNK, {HUNK}, None, 3])
def test_file_diff_hunks_must_be_a_tuple(not_a_tuple):
    with pytest.raises(TypeError):
        make_file_diff(hunks=not_a_tuple)


# --- Patch --------------------------------------------------------------


def test_patch_valid_construction_reads_back_every_field():
    file_diff = make_file_diff()
    patch = make_patch(file_diffs=(file_diff,))

    assert patch.patch_id == "p-001"
    assert patch.file_diffs == (file_diff,)


def test_patch_holds_multiple_file_diffs_in_order():
    """One API change affects many call sites, so a patch is multi-file."""
    first = make_file_diff(file_path="examples/payment.py")
    second = make_file_diff(file_path="examples/refund.py")

    patch = make_patch(file_diffs=(first, second))

    assert patch.file_diffs == (first, second)


def test_patch_is_frozen():
    patch = make_patch()

    with pytest.raises(dataclasses.FrozenInstanceError):
        patch.patch_id = "p-999"


def test_patch_has_no_dict_because_slots_are_in_force():
    assert not hasattr(make_patch(), "__dict__")


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
def test_patch_id_rejects_empty_or_whitespace(bad_value):
    with pytest.raises(ValueError) as excinfo:
        make_patch(patch_id=bad_value)

    assert "patch_id" in str(excinfo.value)


def test_patch_empty_file_diffs_tuple_is_rejected():
    """A patch changing no files is not meaningful."""
    with pytest.raises(ValueError) as excinfo:
        make_patch(file_diffs=())

    assert "file_diffs" in str(excinfo.value)


def test_patch_file_diffs_as_a_list_is_rejected():
    with pytest.raises(TypeError) as excinfo:
        make_patch(file_diffs=[make_file_diff()])

    assert "tuple" in str(excinfo.value)


def test_patch_empty_list_of_file_diffs_reports_the_type_problem():
    with pytest.raises(TypeError):
        make_patch(file_diffs=[])


@pytest.mark.parametrize(
    "not_a_file_diff",
    [
        "examples/payment.py",
        {"file_path": "examples/payment.py"},
        None,
        7,
    ],
)
def test_patch_every_element_must_be_a_file_diff(not_a_file_diff):
    with pytest.raises(TypeError) as excinfo:
        make_patch(file_diffs=(not_a_file_diff,))

    assert "FileDiff" in str(excinfo.value)


def test_patch_reports_the_index_of_the_offending_element():
    """A multi-file patch with one bad entry should say which one."""
    with pytest.raises(TypeError) as excinfo:
        make_patch(file_diffs=(make_file_diff(), "not a FileDiff"))

    assert "1" in str(excinfo.value)


def test_patch_has_no_base_commit_hash_field():
    """The commit-level anchor lives on Migration; Patch anchors per file."""
    field_names = {f.name for f in dataclasses.fields(Patch)}

    assert "base_commit_hash" not in field_names


def test_patch_has_no_reversible_field():
    """Reversibility is enabled by the shape, not stored as a fact."""
    field_names = {f.name for f in dataclasses.fields(Patch)}

    assert "reversible" not in field_names
