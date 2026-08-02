"""Output path derivation for save_fixed_code."""

import os

import pytest

from src.core.fixer import CodeFixer
from src.core.paths import is_fixed_output

pytestmark = pytest.mark.unit


@pytest.fixture
def fixer():
    return CodeFixer(demo_mode=True)


def test_payment_py_maps_to_payment_fixed_py(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "payment.py"), "x = 1\n")

    assert os.path.basename(saved) == "payment_fixed.py"


def test_the_fixed_copy_lands_in_the_originals_directory(fixer, tmp_path):
    nested = tmp_path / "src" / "api"
    nested.mkdir(parents=True)

    saved = fixer.save_fixed_code(str(nested / "charge.py"), "x = 1\n")

    assert os.path.dirname(saved) == str(nested)
    assert os.path.basename(saved) == "charge_fixed.py"


def test_missing_parent_directories_are_created(fixer, tmp_path):
    target = tmp_path / "a" / "b" / "c" / "mod.py"

    saved = fixer.save_fixed_code(str(target), "x = 1\n")

    assert os.path.exists(saved)


def test_the_original_file_is_never_written(fixer, tmp_path):
    original = tmp_path / "payment.py"
    original.write_bytes(b"original content\n")

    fixer.save_fixed_code(str(original), "replacement\n")

    assert original.read_bytes() == b"original content\n"


def test_a_non_py_extension_is_preserved(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "script.txt"), "x = 1\n")

    assert os.path.basename(saved) == "script_fixed.txt"


def test_an_empty_path_falls_back_to_fixed_code_py(fixer, tmp_path, monkeypatch):
    """chdir into tmp_path first: this branch writes into the CURRENT directory,
    which would otherwise land in the project tree and trip the tree guard."""
    monkeypatch.chdir(tmp_path)

    saved = fixer.save_fixed_code("", "x = 1\n")

    assert saved == "fixed_code.py"
    assert (tmp_path / "fixed_code.py").exists()


def test_a_whitespace_only_path_also_falls_back(fixer, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert fixer.save_fixed_code("   ", "x = 1\n") == "fixed_code.py"


def test_an_error_string_is_refused(fixer, tmp_path):
    result = fixer.save_fixed_code(str(tmp_path / "p.py"), "ERROR: it went wrong")

    assert result.startswith("ERROR: Refusing to save a failed fix:")
    assert not (tmp_path / "p_fixed.py").exists()


def test_save_fixed_code_returns_a_string(fixer, tmp_path):
    assert isinstance(fixer.save_fixed_code(str(tmp_path / "p.py"), "x = 1\n"), str)
    assert isinstance(fixer.save_fixed_code(str(tmp_path / "p.py"), ""), str)


def test_already_fixed_input_produces_a_double_suffix(fixer, tmp_path):
    """CHARACTERIZATION -- the spec expected a skip here, and there is none.

    The spec assumed the `_fixed.py` skip predicate lived in the fixer. It does
    not: it lives in main.py, which guards before calling. save_fixed_code has
    no such check, so handed payment_fixed.py it cheerfully writes
    payment_fixed_fixed.py. Pinned as-is rather than "fixed", because adding the
    guard would be new product behaviour, not the §3.3 extraction. Flagged in
    the summary for your decision.
    """
    saved = fixer.save_fixed_code(str(tmp_path / "payment_fixed.py"), "x = 1\n")

    assert os.path.basename(saved) == "payment_fixed_fixed.py"
    assert is_fixed_output(saved) is True
