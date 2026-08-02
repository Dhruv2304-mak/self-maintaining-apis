"""The scanner must not report matches from the fixer's own *_fixed.py output.

Regression test for the deferred Phase 0 bug: a scan run after a fix counted
every finding twice, because payment_fixed.py sits next to payment.py and is a
perfectly ordinary .py file as far as os.walk is concerned.
"""

import pytest

from src.core.paths import FIXED_SUFFIX, is_fixed_output
from src.core.scanner import CodebaseScanner

pytestmark = pytest.mark.unit

# Three occurrences, one per line, so each yields its own finding: the scanner
# reports at most one finding per keyword per line.
SOURCE_WITH_THREE_MATCHES = """\
import stripe


def charge_once(amount):
    return stripe.Charge.create(amount=amount)


def charge_twice(amount):
    stripe.Charge.create(amount=amount)
    return stripe.Charge.create(amount=amount)
"""


@pytest.fixture
def project_with_a_fixed_copy(tmp_path):
    """A directory holding payment.py and an identical payment_fixed.py."""
    (tmp_path / "payment.py").write_text(SOURCE_WITH_THREE_MATCHES, encoding="utf-8")
    (tmp_path / "payment_fixed.py").write_text(
        SOURCE_WITH_THREE_MATCHES, encoding="utf-8"
    )
    return tmp_path


def test_scan_ignores_fixed_copies(project_with_a_fixed_copy):
    scanner = CodebaseScanner(project_root=str(project_with_a_fixed_copy))

    findings = scanner.scan_for_api_usage(["stripe.Charge.create"])

    assert len(findings) == 3


def test_no_finding_comes_from_a_fixed_copy(project_with_a_fixed_copy):
    """Assert the paths, not just the count.

    A count-only assertion can pass for the wrong reason -- for instance if the
    scanner silently failed to read payment.py and returned the three findings
    from payment_fixed.py instead.
    """
    scanner = CodebaseScanner(project_root=str(project_with_a_fixed_copy))

    findings = scanner.scan_for_api_usage(["stripe.Charge.create"])

    paths = [str(finding["file_path"]) for finding in findings]
    assert all(path.endswith("payment.py") for path in paths)
    assert not any(path.endswith("payment_fixed.py") for path in paths)


def test_fixed_copy_is_excluded_from_the_file_list(project_with_a_fixed_copy):
    scanner = CodebaseScanner(project_root=str(project_with_a_fixed_copy))

    names = [path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for path in scanner.find_python_files()]

    assert names == ["payment.py"]


# --- The shared predicate itself ------------------------------------------
#
# The predicate is a plain `str.endswith("_fixed.py")`, matching what main.py
# has always done. The ambiguous cases below are characterizations of that
# behaviour, not a specification of what it ought to be.


@pytest.mark.parametrize(
    "path, expected",
    [
        ("payment.py", False),
        ("payment_fixed.py", True),
        ("payment_fixed.txt", False),  # extension must match too
        ("fixed.py", False),  # no leading underscore
        ("_fixed.py", True),  # the bare suffix is itself a match
        ("my_fixed_file.py", False),  # `_fixed` must be at the end
        ("a/b/payment_fixed.py", True),  # directories in the path are fine
        ("a\\b\\payment_fixed.py", True),
    ],
)
def test_is_fixed_output(path, expected):
    assert is_fixed_output(path) is expected


@pytest.mark.parametrize("path", ["PAYMENT_FIXED.PY", "payment_FIXED.py", "payment_fixed.PY"])
def test_is_fixed_output_is_case_sensitive(path):
    """Characterization: str.endswith is case-sensitive, so these are NOT skipped.

    On Windows these name the same file as the lowercase form, so a scan could
    still double-count one. Preserved deliberately -- it is exactly what main.py
    did before the extraction. Flagged in the summary.
    """
    assert is_fixed_output(path) is False


def test_suffix_constant_matches_the_one_main_has_always_used():
    assert FIXED_SUFFIX == "_fixed.py"


def test_predicate_agrees_with_mains_original_expression():
    """The extraction must not have changed semantics."""
    for path in ["payment.py", "payment_fixed.py", "_fixed.py", "a/b/c_fixed.py", "x.txt"]:
        assert is_fixed_output(path) == path.endswith("_fixed.py")
