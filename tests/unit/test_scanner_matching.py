"""Core keyword matching: what the scanner finds and what it reports.

Note on the finding shape: the scanner returns at most ONE finding per keyword
per line, and findings carry no column. Columns exist internally (see
test_scanner_masking.py) but are not part of the public result.
"""

import pytest

pytestmark = pytest.mark.unit

KW = "stripe.Charge.create"


def test_keyword_in_ordinary_code_is_found(scan_dir):
    findings, _ = scan_dir({"a.py": f"x = {KW}(amount=1)\n"})

    assert len(findings) == 1


def test_finding_has_exactly_the_documented_fields(scan_dir):
    findings, _ = scan_dir({"a.py": f"x = {KW}(amount=1)\n"})

    assert set(findings[0]) == {
        "file_path",
        "line_number",
        "line_content",
        "matched_keyword",
    }


def test_line_number_is_one_based(scan_dir):
    source = f"import stripe\n\n\nx = {KW}(amount=1)\n"

    findings, _ = scan_dir({"a.py": source})

    assert findings[0]["line_number"] == 4


def test_line_content_is_stripped(scan_dir):
    findings, _ = scan_dir({"a.py": f"        x = {KW}(1)\n"})

    assert findings[0]["line_content"] == f"x = {KW}(1)"


def test_matched_keyword_is_reported_verbatim(scan_dir):
    findings, _ = scan_dir({"a.py": f"x = {KW}(1)\n"})

    assert findings[0]["matched_keyword"] == KW


def test_file_path_is_absolute(scan_dir, tmp_path):
    findings, _ = scan_dir({"a.py": f"x = {KW}(1)\n"})

    assert str(findings[0]["file_path"]).startswith(str(tmp_path))


def test_two_occurrences_on_one_line_yield_one_finding(scan_dir):
    """Characterization, not a specification.

    The spec anticipated two findings with distinct columns. The scanner instead
    reports at most one finding per keyword per line -- a line is either flagged
    or not -- and exposes no column. See the Phase 1 deviation report.
    """
    findings, _ = scan_dir({"a.py": f"a = {KW}(1); b = {KW}(2)\n"})

    assert len(findings) == 1


def test_same_keyword_on_two_lines_yields_two_findings(scan_dir):
    findings, _ = scan_dir({"a.py": f"a = {KW}(1)\nb = {KW}(2)\n"})

    assert [f["line_number"] for f in findings] == [1, 2]


def test_multiple_keywords_are_each_attributed_correctly(scan_dir):
    source = "import stripe\nimport openai\n"

    findings, _ = scan_dir({"a.py": source}, keywords=("stripe", "openai"))

    attributed = {(f["line_number"], f["matched_keyword"]) for f in findings}
    assert attributed == {(1, "stripe"), (2, "openai")}


def test_two_keywords_on_the_same_line_yield_one_finding_each(scan_dir):
    findings, _ = scan_dir(
        {"a.py": "import stripe, openai\n"}, keywords=("stripe", "openai")
    )

    assert sorted(f["matched_keyword"] for f in findings) == ["openai", "stripe"]


def test_matching_is_case_insensitive(scan_dir):
    findings, _ = scan_dir({"a.py": "x = STRIPE.Charge.CREATE(1)\n"})

    assert len(findings) == 1


def test_no_matches_yields_no_findings(scan_dir):
    findings, _ = scan_dir({"a.py": "x = 1 + 2\nprint(x)\n"})

    assert findings == []


def test_empty_file_is_scanned_without_error(scan_dir):
    findings, scanner = scan_dir({"a.py": ""})

    assert findings == []
    assert scanner.files_scanned == 1


def test_whitespace_only_file_is_scanned_without_error(scan_dir):
    findings, scanner = scan_dir({"a.py": "   \n\n\t\n"})

    assert findings == []
    assert scanner.files_scanned == 1


def test_comment_only_file_yields_no_findings(scan_dir):
    findings, scanner = scan_dir({"a.py": f"# {KW}\n# and again {KW}\n"})

    assert findings == []
    assert scanner.files_scanned == 1


def test_files_scanned_counts_every_readable_file(scan_dir):
    findings, scanner = scan_dir(
        {"a.py": f"{KW}\n", "b.py": "pass\n", "c.py": f"{KW}\n"}
    )

    assert scanner.files_scanned == 3
    assert len(findings) == 2


def test_files_scanned_starts_at_zero_before_any_scan():
    from src.core.scanner import CodebaseScanner

    assert CodebaseScanner(project_root=".").files_scanned == 0


def test_substring_matches_a_longer_identifier(scan_dir):
    """Characterization: no word-boundary handling by default.

    `stripe.Charge.created` matches the keyword `stripe.Charge.create`. This has
    real false-positive consequences for the pipeline -- flagged in the summary.
    """
    findings, _ = scan_dir({"a.py": "x = stripe.Charge.created\n"})

    assert len(findings) == 1


def test_substring_matches_a_prefixed_identifier(scan_dir):
    """Characterization: `my_stripe.Charge.create()` matches too."""
    findings, _ = scan_dir({"a.py": "x = my_stripe.Charge.create()\n"})

    assert len(findings) == 1


def test_whole_word_rejects_a_trailing_extension(scan_dir):
    """Characterization: whole_word=True drops `stripe.Charge.created`."""
    findings, _ = scan_dir({"a.py": "x = stripe.Charge.created\n"}, whole_word=True)

    assert findings == []


def test_whole_word_also_rejects_a_prefixed_identifier(scan_dir):
    """Characterization: `my_stripe.Charge.create()` is dropped by whole_word.

    The leading \\b fails because `_` is a word character, so there is no
    boundary between `my_` and `stripe`. If the deprecated API is ever reached
    through an aliased or attribute-prefixed name, whole_word=True will miss it.
    That is a narrow blind spot, not a general one -- an ordinary call is matched
    normally, as the tests below show.
    """
    findings, _ = scan_dir({"a.py": "x = my_stripe.Charge.create()\n"}, whole_word=True)

    assert findings == []


@pytest.mark.parametrize(
    "source",
    [
        f"x = {KW}(amount=100)\n",
        f"{KW}(amount=100)\n",
        f"def f():\n    return {KW}(amount=1)\n",
    ],
    ids=["assignment", "bare call", "return statement"],
)
def test_whole_word_matches_a_genuine_call(scan_dir, source):
    """whole_word=True does NOT reject ordinary calls.

    `(` after `create` is a non-word character, so the trailing \\b is satisfied.
    Only `stripe.Charge.created` (word char continues) and prefixed forms like
    `my_stripe.` are dropped.
    """
    findings, _ = scan_dir({"a.py": source}, whole_word=True)

    assert len(findings) == 1


def test_keyword_with_dots_is_escaped_not_treated_as_regex(scan_dir):
    """`.` in a keyword must be literal, not "any character"."""
    findings, _ = scan_dir({"a.py": "x = stripeXChargeXcreate(1)\n"})

    assert findings == []
