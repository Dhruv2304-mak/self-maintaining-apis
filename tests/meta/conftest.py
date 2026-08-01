"""Meta-test markers and safety harness collection.

All tests in this directory verify the harness itself, not product behavior.
"""

import pytest


@pytest.fixture(autouse=True)
def mark_meta(request):
    request.node.add_marker("meta")


def pytest_collection_modifyitems(config, items):
    # The autouse fixture above applies the marker at run time, which is too late
    # for `-m meta` selection -- that happens during collection. Both are needed:
    # the hook makes selection work, the fixture makes the marker visible to
    # anything inspecting the node during the test.
    for item in items:
        item.add_marker("meta")
