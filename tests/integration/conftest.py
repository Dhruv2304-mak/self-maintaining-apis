"""Integration test fixtures and markers.

These tests may compose multiple internal modules, but still must not contact
external services or modify the real repo outside tmp_path.
"""

import pathlib

import pytest


@pytest.fixture(autouse=True)
def mark_integration(request):
    request.node.add_marker("integration")


def pytest_collection_modifyitems(config, items):
    # Session-wide hook: filter by path, or every test in the suite gets marked.
    here = pathlib.Path(__file__).parent
    for item in items:
        if here in pathlib.Path(str(item.path)).parents:
            item.add_marker("integration")
