---

# Errata — corrections from the Step 1 source report

Applied after the §3 source report run against commit `1998235` (anthropic 0.120.0,
PyGithub 2.9.1, Python 3.14.6). Every item below **overrides** the section it names.
Where this errata and the body of the spec disagree, the errata wins.

Five of these are spec errors — cases where the spec asserted something about the
source that turned out to be false. Three of them would have produced tests that
passed without testing anything. This is the third time the read-the-source-first
step has caught a spec error; it stays.

---

## E1 — §3.2, §4.1, §5.4: no `IndexError` is reachable

The spec asked whether `response.content[0].text` could raise on an empty response.
There is no indexing anywhere. `_extract_code` (`fixer.py:158-161`) uses a list
comprehension filtered on `block.type == "text"`, joins with `"\n"`, and strips.

An empty `content` list therefore yields `""`, which hits the guard at
`fixer.py:358-359` and returns `"ERROR: Claude returned an empty response."`

**Action:** keep the `FakeAnthropicEmptyContent` variant from §4.1, but it tests the
empty-response *guard*, not an `IndexError`. Assert the exact string above.

## E2 — §5.4: a malformed block raises out of `fix_code`

The `try` opens at `fixer.py:315` and its body is only the `messages.create(...)` call,
lines 316-328. Handlers run 333-350. The `stop_reason` check (354) and `_extract_code`
(357) are **outside** the `try`.

So a content block lacking `.type` propagates `AttributeError` straight out of
`fix_code`, contradicting its own docstring at `fixer.py:298-302` ("On any failure this
returns a human-readable message starting with `ERROR:` instead of raising").

**Action:** write this as a characterization test using
`pytest.raises(AttributeError)`. Add a comment in the test body reading, in substance:
*this documents a known defect — `fix_code` can raise, contrary to its docstring.
Do not fix in Phase 2.* Add to carry-forward for Phase 3: the fix is to widen the
`try` to enclose the `stop_reason` check and `_extract_code`, or to catch around the
extraction separately.

## E3 — §3.4 and §6: `save_fixed_code` uses `Path.write_text`, not `open()`

The write is `target.write_text(fixed_code, encoding="utf-8", newline="")` at
`fixer.py:418`, preceded by `target.parent.mkdir(parents=True, exist_ok=True)` at 417.
There is no `open()` call in this function.

**The monkeypatch recipe in §6 does not work.** `builtins.open is io.open` is `True`,
but `Path.open` ends in `return io.open(...)` — the name is resolved in the `io`
module namespace, so rebinding `builtins.open` has no effect. Proven empirically:
patching `builtins.open` let the write succeed and returned a real path.

**Action:** use

```python
monkeypatch.setattr("pathlib.Path.write_text", _boom)
```

`io.open` also works but is broader than needed and riskier around pytest's own
machinery. Prefer `Path.write_text` — it is the single call the source actually makes.

**Also correcting §6:**

- §6 test 3 ("directory does not exist — characterize"): it **succeeds**. Parents are
  created at line 417. Assert the file exists and the returned path is correct. There
  is no error to test.
- Do **not** test an illegal Windows filename expecting `OSError`. A colon in the name
  is treated by NTFS as an alternate-data-stream separator and silently succeeds.
- `newline=""` is confirmed in place; the CRLF round-trip test in §6.5 stands as written.

## E4 — §4.2: `FakeGithub(token)` is the wrong signature

The source calls `Github(auth=Auth.Token(self._token))` at `publisher.py:177`. The
constructor receives **no positional arguments** and one keyword argument, `auth=`,
holding a `github.Auth.Token` object — not a string.

**Action:**

```python
class FakeGithub:
    def __init__(self, auth=None, **kwargs):
        self.token = auth.token if auth is not None else None
```

Leave the real `Auth.Token` in place. It is an inert value object with no I/O, so the
fake stays honest about what the source actually constructs. Do not add a second fake
for `Auth`.

Patch target confirmed as `monkeypatch.setattr("src.core.publisher.Github", FakeGithub)` —
`from github import Auth, Github` at `publisher.py:30` binds the name into the
publisher module namespace, so patching `github.Github` would miss.

## E5 — §3.2: `temperature` is not passed

The spec listed it among the possible kwargs. `messages.create` receives exactly four:
`model` (`"claude-sonnet-5"`), `max_tokens` (`16000`), `system` (the module-level
`SYSTEM_PROMPT`, identity-equal), and `messages` (a one-element list whose `content`
is a plain string). Assert on those four and assert `"temperature" not in kwargs`.

## E6 — §3.7 and §11: there is no fixture named `project_tree_guard`

It is a `pytest_sessionstart` / `pytest_sessionfinish` hook pair in
`tests/conftest.py:109-125`, backed by `tests/helpers/tree_guard.py`. It snapshots
`(st_size, st_mtime_ns)` per file under the repo root and forces
`session.exitstatus >= 1` on any diff.

Consequences that matter for Phase 2:

- It fires at session finish and reports only a filename — it does **not** identify
  the culprit test. A stray write costs real debugging time. Use `tmp_path` always.
- `tmp_path` lives outside the repo root, so the guard never sees it. Confirmed.
- Files created under `tests/fakes/` before the run are in the opening snapshot, so
  they raise no diff.

## E7 — new: `CodeFixer.__init__` can raise, contrary to its docstring

`fixer.py:94-97` claims nothing in `__init__` ever raises. `fixer.py:120` is not
wrapped, so if `anthropic.Anthropic(...)` raises, the constructor propagates.

**Action:** one characterization test — inject a client class whose `__init__` raises,
assert `pytest.raises(RuntimeError)` on `CodeFixer(api_key=...)`. Note in a comment
that this contradicts the docstring. Do not fix.

Also note for all live-path tests: **the client is built in `__init__`, not in
`fix_code`.** The monkeypatch must be active before `CodeFixer(...)` is constructed.

## E8 — new: `_setup_error` is dead, and `fixer.py:312-313` is unreachable

`_setup_error` is assigned `None` at line 117 and read at line 313. It never takes a
non-`None` value, so line 313 always returns the literal fallback. The guard at 312
(`self._client is None`) is unreachable through the public API, because `__init__`
guarantees `_client` is non-`None` whenever `demo_mode` is `False`, and `demo_mode`
`True` returns earlier at 308-309.

These two statements count against the §10.2 coverage gate.

**Action:** one test that constructs a fixer, sets `fixer._client = None` by hand, and
asserts the return is `"ERROR: CodeFixer is not configured."` This is a deliberate,
one-off exception to the "test through the public API" default. The test body must
carry a comment saying so, and saying that it exists to cover dead code. Do not use
this as precedent elsewhere in Phase 2.

## E9 — §7.3: `_redact` is unreachable from two of the four publisher handlers

Handlers for `BadCredentialsException` (242-246) and `UnknownObjectException`
(247-253) return fixed literals that never interpolate library output. `_redact` can
only be exercised through `GithubException` (which redacts `error.data`) or the bare
`Exception` handler (which redacts `error`).

**Action:** route the §7.3 leak test through the bare `Exception` handler — inject a
`RuntimeError` whose message embeds the token, and assert the token string is absent
from the return value while `***REDACTED***` is present. Confirmed working.

Note `error.status` at line 258 is not redacted; it is an `int` from PyGithub, which
is fine.

## E10 — §7.4: two branches the spec missed

Both need tests:

1. **`get_contents` raises `UnknownObjectException` → `create_file` fallback.** This is
   not an error path. The inner handler at `publisher.py:220` calls `create_file`
   instead of `update_file` and the run succeeds, returning the PR URL. Assert the
   event sequence contains `create_file` and not `update_file`.
2. **`get_contents` returns a list (path is a directory) → partial write.** Returns
   `"ERROR: '<path>' is a directory in the repository, not a file."` from
   `publisher.py:205-209`. Because the `return` is inside the `for` loop, files earlier
   in `sorted(changes)` order have **already been committed**. Test with a two-file
   change where the second is the directory, and assert the first file's `update_file`
   event is present in the recorded sequence. This is the most interesting failure
   mode in the publisher and the spec omitted it entirely.

## E11 — new: the UTF-8 BOM leaks into `line_content`

`scan_for_api_usage` opens with `encoding="utf-8"` (not `utf-8-sig`) at
`scanner.py:249`, so a BOM survives as a literal `\ufeff` at the start of line 1.
A line-1 match returns `line_content` of `'\ufeffstripe.Charge.create(1)'`.

There is also a genuine one-character column offset between the tokenizer (binary
mode, which consumes the BOM via `detect_encoding`) and the line text. The report
attempted to construct a case where this flips a masked-region verdict and could not,
because masked regions are wide relative to a one-character shift. Do not spend more
time trying.

**Action:** pin the visible half with a characterization test asserting the `\ufeff`
appears in `line_content`. Carry forward: switching line 249 to `utf-8-sig` would fix
both the leak and the offset in one change. Not this phase.

## E12 — new: helper for constructing anthropic exceptions

None of the six SDK exception types can be constructed with no arguments.
`AuthenticationError`, `NotFoundError`, `RateLimitError` and `APIStatusError` need a
positional `message` plus keyword-only `response` and `body`. `APIConnectionError`
needs a keyword-only `request`.

`httpx` is already a transitive dependency of `anthropic`, and both `httpx.Request`
and `httpx.Response` are inert data objects that open no connection — safe under
`--disable-socket`.

**Action:** add a factory to `tests/fakes/`, e.g. `tests/fakes/anthropic_errors.py`,
exposing something like `make_status_error(cls, status, message)` and
`make_connection_error(message)`. Six near-identical construction blocks inlined
across six tests is the kind of duplication that rots.

For the `APIStatusError` handler test, the response's status must match what the
assertion expects — `error.status_code` is read from the response you supply.

Handler ordering was verified correct: all six are reachable, none shadowed. Note that
`anthropic.APIError` and `anthropic.AnthropicError` have no dedicated handler and fall
through to the bare `Exception` at 349 — a clean way to reach handler #6 with a real
SDK type rather than a synthetic one.

Distinguishing substrings for the six, all confirmed distinct: `"API key was
rejected"`, `"was not found"`, `"Rate limited"`, `"Could not reach the API"`, `"The API
returned"`, `"Unexpected problem while calling Claude"`.

## E13 — §4: `tests/fakes/` needs an `__init__.py`

`tests/helpers/` has one and is the only directory under `tests/` that does.
`pytest.ini` sets `pythonpath = .`, so `tests/fakes/` must match to be importable as
`from tests.fakes.fake_anthropic import FakeAnthropic`.

`testpaths = tests` is set with no custom `python_files`, so the default `test_*.py` /
`*_test.py` patterns apply. Files named `fake_anthropic.py`, `fake_github.py` and
`anthropic_errors.py` will not be collected. The naming in §4.1/§4.2 is safe.

## E14 — §6: the empty-path branch writes into the CWD

`save_fixed_code("", code)` returns the *relative* string `'fixed_code.py'` and writes
into the process working directory (`fixer.py:400-402`), which under pytest is the
repo root. Any test touching this branch must call `monkeypatch.chdir(tmp_path)` first
or it will trip the tree guard and fail the whole session.

## E15 — scanner fallback behaviour is confirmed and testable

`tokenize` failures are caught at `scanner.py:172-180` — the tuple
`(tokenize.TokenError, SyntaxError, UnicodeDecodeError, OSError)` — and the file falls
back to a plain line-by-line scan **including comments and strings**. Verified raising
types: invalid Python → `TokenError`; null bytes → `SyntaxError`; latin-1 bytes with no
coding declaration → `SyntaxError`. All three land in the tuple.

`UnicodeDecodeError` cannot occur on the *line read* — `errors="ignore"` at line 249
drops undecodable bytes silently. It is only reachable on the tokenize path.

`files_scanned` does **not** count files that fail to open (`continue` at 251-253
precedes the increment at 256), but **does** count files that fail to tokenize.

An explicit `# -*- coding: latin-1 -*-` declaration tokenizes cleanly with no fallback.

---

## Revised expectations

§10.2's 85% target on `fixer.py` stands, with E8 accounting for the two dead
statements. §10.6 ("every `except` clause in 312-361 has a dedicated test") stands —
all six are reachable, confirmed.

Add to §13, the report-back list: state explicitly whether E2's `AttributeError`
characterization test and E7's constructor test are the only two tests in Phase 2 that
document defects rather than intended behaviour. If a third appears, name it.
