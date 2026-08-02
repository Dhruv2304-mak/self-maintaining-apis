"""Meta-test markers and safety harness collection.

All tests in this directory verify the harness itself, not product behavior.
"""

import pathlib

import pytest


@pytest.fixture(autouse=True)
def mark_meta(request):
    request.node.add_marker("meta")


def pytest_collection_modifyitems(config, items):
    # The autouse fixture above applies the marker at run time, which is too late
    # for `-m meta` selection -- that happens during collection. Both are needed:
    # the hook makes selection work, the fixture makes the marker visible to
    # anything inspecting the node during the test.
    #
    # The hook fires for the WHOLE session, not just this directory, so items
    # must be filtered by path or every unit test would be marked `meta` too.
    here = pathlib.Path(__file__).parent
    for item in items:
        if here in pathlib.Path(str(item.path)).parents:
            item.add_marker("meta")
