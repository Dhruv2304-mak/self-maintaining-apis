"""save_fixed_code must not translate line endings, in either direction.

Every assertion here reads the file back in BINARY mode. A text-mode round-trip
on Windows normalizes silently, so it would pass while proving nothing -- see
test_text_mode_write_corrupts_line_endings, which exists to prove that risk is
real on this platform rather than theoretical.
"""

import pytest

from src.core.fixer import CodeFixer

pytestmark = pytest.mark.unit


@pytest.fixture
def fixer():
    return CodeFixer(demo_mode=True)


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def test_lf_content_stays_lf_with_no_cr_byte(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "s.py"), "a\nb\n")

    data = read_bytes(saved)
    assert data == b"a\nb\n"
    assert b"\r" not in data


def test_crlf_content_is_not_expanded_to_cr_cr_lf(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "s.py"), "a\r\nb\r\n")

    data = read_bytes(saved)
    assert data == b"a\r\nb\r\n"
    assert b"\r\r\n" not in data


def test_mixed_endings_survive_byte_for_byte(fixer, tmp_path):
    content = "lf\ncrlf\r\nlf\ntrailing\r\n"

    saved = fixer.save_fixed_code(str(tmp_path / "s.py"), content)

    assert read_bytes(saved) == b"lf\ncrlf\r\nlf\ntrailing\r\n"


def test_no_trailing_newline_means_none_is_added(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "s.py"), "a\nb")

    assert read_bytes(saved) == b"a\nb"


def test_a_lone_cr_is_preserved(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "s.py"), "a\rb")

    assert read_bytes(saved) == b"a\rb"


def test_utf8_content_round_trips(fixer, tmp_path):
    saved = fixer.save_fixed_code(str(tmp_path / "s.py"), "x = 'café — naïve'\n")

    assert read_bytes(saved) == "x = 'café — naïve'\n".encode("utf-8")


def test_empty_content_is_refused_rather_than_written(fixer, tmp_path):
    """Characterization: the spec expected an empty file; the fixer guards instead.

    save_fixed_code refuses empty or whitespace-only content so a failed fix
    cannot land on disk looking like a valid module.
    """
    result = fixer.save_fixed_code(str(tmp_path / "s.py"), "")

    assert result == "ERROR: There is no fixed code to save."
    assert not (tmp_path / "s_fixed.py").exists()


def test_whitespace_only_content_is_refused(fixer, tmp_path):
    result = fixer.save_fixed_code(str(tmp_path / "s.py"), "   \n\t\n")

    assert result == "ERROR: There is no fixed code to save."


def test_text_mode_write_corrupts_line_endings(tmp_path):
    """Proves the binary assertions above have teeth.

    This does NOT test product code. It writes the same content the way
    save_fixed_code deliberately avoids -- text mode with default newline
    handling -- and asserts the bytes come back corrupted. If this test ever
    starts failing, the platform assumption behind this whole module has
    changed and the binary assertions above may have quietly become vacuous.
    """
    scratch = tmp_path / "text_mode.py"

    with open(scratch, "w", encoding="utf-8") as handle:
        handle.write("a\nb\n")

    data = read_bytes(scratch)
    assert data == b"a\r\nb\r\n", "expected Windows text mode to expand \\n to \\r\\n"
    assert b"\r" in data
