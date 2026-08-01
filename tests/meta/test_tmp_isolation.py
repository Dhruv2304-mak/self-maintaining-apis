"""Proves tmp_path isolation and byte-exact file I/O.

The binary round-trip matters beyond this phase: Phase 1's line-ending tests are
only meaningful if nothing between the test and the disk normalises newlines.
"""

import os

import pytest


def test_tmp_path_exists_and_is_empty(tmp_path):
    assert tmp_path.exists()
    assert tmp_path.is_dir()
    assert not any(tmp_path.iterdir())


def test_written_file_reads_back_with_exact_bytes(tmp_path):
    data = b"exact bytes, no translation"
    target = tmp_path / "payload.bin"
    target.write_bytes(data)
    assert target.read_bytes() == data


# Recording one test's tmp_path for the next to compare against. Cross-test
# coupling is acceptable here: proving isolation requires comparing two tests.
_seen_tmp_paths = []


def test_tmp_path_is_recorded_for_the_next_test(tmp_path):
    _seen_tmp_paths.append(str(tmp_path))
    assert _seen_tmp_paths


def test_tmp_path_differs_between_tests(tmp_path):
    assert _seen_tmp_paths, "the recording test must run first"
    assert str(tmp_path) not in _seen_tmp_paths


def test_binary_round_trip_preserves_newlines(tmp_path):
    payload = b"lf\nlf-again\ncrlf\r\ntrailing\n"
    target = tmp_path / "endings.bin"

    with open(target, "wb") as handle:
        handle.write(payload)
    with open(target, "rb") as handle:
        read_back = handle.read()

    assert read_back == payload
    assert read_back.count(b"\n") == 4
    assert read_back.count(b"\r\n") == 1


def test_monkeypatch_chdir_restores_the_real_cwd(tmp_path):
    original = os.getcwd()

    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(tmp_path)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(str(tmp_path))

    assert os.getcwd() == original
