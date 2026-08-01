"""Integration test fixtures and markers.

These tests may compose multiple internal modules, but still must not contact
external services or modify the real repo outside tmp_path.
"""

import pytest


@pytest.fixture(autouse=True)
def mark_integration(request):
    request.node.add_marker("integration")


def pytest_collection_modifyitems(config, items):
    for item in items:
        item.add_marker("integration")
