"""Unit tests for CodebaseScanner.scan -- the typed Impact Analysis boundary.

Two jobs here. First, pin what scan() produces: Finding objects carrying the
ChangeEvent's id, with a CodeLocation that actually points at the match. Second,
prove scan() and the older scan_for_api_usage() report *the same matches in the
same order* -- that equivalence is the only thing stopping the two entry points
from drifting once callers start using both.
"""

import pytest

from src.core.scanner import CodebaseScanner
from src.domain.change_event import ChangeEvent
from src.domain.finding import CodeLocation, Finding
from src.domain.ids import derive_finding_id

pytestmark = pytest.mark.unit

SYMBOL = "stripe.Charge.create"

CODE_WITH_TWO_HITS = (
    "import stripe\n"
    "\n"
    "\n"
    "def charge(amount, token):\n"
    '    """Charge using the old Charges API."""\n'
    "    return stripe.Charge.create(amount=amount, source=token)\n"
)


@pytest.fixture
def event():
    """A ChangeEvent to scan for. Built directly, not via an adapter."""
    return ChangeEvent(
        change_event_id="ce-testtesttesttes",
        symbol=SYMBOL,
        change_class="removed",
        description="The Charge API has been removed.",
        source_url="https://example.invalid/docs",
        detected_at="2026-08-02T00:00:00+00:00",
    )


def write_tree(root, files):
    """Write {relative path: text} under `root`."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


# --- shape --------------------------------------------------------------


def test_scan_returns_a_tuple_of_findings(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert isinstance(findings, tuple)
    assert findings
    assert all(isinstance(f, Finding) for f in findings)


def test_scan_returns_an_empty_tuple_when_nothing_matches(tmp_path, event):
    """No matches is a normal result, not an error, and never None."""
    write_tree(tmp_path, {"a.py": "x = 1\n"})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert findings == ()


def test_every_finding_carries_the_change_event_id(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert all(f.change_event_id == event.change_event_id for f in findings)


def test_location_is_a_code_location_instance(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert all(isinstance(f.location, CodeLocation) for f in findings)


def test_matched_symbol_is_the_keyword_that_matched(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert {f.matched_symbol for f in findings} == {SYMBOL}


# --- the location actually points at the match ---------------------------


def test_line_number_is_one_based_and_correct(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    # Line 6 holds the only real-code occurrence; line 5's is inside a docstring.
    assert [f.location.line for f in findings] == [6]


def test_snippet_is_the_stripped_matching_line(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert findings[0].location.snippet == (
        "return stripe.Charge.create(amount=amount, source=token)"
    )


def test_column_indexes_the_raw_line_not_the_snippet(tmp_path, event):
    """Characterization of a real mismatch worth knowing about.

    `column` is the offset into the unstripped line, but `snippet` is stripped.
    On an indented line the two therefore disagree, and indexing snippet by
    column lands in the wrong place. Pinned rather than fixed: the column is
    correct for the file on disk, which is what a patch would need.
    """
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    location = CodebaseScanner(str(tmp_path)).scan(event)[0].location

    raw_line = CODE_WITH_TWO_HITS.split("\n")[location.line - 1]
    assert raw_line[location.column:].startswith(SYMBOL)
    assert not location.snippet[location.column:].startswith(SYMBOL)


def test_file_path_is_posix_form(tmp_path, event):
    """CodeLocation promises POSIX-form paths, so no backslashes survive."""
    write_tree(tmp_path, {"pkg/nested/a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert "\\" not in findings[0].location.file_path
    assert findings[0].location.file_path.endswith("pkg/nested/a.py")


def test_posix_path_still_opens(tmp_path, event):
    """A forward-slash path has to remain usable, or the fixer cannot read it."""
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    path = CodebaseScanner(str(tmp_path)).scan(event)[0].location.file_path

    with open(path, "r", encoding="utf-8") as handle:
        assert "stripe" in handle.read()


# --- keyword selection ---------------------------------------------------


def test_keywords_default_to_the_events_own_symbol(tmp_path, event):
    """The thing that changed is the thing to look for."""
    write_tree(tmp_path, {"a.py": "import stripe\nstripe.Charge.create()\n"})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    # "import stripe" on line 1 does not contain the full dotted symbol.
    assert [f.location.line for f in findings] == [2]


def test_explicit_keywords_widen_the_search(tmp_path, event):
    write_tree(tmp_path, {"a.py": "import stripe\nstripe.Charge.create()\n"})

    findings = CodebaseScanner(str(tmp_path)).scan(event, ["stripe"])

    assert [f.location.line for f in findings] == [1, 2]


def test_explicit_empty_keyword_list_finds_nothing(tmp_path, event):
    """An empty list is not the same as None: it means "search for nothing"."""
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    assert CodebaseScanner(str(tmp_path)).scan(event, []) == ()


# --- ids ------------------------------------------------------------------


def test_finding_id_is_derived_from_the_documented_inputs(tmp_path, event):
    """Contract: the id comes from derive_finding_id, not from a local rule."""
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    finding = CodebaseScanner(str(tmp_path)).scan(event)[0]

    assert finding.finding_id == derive_finding_id(
        change_event_id=event.change_event_id,
        file_path=finding.location.file_path,
        line=finding.location.line,
        column=finding.location.column,
        matched_symbol=finding.matched_symbol,
    )


def test_rescanning_an_unchanged_tree_yields_identical_findings(tmp_path, event):
    """Re-scanning an unchanged tree is stable. That is the whole claim.

    It does NOT follow that a finding can be recognised across edits: `line` and
    `column` are digest inputs, so inserting a single line above a match changes
    the finding_id of every match below it in that file.
    """
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    first = CodebaseScanner(str(tmp_path)).scan(event)
    second = CodebaseScanner(str(tmp_path)).scan(event)

    assert first == second


def test_finding_ids_are_distinct_per_match(tmp_path, event):
    write_tree(tmp_path, {"a.py": "stripe.Charge.create()\nstripe.Charge.create()\n"})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert len(findings) == 2
    assert len({f.finding_id for f in findings}) == 2


def test_a_different_change_event_yields_different_finding_ids(tmp_path, event):
    """The same location scanned for a different change is a different finding."""
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})
    other = ChangeEvent(
        change_event_id="ce-otherotherother",
        symbol=SYMBOL,
        change_class="removed",
        description="Same symbol, different event.",
        source_url="https://example.invalid/docs",
        detected_at="2026-08-02T00:00:00+00:00",
    )

    mine = CodebaseScanner(str(tmp_path)).scan(event)[0]
    theirs = CodebaseScanner(str(tmp_path)).scan(other)[0]

    assert mine.location == theirs.location
    assert mine.finding_id != theirs.finding_id


def test_finding_ids_start_with_the_f_prefix(tmp_path, event):
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS})

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert all(f.finding_id.startswith("f-") for f in findings)


# --- equivalence with the compatibility form ------------------------------

EQUIVALENCE_TREES = [
    pytest.param({"a.py": CODE_WITH_TWO_HITS}, id="single file"),
    pytest.param(
        {"a.py": CODE_WITH_TWO_HITS, "b.py": "stripe.Charge.create()\n"},
        id="two files",
    ),
    pytest.param(
        {"pkg/x.py": "stripe.Charge.create()\n", "pkg/sub/y.py": "import stripe\n"},
        id="nested",
    ),
    pytest.param({"a.py": "# stripe.Charge.create in a comment\n"}, id="comment only"),
    pytest.param({"a.py": 'S = "stripe.Charge.create"\n'}, id="string only"),
    pytest.param({"a.py": "def broken(:\n    stripe.Charge.create()\n"}, id="untokenizable"),
    pytest.param({"a.py": "x = 1\n"}, id="no matches"),
    pytest.param({}, id="empty tree"),
]


@pytest.mark.parametrize("files", EQUIVALENCE_TREES)
def test_scan_and_scan_for_api_usage_report_the_same_matches(tmp_path, event, files):
    """The two entry points must never disagree about what matched.

    Compared as ordered sequences, because order is part of the contract: the
    printed report and the grouped file counts both depend on it.
    """
    write_tree(tmp_path, files)
    keywords = ["stripe", "stripe.Charge.create"]

    typed = CodebaseScanner(str(tmp_path)).scan(event, keywords)
    plain = CodebaseScanner(str(tmp_path)).scan_for_api_usage(keywords)

    assert len(typed) == len(plain)
    for finding, row in zip(typed, plain):
        assert finding.location.line == row["line_number"]
        assert finding.location.snippet == row["line_content"]
        assert finding.matched_symbol == row["matched_keyword"]
        # Same file, allowing for the documented POSIX-vs-native difference.
        assert finding.location.file_path == str(row["file_path"]).replace("\\", "/")


@pytest.mark.parametrize("files", EQUIVALENCE_TREES)
def test_both_entry_points_agree_on_files_scanned(tmp_path, event, files):
    """files_scanned is set by the shared generator, so it must match too."""
    write_tree(tmp_path, files)

    typed_scanner = CodebaseScanner(str(tmp_path))
    typed_scanner.scan(event, ["stripe"])

    plain_scanner = CodebaseScanner(str(tmp_path))
    plain_scanner.scan_for_api_usage(["stripe"])

    assert typed_scanner.files_scanned == plain_scanner.files_scanned


def test_files_scanned_is_populated_after_scan(tmp_path, event):
    """The shared core is a generator; scan() must consume it fully."""
    write_tree(tmp_path, {"a.py": CODE_WITH_TWO_HITS, "b.py": "x = 1\n"})
    scanner = CodebaseScanner(str(tmp_path))

    scanner.scan(event)

    assert scanner.files_scanned == 2


def test_files_scanned_is_zero_before_any_scan(tmp_path):
    assert CodebaseScanner(str(tmp_path)).files_scanned == 0


def test_scan_respects_skip_comments_false(tmp_path, event):
    """Constructor options still apply to the typed entry point."""
    write_tree(tmp_path, {"a.py": "# stripe.Charge.create\n"})

    assert CodebaseScanner(str(tmp_path)).scan(event) == ()
    assert CodebaseScanner(str(tmp_path), skip_comments=False).scan(event)


def test_scan_skips_the_fixers_own_output(tmp_path, event):
    """Same _fixed.py exclusion the dictionary form has always applied."""
    write_tree(
        tmp_path,
        {"a.py": "stripe.Charge.create()\n", "a_fixed.py": "stripe.Charge.create()\n"},
    )

    findings = CodebaseScanner(str(tmp_path)).scan(event)

    assert len(findings) == 1
    assert findings[0].location.file_path.endswith("/a.py")
