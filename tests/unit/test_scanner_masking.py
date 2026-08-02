"""Comment and string masking -- the scanner's distinguishing feature.

The masking is column-level, driven by tokenize. A line is skipped only when
EVERY occurrence of the keyword on it falls inside a masked region; one real
occurrence is enough to report the line.
"""

import pytest

pytestmark = pytest.mark.unit

KW = "stripe.Charge.create"


def test_keyword_in_a_comment_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f"x = 1  # {KW} was here\n"})

    assert findings == []


def test_keyword_in_a_single_quoted_string_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f"x = '{KW}'\n"})

    assert findings == []


def test_keyword_in_a_double_quoted_string_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f'x = "{KW}"\n'})

    assert findings == []


def test_keyword_in_a_docstring_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f'"""Docs mentioning {KW}."""\n'})

    assert findings == []


def test_keyword_on_an_interior_line_of_a_docstring_is_not_found(scan_dir):
    source = f'"""Line one.\n\nWe used to call {KW} here.\n\nLine five.\n"""\n'

    findings, _ = scan_dir({"a.py": source})

    assert findings == []


def test_keyword_in_a_raw_string_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f'x = r"{KW}"\n'})

    assert findings == []


def test_keyword_in_a_byte_string_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f'x = b"{KW}"\n'})

    assert findings == []


def test_keyword_inside_escaped_quotes_is_not_found(scan_dir):
    findings, _ = scan_dir({"a.py": f'x = "he said \\"{KW}\\" loudly"\n'})

    assert findings == []


def test_code_followed_by_a_comment_repeating_it_yields_one_finding(scan_dir):
    """The column-level test -- the most valuable scanner test in Phase 1.

    A line-level masker fails this in one of two ways: masking the whole line
    and reporting nothing, or ignoring masking and reporting the comment too.
    Only a column-accurate masker reports exactly one.
    """
    source = f"{KW}(amount=100)  # old {KW} call\n"

    findings, _ = scan_dir({"a.py": source})

    assert len(findings) == 1
    assert findings[0]["line_number"] == 1


def test_a_masked_comment_line_does_not_leak_onto_the_next_line(scan_dir):
    """The mirror case: a comment-only line directly above a real call."""
    source = f"# TODO: remove {KW}\n{KW}(amount=100)\n"

    findings, _ = scan_dir({"a.py": source})

    assert len(findings) == 1
    assert findings[0]["line_number"] == 2


def test_a_docstring_does_not_mask_code_after_it(scan_dir):
    source = f'"""Mentions {KW}\nover two lines."""\n{KW}(1)\n'

    findings, _ = scan_dir({"a.py": source})

    assert [f["line_number"] for f in findings] == [3]


def test_string_on_the_same_line_as_real_code_still_reports(scan_dir):
    source = f'{KW}(note="{KW}")\n'

    findings, _ = scan_dir({"a.py": source})

    assert len(findings) == 1


def test_skip_comments_false_reports_matches_in_prose(scan_dir):
    source = f"# {KW}\nx = '{KW}'\n"

    findings, _ = scan_dir({"a.py": source}, skip_comments=False)

    assert [f["line_number"] for f in findings] == [1, 2]


def test_fstring_literal_text_is_masked(scan_dir):
    """Characterization: FSTRING_MIDDLE is treated as prose."""
    findings, _ = scan_dir({"a.py": f'result = f"deprecated: {KW}"\n'})

    assert findings == []


def test_fstring_expression_is_real_code_and_is_found(scan_dir):
    """Characterization, and the deliberate design.

    On Python 3.12+ the `{...}` parts of an f-string tokenize as ordinary code,
    so a genuine call inside the braces is reported while the literal text
    around it is masked. scanner.py comments say this is intended.
    """
    findings, _ = scan_dir({"a.py": f'result = f"charge: {{{KW}(amount=100)}}"\n'})

    assert len(findings) == 1


def test_masked_region_helper_is_half_open(scan_dir):
    """The region check is `start <= column < end`, so `end` is exclusive."""
    from src.core.scanner import CodebaseScanner

    assert CodebaseScanner._is_inside_masked_region(5, [(5, 10)]) is True
    assert CodebaseScanner._is_inside_masked_region(9, [(5, 10)]) is True
    assert CodebaseScanner._is_inside_masked_region(10, [(5, 10)]) is False
    assert CodebaseScanner._is_inside_masked_region(4, [(5, 10)]) is False
    assert CodebaseScanner._is_inside_masked_region(5, []) is False


def test_keyword_columns_are_zero_based_and_find_every_occurrence():
    """Columns are internal, but they are what the masking compares against."""
    from src.core.scanner import CodebaseScanner

    scanner = CodebaseScanner(project_root=".")
    line = f"{KW}(1); {KW}(2)"

    assert scanner._keyword_columns(line, KW) == [0, len(KW) + len("(1); ")]


def test_keyword_columns_are_case_insensitive():
    from src.core.scanner import CodebaseScanner

    scanner = CodebaseScanner(project_root=".")

    assert scanner._keyword_columns("STRIPE here", "stripe") == [0]


def test_keyword_columns_find_overlapping_occurrences():
    """Characterization: the search advances by one, so `aa` finds 2 in `aaa`."""
    from src.core.scanner import CodebaseScanner

    scanner = CodebaseScanner(project_root=".")

    assert scanner._keyword_columns("aaa", "aa") == [0, 1]
