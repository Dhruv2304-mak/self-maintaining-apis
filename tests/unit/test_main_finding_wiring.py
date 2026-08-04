"""Unit tests for main.py consuming Finding objects.

main() itself is not exercised here -- it drives the whole pipeline and writes
files. These tests cover the seam that changed: group_findings_by_file now reads
CodeLocation instead of indexing a dict.
"""

import os

import pytest

import src.main as main_module
from src.core.scanner import CodebaseScanner
from src.domain.change_event import ChangeEvent
from src.domain.finding import CodeLocation, Finding
from src.main import group_findings_by_file

pytestmark = pytest.mark.unit


def make_finding(file_path, line=1, column=0, symbol="stripe.Charge.create"):
    """A Finding at a given place. Ids are irrelevant to grouping."""
    return Finding(
        finding_id=f"f-{line:016d}",
        change_event_id="ce-testtesttesttes",
        location=CodeLocation(
            file_path=file_path, line=line, column=column, snippet="snippet"
        ),
        matched_symbol=symbol,
    )


# --- group_findings_by_file ----------------------------------------------


def test_grouping_counts_matches_per_file():
    findings = [
        make_finding("examples/payment.py", line=1),
        make_finding("examples/payment.py", line=2),
        make_finding("examples/refund.py", line=1),
    ]

    assert group_findings_by_file(findings) == {
        "examples/payment.py": 2,
        "examples/refund.py": 1,
    }


def test_grouping_returns_paths_in_sorted_order():
    """Sorted output is what makes the printed report stable between runs."""
    findings = [
        make_finding("z.py"),
        make_finding("a.py"),
        make_finding("m.py"),
    ]

    assert list(group_findings_by_file(findings)) == ["a.py", "m.py", "z.py"]


def test_grouping_an_empty_sequence_yields_an_empty_dict():
    assert group_findings_by_file([]) == {}


def test_grouping_accepts_a_tuple_because_scan_returns_one():
    """scan() returns a tuple, so grouping must not require a list."""
    findings = (make_finding("a.py", line=1), make_finding("a.py", line=2))

    assert group_findings_by_file(findings) == {"a.py": 2}


def test_grouping_reads_the_location_not_a_dict_key():
    """A dict would raise TypeError here, proving the attribute path is used."""
    finding = make_finding("a.py")

    assert group_findings_by_file([finding]) == {"a.py": 1}
    with pytest.raises((TypeError, AttributeError)):
        group_findings_by_file([{"file_path": "a.py"}])


def test_grouping_keeps_two_symbols_on_one_line_as_two_matches():
    """The scanner reports one finding per keyword per line, and both count."""
    findings = [
        make_finding("a.py", line=5, symbol="stripe"),
        make_finding("a.py", line=5, symbol="stripe.Charge.create"),
    ]

    assert group_findings_by_file(findings) == {"a.py": 2}


# --- end to end through the real scanner ---------------------------------


@pytest.fixture
def event():
    return ChangeEvent(
        change_event_id="ce-testtesttesttes",
        symbol="stripe.Charge.create",
        change_class="removed",
        description="The Charge API has been removed.",
        source_url="https://example.invalid/docs",
        detected_at="2026-08-02T00:00:00+00:00",
    )


def test_scanner_output_feeds_straight_into_grouping(tmp_path, event):
    """The two halves of the seam have to fit without adaptation."""
    (tmp_path / "a.py").write_text(
        "stripe.Charge.create()\nstripe.Charge.create()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("stripe.Charge.create()\n", encoding="utf-8")

    findings = CodebaseScanner(str(tmp_path)).scan(event)
    grouped = group_findings_by_file(findings)

    assert sorted(grouped.values()) == [1, 2]
    assert all("\\" not in path for path in grouped)


def test_grouped_paths_are_openable(tmp_path, event):
    """fix_files_from_findings opens these keys, so they must be real paths."""
    (tmp_path / "a.py").write_text("stripe.Charge.create()\n", encoding="utf-8")

    grouped = group_findings_by_file(CodebaseScanner(str(tmp_path)).scan(event))

    for path in grouped:
        with open(path, "r", encoding="utf-8") as handle:
            assert "stripe" in handle.read()


def test_build_change_event_and_scan_compose(tmp_path, event):
    """A ChangeEvent built the way main builds one is scannable."""
    (tmp_path / "a.py").write_text("stripe.Charge.create()\n", encoding="utf-8")
    args = main_module.parse_args(["--target", str(tmp_path)])
    built = main_module.build_change_event(args, clock=lambda: "2026-01-01T00:00:00Z")

    findings = CodebaseScanner(args.target).scan(built, args.keywords)

    assert findings
    assert all(f.change_event_id == built.change_event_id for f in findings)


def test_calling_scan_twice_on_one_instance_reports_the_same_count(tmp_path, event):
    """files_scanned is reset inside the shared generator, not per entry point.

    Were the reset in the compatibility wrapper instead, the second scan() would
    add to the first and double the count.
    """
    (tmp_path / "a.py").write_text("stripe.Charge.create()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    scanner = CodebaseScanner(str(tmp_path))

    scanner.scan(event)
    first = scanner.files_scanned
    scanner.scan(event)

    assert first == 2
    assert scanner.files_scanned == 2


# --- to_repo_path: where a local path becomes a remote one ----------------


def test_to_repo_path_accepts_a_posix_form_absolute_path():
    """The one place a local path becomes a path in a pull request.

    scan() now emits forward-slash absolute paths, and to_repo_path must still
    reduce them correctly. A regression here puts wrong paths in a PR.
    """
    absolute = f"{main_module.PROJECT_ROOT}/examples/payment.py".replace("\\", "/")

    assert main_module.to_repo_path(absolute) == "examples/payment.py"


def test_to_repo_path_agrees_between_posix_and_native_separators():
    posix = f"{main_module.PROJECT_ROOT}/examples/payment.py".replace("\\", "/")
    native = os.path.join(main_module.PROJECT_ROOT, "examples", "payment.py")

    assert main_module.to_repo_path(posix) == main_module.to_repo_path(native)


def test_to_repo_path_rejects_a_path_outside_the_project(tmp_path):
    """Outside the repository means it cannot go into a pull request at all."""
    outside = str(tmp_path / "elsewhere.py").replace("\\", "/")

    assert main_module.to_repo_path(outside) is None


def test_scan_output_feeds_to_repo_path_without_adaptation(tmp_path, event):
    """Composition check: the scanner's own output must be directly usable."""
    (tmp_path / "a.py").write_text("stripe.Charge.create()\n", encoding="utf-8")

    finding = CodebaseScanner(str(tmp_path)).scan(event)[0]

    # tmp_path is outside the project, so None is the correct answer here; the
    # point is that it returns cleanly rather than raising on a POSIX path.
    assert main_module.to_repo_path(finding.location.file_path) is None
