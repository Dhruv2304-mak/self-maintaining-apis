"""Sanity checks on the fakes themselves (spec 4.3).

These drive the fakes DIRECTLY -- nothing here imports from `src/`. That is the
point: a fake with a bug produces a green suite that tests nothing, and every
Phase 2 test downstream of here trusts these objects to behave. Cheap insurance.

The guard tests matter most. `FakeAnthropic` and `FakeGithub` both refuse
half-configured construction, and a refusal that quietly stopped working would
let a misconfigured test exercise the happy path while claiming to test a
failure.
"""

import anthropic
import pytest
from github import Auth
from github.GithubException import GithubException, UnknownObjectException

from tests.fakes.anthropic_errors import (
    make_api_error,
    make_connection_error,
    make_status_error,
)
from tests.fakes.fake_anthropic import (
    FakeAnthropic,
    FakeAnthropicEmptyContent,
    FakeAnthropicFactory,
    FakeBlockWithoutType,
    FakeThinkingBlock,
)
from tests.fakes.fake_github import (
    DEFAULT_REPO_FULL_NAME,
    FakeGithub,
    FakeGithubFactory,
)

pytestmark = pytest.mark.unit

FAKE_KEY = "sk-ant-fake-DO-NOT-USE"
FAKE_TOKEN = "ghp_fake_do_not_use"


# --- FakeAnthropic ------------------------------------------------------


def test_both_response_text_and_raise_exc_is_refused():
    with pytest.raises(ValueError, match="exactly one"):
        FakeAnthropic(response_text="x", raise_exc=RuntimeError("y"))


def test_neither_response_text_nor_raise_exc_is_refused():
    with pytest.raises(ValueError, match="exactly one"):
        FakeAnthropic(api_key=FAKE_KEY)


def test_successful_create_records_the_call_and_returns_the_text():
    client = FakeAnthropic(api_key=FAKE_KEY, response_text="print('fixed')")

    response = client.messages.create(model="m", max_tokens=1, system="s", messages=[])

    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "m"
    assert client.calls[0]["max_tokens"] == 1
    assert response.content[0].text == "print('fixed')"
    assert response.content[0].type == "text"
    assert response.stop_reason == "end_turn"


def test_api_key_lands_on_init_kwargs():
    client = FakeAnthropic(api_key=FAKE_KEY, response_text="x")

    assert client.init_kwargs == {"api_key": FAKE_KEY}


def test_raise_exc_mode_raises_but_still_records_the_call():
    """The call is recorded BEFORE raising, so a failure test can still inspect
    what was sent to the API."""
    boom = make_connection_error("no route")
    client = FakeAnthropic(api_key=FAKE_KEY, raise_exc=boom)

    with pytest.raises(anthropic.APIConnectionError):
        client.messages.create(model="m", max_tokens=1, system="s", messages=[])

    assert len(client.calls) == 1


def test_empty_content_variant_yields_no_blocks():
    client = FakeAnthropicEmptyContent(api_key=FAKE_KEY)

    response = client.messages.create(messages=[])

    assert response.content == []


def test_thinking_block_has_no_text_attribute():
    """Proves the block that must be filtered out cannot be read as text.

    If the source ever regressed to `response.content[0].text`, a test using this
    block would raise AttributeError instead of silently passing.
    """
    assert not hasattr(FakeThinkingBlock(), "text")
    assert FakeThinkingBlock().type == "thinking"


def test_block_without_type_has_text_but_no_type():
    assert FakeBlockWithoutType().text
    assert not hasattr(FakeBlockWithoutType(), "type")


def test_factory_passes_api_key_through_and_keeps_the_client():
    factory = FakeAnthropicFactory(response_text="ok")

    client = factory(api_key=FAKE_KEY)

    assert client is factory.client
    assert factory.client.init_kwargs == {"api_key": FAKE_KEY}
    assert factory.calls == []


def test_factory_validates_its_behaviour_eagerly():
    """A misconfigured factory must fail on the line that built it, not later
    inside CodeFixer.__init__ where the traceback is far less legible."""
    with pytest.raises(ValueError, match="exactly one"):
        FakeAnthropicFactory(response_text="x", raise_exc=RuntimeError("y"))


def test_factory_client_property_refuses_when_no_client_was_built():
    factory = FakeAnthropicFactory(response_text="ok")

    with pytest.raises(AssertionError, match="exactly 1 fake client"):
        factory.client


# --- FakeGithub ---------------------------------------------------------


def test_get_repo_raises_unknown_object_for_an_unconfigured_repo():
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN))

    with pytest.raises(UnknownObjectException):
        client.get_repo("nope/nope")


def test_auth_token_object_is_unwrapped_onto_token():
    """Errata E4: the source passes `auth=Auth.Token(...)`, not a bare string."""
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN))

    assert client.token == FAKE_TOKEN


def test_no_auth_leaves_token_none():
    assert FakeGithub().token is None


def test_token_is_never_written_into_the_events_log():
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN))
    client.get_repo(DEFAULT_REPO_FULL_NAME)

    assert FAKE_TOKEN not in repr(client.events)


def test_fail_on_raises_only_on_that_call_and_records_the_earlier_events():
    rejected = GithubException(422, {"message": "A pull request already exists"}, {})
    client = FakeGithub(
        auth=Auth.Token(FAKE_TOKEN), fail_on="create_pull", fail_with=rejected
    )

    repo = client.get_repo(DEFAULT_REPO_FULL_NAME)
    repo.get_branch("main")
    repo.create_git_ref(ref="refs/heads/bot/x", sha="deadbeef")

    with pytest.raises(GithubException):
        repo.create_pull(title="t", body="b", head="bot/x", base="main")

    assert client.events == [
        ("Github",),
        ("get_repo", DEFAULT_REPO_FULL_NAME),
        ("get_branch", "main"),
        ("create_git_ref", "refs/heads/bot/x", "deadbeef"),
    ]


def test_fail_on_without_fail_with_is_refused():
    """A fail_on that silently did nothing would produce a test that passes while
    exercising the happy path."""
    with pytest.raises(ValueError, match="fail_on and fail_with together"):
        FakeGithub(fail_on="create_pull")


def test_missing_path_makes_get_contents_raise_unknown_object():
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN), missing_paths={"new.py"})
    repo = client.get_repo(DEFAULT_REPO_FULL_NAME)

    with pytest.raises(UnknownObjectException):
        repo.get_contents("new.py", ref="bot/x")

    # Recorded even though it raised: a missing file is a normal branch of the
    # source (it triggers create_file), not an injected failure.
    assert ("get_contents", "new.py", "bot/x") in client.events


def test_directory_path_makes_get_contents_return_a_list():
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN), directory_paths={"pkg"})
    repo = client.get_repo(DEFAULT_REPO_FULL_NAME)

    assert isinstance(repo.get_contents("pkg", ref="bot/x"), list)


def test_get_contents_returns_a_file_with_a_sha_by_default():
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN))
    repo = client.get_repo(DEFAULT_REPO_FULL_NAME)

    assert repo.get_contents("a.py", ref="bot/x").sha


def test_create_pull_returns_a_pr_with_a_url_and_number():
    client = FakeGithub(auth=Auth.Token(FAKE_TOKEN), pr_number=42)
    repo = client.get_repo(DEFAULT_REPO_FULL_NAME)

    pull = repo.create_pull(title="t", body="b", head="h", base="main")

    assert pull.number == 42
    assert pull.html_url.endswith("/pull/42")


def test_default_branch_is_an_attribute_not_a_method():
    """The source READS repo.default_branch (publisher.py:183). If the fake made
    it callable the source would silently get a bound method as the branch name."""
    repo = FakeGithub(auth=Auth.Token(FAKE_TOKEN)).get_repo(DEFAULT_REPO_FULL_NAME)

    assert repo.default_branch == "main"
    assert not callable(repo.default_branch)


def test_github_factory_passes_auth_through_and_keeps_the_client():
    factory = FakeGithubFactory()

    client = factory(auth=Auth.Token(FAKE_TOKEN))

    assert client is factory.client
    assert factory.client.token == FAKE_TOKEN
    assert factory.events == [("Github",)]


def test_github_factory_validates_its_config_eagerly():
    with pytest.raises(ValueError, match="fail_on and fail_with together"):
        FakeGithubFactory(fail_on="create_pull")


# --- the anthropic exception factory (errata E12) -----------------------


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (anthropic.AuthenticationError, 401),
        (anthropic.NotFoundError, 404),
        (anthropic.RateLimitError, 429),
        (anthropic.APIStatusError, 500),
    ],
)
def test_status_error_factory_builds_the_real_type_with_the_right_status(cls, status):
    """`status_code` is read off the httpx.Response we supply, and handler #5 in
    fixer.py interpolates it into its message -- so it has to be right."""
    error = make_status_error(cls, status, "boom")

    assert isinstance(error, cls)
    assert error.status_code == status
    assert error.message == "boom"


def test_connection_error_factory_builds_the_real_type():
    error = make_connection_error("no route to host")

    assert isinstance(error, anthropic.APIConnectionError)
    assert error.message == "no route to host"


def test_api_error_reaches_the_bare_exception_handler():
    """APIError has no dedicated handler in fixer.py, so it must NOT be an
    instance of the types caught earlier -- otherwise it would land in handler
    #4 or #5 and the handler-#6 test would pass for the wrong reason."""
    error = make_api_error()

    assert isinstance(error, anthropic.APIError)
    assert not isinstance(error, anthropic.APIStatusError)
    assert not isinstance(error, anthropic.APIConnectionError)
