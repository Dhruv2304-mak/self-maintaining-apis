"""Unit test fixtures and markers.

These tests should be fast and isolated to a single module. Do not place
integration-wide or meta-tests here.
"""

import pytest


@pytest.fixture(autouse=True)
def mark_unit(request):
    request.node.add_marker("unit")


def pytest_collection_modifyitems(config, items):
    for item in items:
        item.add_marker("unit")
