"""Constructors for real `anthropic` exception objects (errata E12).

None of the six exception types `fixer.py` catches can be built with no
arguments:

    AuthenticationError(message, *, response, body)   # and NotFoundError,
    RateLimitError, APIStatusError -- all four share this signature
    APIConnectionError(*, message="Connection error.", request)
    APIError(message, request, *, body)

So every handler test needs an `httpx.Response` or an `httpx.Request` to hand
over. Both are inert data objects -- constructing one opens no connection and
resolves no hostname -- so they are safe under `--disable-socket`. The URL below
uses the reserved `.invalid` TLD as a second belt-and-braces guarantee that
nothing could resolve even if something tried.

We build the REAL exception types rather than stand-ins, because the whole point
of the handler tests is that `except anthropic.AuthenticationError` matches. A
fake exception class would not be caught by the code under test, and the test
would pass for the wrong reason.
"""

import anthropic
import httpx

# Reserved TLD (RFC 2606): guaranteed never to resolve.
FAKE_URL = "https://api.anthropic.invalid/v1/messages"


def make_request():
    """An httpx.Request that has never been sent and never will be."""
    return httpx.Request("POST", FAKE_URL)


def make_response(status, request=None):
    """An httpx.Response carrying `status`, attached to a dummy request.

    `status` matters: APIStatusError reads `.status_code` off this object, and
    handler #5 in fixer.py interpolates it into its error string.
    """
    return httpx.Response(status_code=status, request=request or make_request())


def make_status_error(cls, status, message):
    """Build one of the four APIStatusError subclasses.

    Args:
        cls: the exception class, e.g. `anthropic.AuthenticationError`.
        status: HTTP status the exception should report via `.status_code`.
        message: text the exception should report via `.message`.

    Use the conventional status for the class -- 401 for authentication, 404 for
    not-found, 429 for rate limits -- so the object is a believable stand-in for
    what the SDK would really raise.
    """
    return cls(message, response=make_response(status), body=None)


def make_connection_error(message="Connection error."):
    """Build an `anthropic.APIConnectionError`.

    Different signature from the four above: no response (there was none -- the
    request never landed), and `request` is keyword-only.
    """
    return anthropic.APIConnectionError(message=message, request=make_request())


def make_api_error(message="Something the SDK did not classify"):
    """Build a bare `anthropic.APIError`.

    APIError is a real SDK type with NO dedicated handler in fixer.py, so it
    falls through to the bare `except Exception` at fixer.py:349. That makes it
    a more honest way to reach handler #6 than inventing our own exception
    class: it is a failure the SDK could genuinely produce.
    """
    return anthropic.APIError(message, make_request(), body=None)
