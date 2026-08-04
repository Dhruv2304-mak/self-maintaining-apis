"""Unit tests for main.py consuming Finding objects.

main() itself is not exercised here -- it drives the whole pipeline and writes
files. These tests cover the seam that changed: group_findings_by_file now reads
CodeLocation instead of indexing a dict.
"""

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


def test_main_module_no_longer_indexes_findings_as_dicts():
    """Guards against a stray dict-style access surviving the migration."""
    import inspect

    source = inspect.getsource(main_module)

    for dead in (
        "finding['file_path']",
        "finding['line_number']",
        "finding['line_content']",
        "finding['matched_keyword']",
        'finding["file_path"]',
    ):
        assert dead not in source, f"{dead} still present in src/main.py"
