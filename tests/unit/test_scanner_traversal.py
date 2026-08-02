"""Directory traversal, ignored folders, and line-ending independence."""

import os

import pytest

pytestmark = pytest.mark.unit

KW = "stripe.Charge.create"


def test_nested_subdirectories_are_scanned_recursively(scan_dir):
    findings, _ = scan_dir({"pkg/sub/deep/a.py": f"{KW}(1)\n"})

    assert len(findings) == 1


def test_findings_from_multiple_files_each_keep_their_own_path(scan_dir):
    findings, _ = scan_dir({"a.py": f"{KW}(1)\n", "pkg/b.py": f"{KW}(2)\n"})

    names = sorted(os.path.basename(str(f["file_path"])) for f in findings)
    assert names == ["a.py", "b.py"]


def test_non_python_files_are_not_scanned(scan_dir):
    """Characterization: only `*.py` is collected; a .txt is invisible."""
    findings, scanner = scan_dir({"a.txt": f"{KW}\n", "b.py": f"{KW}(1)\n"})

    assert scanner.files_scanned == 1
    assert os.path.basename(str(findings[0]["file_path"])) == "b.py"


def test_pyi_and_similar_extensions_are_not_scanned(scan_dir):
    """Characterization: the filter is a literal `.py` suffix check."""
    findings, scanner = scan_dir({"a.pyi": f"{KW}\n"})

    assert scanner.files_scanned == 0
    assert findings == []


@pytest.mark.parametrize("ignored", ["venv", ".venv", "__pycache__", ".git"])
def test_default_ignored_directories_are_skipped(scan_dir, ignored):
    findings, scanner = scan_dir({f"{ignored}/a.py": f"{KW}(1)\n"})

    assert scanner.files_scanned == 0
    assert findings == []


def test_hidden_directories_are_not_skipped(scan_dir):
    """Characterization: only the four named folders are pruned.

    A dot-prefixed folder such as .github, .tox or .mypy_cache IS walked. venv
    itself is skipped, so the slow-and-nonsense case the spec worried about does
    not arise -- but the skip list is a fixed set of names, not a hidden-dir
    rule. Flagged in the summary.
    """
    findings, _ = scan_dir({".github/a.py": f"{KW}(1)\n"})

    assert len(findings) == 1


def test_extra_ignored_dirs_are_honoured(scan_dir):
    findings, scanner = scan_dir(
        {"tests/a.py": f"{KW}(1)\n"}, extra_ignored_dirs=["tests"]
    )

    assert scanner.files_scanned == 0
    assert findings == []


def test_extra_ignored_dirs_do_not_mutate_the_shared_default(scan_dir):
    from src.core.scanner import IGNORED_DIRS, CodebaseScanner

    before = set(IGNORED_DIRS)
    CodebaseScanner(project_root=".", extra_ignored_dirs=["tests"])

    assert IGNORED_DIRS == before


def test_ignored_directories_are_matched_by_name_at_any_depth(scan_dir):
    findings, scanner = scan_dir({"pkg/venv/a.py": f"{KW}(1)\n"})

    assert scanner.files_scanned == 0


def test_crlf_file_reports_the_same_line_number_as_lf(scan_dir, tmp_path):
    """Line endings are generated in binary mode; see the Phase 1 fixture policy."""
    lf = b"import stripe\n" + KW.encode() + b"(amount=100)\n"
    crlf = b"import stripe\r\n" + KW.encode() + b"(amount=100)\r\n"

    lf_findings, _ = scan_dir({"lf_source.py": lf})
    crlf_findings, _ = scan_dir({"crlf_source.py": crlf})

    assert lf_findings[0]["line_number"] == crlf_findings[0]["line_number"] == 2


def test_crlf_file_reports_the_same_content_as_lf(scan_dir):
    lf = b"import stripe\n" + KW.encode() + b"(amount=100)\n"
    crlf = b"import stripe\r\n" + KW.encode() + b"(amount=100)\r\n"

    lf_findings, _ = scan_dir({"lf_source.py": lf})
    crlf_findings, _ = scan_dir({"crlf_source.py": crlf})

    assert lf_findings[0]["line_content"] == crlf_findings[0]["line_content"]
    assert "\r" not in str(crlf_findings[0]["line_content"])


def test_crlf_masking_still_works(scan_dir):
    """A CRLF comment must still mask, or tokenize offsets have drifted."""
    crlf = b"x = 1  # " + KW.encode() + b"\r\n"

    findings, _ = scan_dir({"a.py": crlf})

    assert findings == []


def test_find_python_files_returns_absolute_paths(tmp_path):
    from src.core.scanner import CodebaseScanner

    (tmp_path / "a.py").write_text("pass\n", encoding="utf-8")

    files = CodebaseScanner(project_root=str(tmp_path)).find_python_files()

    assert all(os.path.isabs(path) for path in files)


def test_project_root_is_stored_as_an_absolute_path(tmp_path, monkeypatch):
    from src.core.scanner import CodebaseScanner

    monkeypatch.chdir(tmp_path)

    assert os.path.isabs(CodebaseScanner(project_root=".").project_root)


def test_untokenizable_file_falls_back_to_a_plain_scan(scan_dir, capsys):
    """Invalid Python still gets scanned, line by line, with a printed notice."""
    findings, _ = scan_dir({"broken.py": f"def (:\n{KW}(1)\n"})

    assert len(findings) == 1
    assert "Could not tokenize" in capsys.readouterr().out
