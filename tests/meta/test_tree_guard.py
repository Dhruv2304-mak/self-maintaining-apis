"""Tests helpers/tree_guard.py directly, always against a throwaway tmp_path tree.

Never point snapshot() at the real project tree from a test: that is the session
hook's job, and doing it here would make the tests depend on repo state.
"""

import os

from tests.helpers.tree_guard import diff, snapshot


def test_unchanged_tree_diffs_empty(tmp_path):
    (tmp_path / "stable.txt").write_text("unchanged")

    before = snapshot(tmp_path)
    after = snapshot(tmp_path)

    assert diff(before, after) == ([], [], [])


def test_modified_file_is_reported_as_modified(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("hello")

    before = snapshot(tmp_path)
    target.write_text("goodbye")
    after = snapshot(tmp_path)

    added, removed, modified = diff(before, after)
    assert added == []
    assert removed == []
    assert modified == ["file.txt"]


def test_new_file_is_reported_as_added(tmp_path):
    before = snapshot(tmp_path)
    (tmp_path / "new.txt").write_text("new")
    after = snapshot(tmp_path)

    added, removed, modified = diff(before, after)
    assert added == ["new.txt"]
    assert removed == []
    assert modified == []


def test_deleted_file_is_reported_as_removed(tmp_path):
    target = tmp_path / "doomed.txt"
    target.write_text("doomed")

    before = snapshot(tmp_path)
    target.unlink()
    after = snapshot(tmp_path)

    added, removed, modified = diff(before, after)
    assert added == []
    assert removed == ["doomed.txt"]
    assert modified == []


def test_excluded_directories_are_absent_from_the_snapshot(tmp_path):
    for excluded in ("__pycache__", "venv", ".git", ".pytest_cache", "htmlcov"):
        directory = tmp_path / excluded
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored")

    (tmp_path / "tracked.txt").write_text("tracked")

    taken = snapshot(tmp_path)

    assert list(taken) == ["tracked.txt"]


def test_coverage_data_files_are_excluded_at_the_root(tmp_path):
    (tmp_path / ".coverage").write_text("coverage data")
    (tmp_path / ".coverage.myhost.12345.678901").write_text("parallel coverage data")
    (tmp_path / ".coveragerc").write_text("[run]")
    (tmp_path / "tracked.txt").write_text("tracked")

    taken = snapshot(tmp_path)

    # .coveragerc is a tracked project file: the ".coverage.*" pattern keeps its
    # literal dot precisely so this stays under the guard's watch.
    assert sorted(taken) == [".coveragerc", "tracked.txt"]


def test_coverage_exclusion_does_not_apply_below_the_root(tmp_path):
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / ".coverage").write_text("a stray write, not a test artefact")

    taken = snapshot(tmp_path)

    assert list(taken) == [os.path.join("src", ".coverage")]


def test_nested_excluded_directory_is_absent(tmp_path):
    nested = tmp_path / "src" / "__pycache__"
    nested.mkdir(parents=True)
    (nested / "module.pyc").write_text("ignored")
    (tmp_path / "src" / "module.py").write_text("tracked")

    taken = snapshot(tmp_path)

    assert list(taken) == [os.path.join("src", "module.py")]


def test_content_change_with_preserved_mtime_is_still_detected(tmp_path):
    target = tmp_path / "file.txt"
    target.write_bytes(b"original")
    original_mtime = target.stat().st_mtime_ns

    before = snapshot(tmp_path)

    target.write_bytes(b"tampered content")
    os.utime(target, ns=(original_mtime, original_mtime))

    after = snapshot(tmp_path)
    added, removed, modified = diff(before, after)

    assert modified == ["file.txt"]
    assert before["file.txt"][1] == after["file.txt"][1], "mtime should be identical"
    assert before["file.txt"][0] != after["file.txt"][0], "detection came from size"
    assert added == []
    assert removed == []
