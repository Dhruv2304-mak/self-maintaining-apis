"""Proves the global socket block is real.

Every assertion names pytest_socket.SocketBlockedError specifically rather than
a bare Exception. A loose `pytest.raises(Exception)` would still pass with the
plugin disabled -- ConnectionRefusedError satisfies it -- so the test would
verify nothing. Targets are 127.0.0.1:9 (discard port) so a mistakenly
unblocked call fails fast instead of hanging.
"""

import socket

import pytest
import requests
from pytest_socket import SocketBlockedError

# Blocking a socket is the expected outcome in every test here, so the warning
# pytest-socket emits alongside the error is noise. Ignoring it (rather than
# letting pytest.ini's `default` action record it) keeps the suite warning-free
# without weakening the block: the error is still raised and still caught below.
pytestmark = pytest.mark.filterwarnings("ignore:A test tried to use socket")


def test_socket_constructor_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_socket_connect_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket().connect(("127.0.0.1", 9))


def test_create_connection_blocked():
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("127.0.0.1", 9), timeout=1)


def test_requests_get_blocked():
    with pytest.raises(SocketBlockedError):
        requests.get("http://127.0.0.1:9", timeout=1)


def test_getaddrinfo_blocked():
    with pytest.raises(SocketBlockedError):
        socket.getaddrinfo("127.0.0.1", 9)


def test_assert_socket_disabled_reports_guard_active(assert_socket_disabled):
    assert assert_socket_disabled is True
