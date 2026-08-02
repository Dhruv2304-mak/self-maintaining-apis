"""A hand-written stand-in for PyGithub's `Github` client.

WHY NOT `MagicMock`
-------------------
Same reason as `fake_anthropic.py`: a MagicMock answers every attribute access,
so `repo.create_pul(...)` (typo) succeeds and the test proves nothing. Worse
here, because the thing under test is a *sequence* of calls -- a mock would
happily record calls that the real API would have rejected in that order.

WHAT THE SOURCE ACTUALLY TOUCHES
--------------------------------
Read off `src/core/publisher.py`. `FakeRepo` implements ONLY these, with the same
argument names, and nothing else of PyGithub's very large surface:

    Github(auth=Auth.Token(token))                            publisher.py:177
    client.get_repo(full_name)                                            :178
    repo.default_branch                    -- an ATTRIBUTE read, not a call  :183
    repo.get_branch(default_branch)                                       :184
    repo.create_git_ref(ref=, sha=)                                       :189
    repo.get_contents(path, ref=)                                         :201
    repo.update_file(path=, message=, content=, sha=, branch=)            :211
    repo.create_file(path=, message=, content=, branch=)                  :222
    repo.create_pull(title=, body=, head=, base=)                         :231

`create_pull`'s return value is used for exactly one thing: `.html_url`
(publisher.py:237). `create_pull_request` returns that URL string -- not a PR
object and not a dict.

THE `auth=` SIGNATURE (errata E4)
---------------------------------
The source calls `Github(auth=Auth.Token(self._token))`. That is NO positional
arguments and one keyword argument holding an `Auth.Token` OBJECT, not a string.
A fake written as `FakeGithub(token)` would raise TypeError. We unwrap the token
via `auth.token` and leave the real `Auth.Token` in place: it is an inert value
object that performs no I/O, so keeping it makes the fake honest about what the
source really constructs.

HOW TO INJECT IT
----------------
`PRPublisher.create_pull_request` builds the client itself, so patch the class:

    factory = FakeGithubFactory(repo_full_name="owner/repo")
    monkeypatch.setattr("src.core.publisher.Github", factory)

    publisher = PRPublisher("owner/repo", token="ghp_fake_do_not_use")
    url = publisher.create_pull_request({"a.py": "..."}, "title", "body")

    assert factory.client.events == [...]

Patch target is `src.core.publisher.Github` because `from github import Auth,
Github` (publisher.py:30) binds the name into the publisher's own namespace --
patching `github.Github` would miss entirely.

THE `events` LIST
-----------------
Every call that reaches the fake appends one tuple to a single shared list, in
order, so a test can assert the *sequence* rather than just the outcome:

    ("Github",)                                              client constructed
    ("get_repo", full_name)
    ("get_branch", name)
    ("create_git_ref", ref, sha)
    ("get_contents", path, ref)
    ("update_file", path, message, content, sha, branch)
    ("create_file", path, message, content, branch)
    ("create_pull", title, body, head, base)

The token is deliberately NOT recorded -- `events` gets printed in failure
output, and a credential has no business being there.

A call suppressed by `fail_on` is NOT recorded: `events` means "what actually
happened". A `get_contents` on a missing path IS recorded, because that is a
normal branch of the source (it triggers the `create_file` fallback), not an
injected failure.
"""

from github.GithubException import UnknownObjectException

DEFAULT_REPO_FULL_NAME = "owner/repo"
DEFAULT_BRANCH = "main"
DEFAULT_HEAD_SHA = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"
DEFAULT_BLOB_SHA = "9999888877776666555544443333222211110000"


class FakePR:
    """What `create_pull` returns. Only `.html_url` is read by the source."""

    def __init__(self, number=1, html_url=None):
        self.number = number
        self.html_url = html_url or (
            f"https://github.com/{DEFAULT_REPO_FULL_NAME}/pull/{number}"
        )


class FakeContentFile:
    """What `get_contents` returns for a file. Only `.sha` is read (line 214)."""

    def __init__(self, path, sha=DEFAULT_BLOB_SHA):
        self.path = path
        self.sha = sha


class FakeCommit:
    """The `.commit` of a branch. Only `.sha` is read (line 190)."""

    def __init__(self, sha):
        self.sha = sha


class FakeBranch:
    """What `get_branch` returns. The source reads `source.commit.sha`."""

    def __init__(self, name, sha):
        self.name = name
        self.commit = FakeCommit(sha)


class FakeRepo:
    """The repository object. Implements only the eight members listed above.

    Args:
        github: the FakeGithub that created us. We append to its `events` list
            and read its failure-injection settings, so both objects share one
            view of what happened.
        full_name: "owner/repo", for building PR URLs.
        default_branch: exposed as a plain attribute, because the source READS
            it (publisher.py:183) rather than calling it.
        head_sha: the sha `get_branch(...).commit.sha` reports, which the source
            passes straight to `create_git_ref`.
        missing_paths: paths where `get_contents` raises UnknownObjectException,
            as the real API does for a file that is not in the repo yet. Drives
            the `create_file` fallback at publisher.py:220-227.
        directory_paths: paths where `get_contents` returns a LIST, as the real
            API does for a folder. Drives the guard at publisher.py:205-209.
    """

    def __init__(
        self,
        github,
        full_name=DEFAULT_REPO_FULL_NAME,
        default_branch=DEFAULT_BRANCH,
        head_sha=DEFAULT_HEAD_SHA,
        missing_paths=(),
        directory_paths=(),
    ):
        self._github = github
        self.full_name = full_name
        self.default_branch = default_branch
        self.head_sha = head_sha
        self.missing_paths = set(missing_paths)
        self.directory_paths = set(directory_paths)

    # --- shared bookkeeping ----------------------------------------------

    def _record(self, *event):
        self._github.events.append(event)

    def _maybe_fail(self, method_name):
        """Raise the injected exception if this is the call under test."""
        self._github.maybe_fail(method_name)

    # --- the eight members the source actually uses -----------------------

    def get_branch(self, branch):
        self._maybe_fail("get_branch")
        self._record("get_branch", branch)
        return FakeBranch(branch, self.head_sha)

    def create_git_ref(self, ref, sha):
        self._maybe_fail("create_git_ref")
        self._record("create_git_ref", ref, sha)

    def get_contents(self, path, ref=None):
        self._maybe_fail("get_contents")
        self._record("get_contents", path, ref)

        if path in self.missing_paths:
            # What the real API raises for a path that does not exist yet.
            raise UnknownObjectException(404, {"message": "Not Found"}, {})

        if path in self.directory_paths:
            # The real API returns a list when the path is a folder.
            return [FakeContentFile(f"{path}/one.py"), FakeContentFile(f"{path}/two.py")]

        return FakeContentFile(path)

    def update_file(self, path, message, content, sha, branch):
        self._maybe_fail("update_file")
        self._record("update_file", path, message, content, sha, branch)
        # The real method returns a dict; the source ignores it entirely.

    def create_file(self, path, message, content, branch):
        self._maybe_fail("create_file")
        self._record("create_file", path, message, content, branch)
        # The real method returns a dict; the source ignores it entirely.

    def create_pull(self, title, body, head, base):
        self._maybe_fail("create_pull")
        self._record("create_pull", title, body, head, base)
        return FakePR(number=self._github.pr_number)


class FakeGithub:
    """One fake client instance.

    Args:
        auth: what the source passes -- a real `github.Auth.Token`. We unwrap
            `auth.token` onto `self.token` so a test can assert the token
            arrived. See errata E4.
        repo_full_name: the ONE repository this client knows about. `get_repo`
            raises UnknownObjectException for anything else, exactly as the real
            client does for a repo you cannot see.
        fail_on: name of the single method that should raise, e.g.
            `"create_pull"`. One fake covers every failure scenario this way
            instead of one subclass per scenario.
        fail_with: the exception INSTANCE to raise. Required when `fail_on` is
            set; passing one without the other raises ValueError immediately,
            because a `fail_on` that silently does nothing would produce a test
            that passes while exercising the happy path.
        pr_number: the number `create_pull` reports.
        **repo_kwargs: forwarded to FakeRepo -- `default_branch`, `head_sha`,
            `missing_paths`, `directory_paths`.
    """

    def __init__(
        self,
        *,
        auth=None,
        repo_full_name=DEFAULT_REPO_FULL_NAME,
        fail_on=None,
        fail_with=None,
        pr_number=1,
        **repo_kwargs,
    ):
        if (fail_on is None) != (fail_with is None):
            raise ValueError(
                "FakeGithub needs fail_on and fail_with together, or neither; "
                f"got fail_on={fail_on!r}, fail_with={fail_with!r}."
            )

        # errata E4: `auth` is an Auth.Token object, not a string.
        self.token = auth.token if auth is not None else None
        self.auth = auth

        self.repo_full_name = repo_full_name
        self.fail_on = fail_on
        self.fail_with = fail_with
        self.pr_number = pr_number
        self.repo_kwargs = repo_kwargs

        # The shared ordered log. See the module docstring for tuple shapes.
        self.events = [("Github",)]

    def maybe_fail(self, method_name):
        """Raise the injected exception if `method_name` is the one under test."""
        if self.fail_on == method_name:
            raise self.fail_with

    def get_repo(self, full_name):
        self.maybe_fail("get_repo")

        if full_name != self.repo_full_name:
            # The type the real PyGithub raises for a repo it cannot find.
            raise UnknownObjectException(404, {"message": "Not Found"}, {})

        self.events.append(("get_repo", full_name))
        return FakeRepo(self, full_name=full_name, **self.repo_kwargs)


class FakeGithubFactory:
    """A callable that impersonates the PyGithub `Github` CLASS.

    `create_pull_request` constructs its own client (publisher.py:177), so a test
    cannot hand one over. Patch this in as the class: the source calls it with
    `auth=...` exactly as it would the real constructor, and we keep the instance
    so the test can read `.events` and `.token` afterwards.

    Mirrors FakeAnthropicFactory deliberately -- the two fakes solve the same
    problem the same way.
    """

    def __init__(self, client_class=FakeGithub, **config):
        self.client_class = client_class
        self.config = config
        self.clients = []

        # Validate `config` now, so a bad fail_on/fail_with pair fails in the
        # test that wrote it rather than deep inside create_pull_request.
        client_class(**config)

    def __call__(self, *, auth=None, **extra):
        client = self.client_class(auth=auth, **self.config, **extra)
        self.clients.append(client)
        return client

    @property
    def client(self):
        """The single client that was built, or an error saying how many were."""
        if len(self.clients) != 1:
            raise AssertionError(
                f"expected exactly 1 fake client to be constructed, "
                f"got {len(self.clients)}"
            )
        return self.clients[0]

    @property
    def events(self):
        """Shorthand for `self.client.events`."""
        return self.client.events


class ExplodingGithub:
    """A client class that raises if constructed at all.

    For the dry-run tests (spec 7.1): dry run must return before any client is
    built (publisher.py:171-173 precedes the try at 175). Patching this in turns
    "no network call happened" from something inferred out of an empty events
    list into something actively enforced.
    """

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "Github client was constructed during a dry run -- publisher.py:171 "
            "should have returned before reaching publisher.py:177."
        )
