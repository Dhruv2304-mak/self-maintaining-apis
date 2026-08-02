"""Unit test fixtures and markers.

These tests should be fast and isolated to a single module. Do not place
integration-wide or meta-tests here.
"""

import pathlib

import pytest

from src.core.scanner import CodebaseScanner

DEFAULT_KEYWORD = "stripe.Charge.create"


@pytest.fixture(autouse=True)
def mark_unit(request):
    request.node.add_marker("unit")


def pytest_collection_modifyitems(config, items):
    # This hook fires for the WHOLE session, not just this directory, so the
    # path check is required -- without it every meta test would also be marked
    # `unit` and `-m unit` would select the entire suite.
    here = pathlib.Path(__file__).parent
    for item in items:
        if here in pathlib.Path(str(item.path)).parents:
            item.add_marker("unit")


@pytest.fixture
def scan_dir(tmp_path):
    """Build a throwaway project tree and scan it.

    `files` maps relative path -> content. bytes are written verbatim (for
    line-ending tests); str is written as UTF-8. Returns (findings, scanner) so
    tests can also assert on scanner.files_scanned.
    """

    def _scan(files, keywords=(DEFAULT_KEYWORD,), **scanner_kwargs):
        for name, content in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")

        scanner = CodebaseScanner(project_root=str(tmp_path), **scanner_kwargs)
        return scanner.scan_for_api_usage(list(keywords)), scanner

    return _scan
