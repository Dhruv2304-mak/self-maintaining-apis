"""A hand-written stand-in for the `anthropic.Anthropic` client.

WHY NOT `MagicMock`
-------------------
`MagicMock()` invents an attribute the moment you touch one. So a test that
asserts on `fake.mesages.create` (note the typo) gets a brand-new mock back, the
assertion is made against something meaningless, and the test passes while
testing nothing. The same goes for the response: `mock.content[0].text` works on
a MagicMock whether or not the real object is shaped that way.

Everything below is a plain class with a fixed set of attributes. Touch a name
that does not exist and you get an `AttributeError` immediately, in the test that
made the mistake.

WHAT THE SOURCE ACTUALLY TOUCHES
--------------------------------
Read off `src/core/fixer.py`, not from memory of the SDK. That is the whole
contract these fakes have to honour:

* `anthropic.Anthropic(api_key=...)` -- one keyword argument, nothing else
  (fixer.py:120).
* `client.messages.create(model=, max_tokens=, system=, messages=)` -- exactly
  four keyword arguments. `temperature` is NOT passed (errata E5).
* On the response object: `.stop_reason` (compared to `"refusal"` at
  fixer.py:354) and `.content`, iterated with `block.type` and `block.text`
  (fixer.py:158-161).

Note `.content` is *iterated and filtered*, never indexed -- so an empty
`content` list cannot raise `IndexError` (errata E1). It falls through to the
"empty response" guard at fixer.py:358 instead.

HOW TO INJECT IT
----------------
`CodeFixer` builds its client inside `__init__` (fixer.py:120), so a test cannot
pass one in. Patch the *class* instead, and do it BEFORE constructing the fixer:

    factory = FakeAnthropicFactory(response_text="print('fixed')")
    monkeypatch.setattr("src.core.fixer.anthropic.Anthropic", factory)

    fixer = CodeFixer(api_key="sk-ant-fake-DO-NOT-USE")   # calls the factory
    result = fixer.fix_code("code", "description")

    assert factory.client.init_kwargs == {"api_key": "sk-ant-fake-DO-NOT-USE"}
    assert len(factory.calls) == 1

The patch target is `src.core.fixer.anthropic.Anthropic` because the source says
`anthropic.Anthropic(...)` -- an attribute lookup on the module object at call
time. Patch where the name is looked up, not where it is defined.
"""

# A private sentinel meaning "the caller did not pass this argument at all".
# We cannot use None for that here, because `content=None` is itself a value a
# test might legitimately want to inject.
_UNSET = object()


class FakeTextBlock:
    """A text block, as `_extract_code` expects to find in `response.content`."""

    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeThinkingBlock:
    """A non-text block, which `_extract_code` must filter out.

    Real Claude Sonnet 5 responses can lead with a thinking block -- the reason
    fixer.py:158-160 filters on `block.type` instead of reading `content[0]`.
    Deliberately has NO `.text` attribute: if the source ever regressed to
    reading the first block blindly, a test using this block would raise
    AttributeError rather than quietly pass.
    """

    def __init__(self, thinking="(pretend reasoning)"):
        self.type = "thinking"
        self.thinking = thinking


class FakeBlockWithoutType:
    """A block with `.text` but no `.type` -- for the errata E2 defect test.

    `_extract_code` runs OUTSIDE the try/except in `fix_code` (the try body is
    only the API call, fixer.py:316-328), so the AttributeError this provokes
    propagates out of `fix_code` instead of becoming an "ERROR:" string. That is
    a known defect, characterized in Phase 2 and not fixed.
    """

    def __init__(self, text="print('unreachable')"):
        self.text = text


class FakeMessage:
    """The object `messages.create()` returns.

    Only the two attributes the source reads: `.content` and `.stop_reason`.
    """

    def __init__(self, content, stop_reason="end_turn"):
        self.content = list(content)
        self.stop_reason = stop_reason


class FakeMessages:
    """Stands in for `client.messages`, whose only job is `.create()`."""

    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        """Record the call, then either raise or return the canned response.

        Recording happens BEFORE the raise, so a test asserting on a failure can
        still inspect what was sent.
        """
        self._client.calls.append(kwargs)

        if self._client.raise_exc is not None:
            raise self._client.raise_exc

        return self._client.response


class FakeAnthropic:
    """One fake client instance.

    Args:
        api_key: recorded, never used. This is the only argument the source
            passes (fixer.py:120), and it lands on `self.init_kwargs` so a test
            can assert the key reached the client.
        response_text: canned successful reply. `.create()` returns a
            FakeMessage holding a single text block with exactly this text.
        raise_exc: an exception INSTANCE. `.create()` raises it.
        content: an explicit list of blocks, for shapes `response_text` cannot
            express -- an empty list, a thinking block, a block with no `.type`.
        stop_reason: the response's `stop_reason`. Pass `"refusal"` to exercise
            the guard at fixer.py:354. Only meaningful alongside `response_text`
            or `content`.

    Exactly one of `response_text`, `raise_exc` or `content` must be given.
    Giving none or more than one raises ValueError immediately, at construction
    time -- a fake that silently does the wrong thing is worse than no fake, and
    failing here means the mistake surfaces in the test that made it.
    """

    def __init__(
        self,
        *,
        api_key=None,
        response_text=None,
        raise_exc=None,
        content=_UNSET,
        stop_reason="end_turn",
    ):
        chosen = [
            name
            for name, was_given in (
                ("response_text", response_text is not None),
                ("raise_exc", raise_exc is not None),
                ("content", content is not _UNSET),
            )
            if was_given
        ]
        if len(chosen) != 1:
            raise ValueError(
                "FakeAnthropic needs exactly one of response_text, raise_exc or "
                f"content; got {len(chosen)}: {chosen or 'none'}."
            )

        # Exactly what the source passed us. Kept as a dict rather than a bare
        # attribute so a test can assert on the whole call, and would notice if
        # the source ever started passing a second argument.
        self.init_kwargs = {"api_key": api_key}
        self.api_key = api_key

        # Every kwargs dict handed to messages.create(), in order.
        self.calls = []

        self.raise_exc = raise_exc
        if raise_exc is not None:
            self.response = None
        else:
            blocks = (
                [FakeTextBlock(response_text)] if content is _UNSET else content
            )
            self.response = FakeMessage(blocks, stop_reason=stop_reason)

        self.messages = FakeMessages(self)


class FakeAnthropicEmptyContent(FakeAnthropic):
    """A client whose reply has `content=[]` (spec 4.1, errata E1).

    This does NOT provoke an IndexError -- there is no indexing in
    `_extract_code`. It exercises the empty-response guard, so `fix_code` returns
    exactly `"ERROR: Claude returned an empty response."`

    Takes only `api_key`, so it can be patched in directly as the client class
    without going through FakeAnthropicFactory. Equivalent to
    `FakeAnthropic(content=[])`.
    """

    def __init__(self, *, api_key=None):
        super().__init__(api_key=api_key, content=[])


class FakeAnthropicFactory:
    """A callable that impersonates the `anthropic.Anthropic` CLASS.

    `CodeFixer.__init__` constructs its own client, so a test cannot hand one
    over. Patching this object in as the class means the fixer calls it exactly
    as it would call the real constructor -- with `api_key=` -- and we keep the
    instance it received so the test can inspect it afterwards.

    Args:
        client_class: which fake client to build. Defaults to FakeAnthropic.
        **behaviour: passed straight through to `client_class`, e.g.
            `response_text=...` or `raise_exc=...`.
    """

    def __init__(self, client_class=FakeAnthropic, **behaviour):
        self.client_class = client_class
        self.behaviour = behaviour
        self.clients = []

        # Build one throwaway client now, purely to validate `behaviour`. A
        # misconfigured factory should fail in the line that built it, not later
        # and less legibly inside CodeFixer.__init__.
        client_class(api_key=None, **behaviour)

    def __call__(self, *, api_key=None, **extra):
        client = self.client_class(api_key=api_key, **self.behaviour, **extra)
        self.clients.append(client)
        return client

    @property
    def client(self):
        """The single client that was built, or an error saying how many were.

        Nearly every test builds exactly one CodeFixer. Guarding the count means
        a test that accidentally built two does not silently assert against the
        wrong one.
        """
        if len(self.clients) != 1:
            raise AssertionError(
                f"expected exactly 1 fake client to be constructed, "
                f"got {len(self.clients)}"
            )
        return self.clients[0]

    @property
    def calls(self):
        """Shorthand for `self.client.calls`."""
        return self.client.calls


class ExplodingAnthropic:
    """A client class whose constructor raises -- for the errata E7 defect test.

    `CodeFixer.__init__` does not wrap its client construction (fixer.py:120),
    so this propagates out of `CodeFixer(...)` itself, contradicting the
    docstring's promise at fixer.py:94-97 that nothing there ever raises.
    """

    def __init__(self, *, api_key=None, **kwargs):
        raise RuntimeError("client construction failed")
