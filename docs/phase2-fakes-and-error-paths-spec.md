# Phase 2 Spec — Fakes and Error Paths

**File:** `docs/phase2-fakes-and-error-paths-spec.md`
**Project:** `self-maintaining-apis`
**Prerequisites:** Phase 0 (test harness) and Phase 1 (scanner + fixer pure logic) complete and committed.
**Owner:** Dhruv Makwana — beginner Python, Windows, PowerShell, VS Code + Claude Code extension.

---

## 0. Gate — do this before writing a single line of Phase 2

Do not start Phase 2 until both of these are true. If either fails, stop and report.

**0.1 — Phase 1 is committed and the tree is clean.**

```powershell
cd "C:\Maintaining Apis\self-maintaining-apis"
git status --porcelain
```

Expected: **empty output**. If it is not empty, Phase 1 was never committed. Commit it fix-first so that no single commit is red:

```powershell
git add src/core/paths.py src/core/scanner.py src/main.py
git commit -m "fix: scanner no longer counts its own *_fixed.py output"

git add tests/conftest.py tests/meta/conftest.py tests/unit/conftest.py tests/integration/conftest.py tests/meta/test_env_isolation.py
git commit -m "fix(tests): scope markers per directory, patch load_dotenv at root"

git add tests/unit/
git commit -m "Phase 1: scanner and fixer unit tests"

git push
git status --porcelain
```

**0.2 — PR #1 is closed, not merged.**

PR #1 (branch `auto-api-fix/20260801-175241`, commit `6ee0c6f`) must be **closed without merging**. Merging it would rewrite `examples/payment.py`, which is the only live test case for the whole pipeline, and would land the demo fixer's self-contradicting docstring on `main`.

```powershell
gh pr view 1 --json state,mergedAt
```

Expected: `state` is `CLOSED` and `mergedAt` is `null`. If `gh` is not installed, check it in the browser at https://github.com/Dhruv2304-mak/self-maintaining-apis/pulls?q=is%3Apr. If it is still open, close it (do not merge) and say so in your report.

**0.3 — Baseline is green.**

```powershell
.\venv\Scripts\python.exe -m pytest
```

Expected: 165 passed, exit code 0. Record the exact number; you will need it in §9.2.

---

## 1. Goal

Phase 1 covered logic that runs entirely in memory. Everything left uncovered in `fixer.py` and `publisher.py` is code that talks to something outside the process — the Anthropic API, the GitHub API, or the filesystem when it misbehaves. Phase 2 covers that code **without ever touching the network**, by hand-writing small fake clients that stand in for the real SDKs.

Concretely, Phase 2 must:

1. Build a hand-written fake Anthropic client and a hand-written fake GitHub client under `tests/fakes/`.
2. Cover `fixer.py` lines ~312–361 (the live Anthropic call plus its six exception handlers) and ~419–422 (the `OSError` write handler).
3. Cover `publisher.py` — dry-run mode, token mode, `_redact()`, branch naming, and its API failure paths.
4. Cover filesystem and encoding error paths in the scanner: missing files, unreadable files, UTF-8 BOM, `coding:` declarations, and `tokenize` failures on invalid Python.
5. Add two meta-tests carried forward from Phase 1 (§8).
6. Raise `fixer.py` and `publisher.py` to **≥85% statement coverage each**.

Phase 2 does **not** cover `detector.py` (Phase 4, after a fetch/parse split) or end-to-end orchestration in `main.py` (Phase 3).

---

## 2. Ground rules — unchanged from Phase 0 and Phase 1

These are non-negotiable. They exist because breaking them has already cost this project real debugging time.

- **Do not modify anything under `src/`.** Not to make a test pass, not to make it "cleaner", not to add dependency injection. If a test is hard to write because of how `src/` is shaped, that is a finding — write it up in your report and work around it in the test. Ask before touching `src/`.
- **Characterize, don't guess.** If you are unsure what the code actually does in some case, write a test that asserts the behaviour you observed by running it, and label it in a comment as a characterization test. Do not write a test that asserts what you think the code *should* do.
- **Tests never touch the network.** `--disable-socket` is on globally. Every fake must be pure in-memory Python. No `time.sleep`, no retries with real delays, no `requests`, no `playwright`.
- **Do not remove the targeted `filterwarnings` downgrade in `pytest.ini`.** It is load-bearing: `pytest-socket` 0.8.0 calls `warnings.warn()` inside `SocketBlockedError.__init__` before `super().__init__()`, so under `error` a blocked socket surfaces as a `UserWarning` and the real exception is never constructed.
- **Do not change `.coveragerc`.** `include_namespace_packages=True` under `[report]` is required because `src/` and `src/core/` have no `__init__.py`. Without it, coverage silently measures only `main.py`.
- **Do not add `__init__.py` to `src/` or `src/core/`** during this phase. It is the more conventional alternative to namespace packages, but changing it mid-phase would invalidate the coverage baseline.
- **No `unittest.mock` auto-chaining for the fakes.** `MagicMock()` returns a new mock for every attribute you touch, so a typo in a test silently passes. The fakes must be plain classes you can read. `monkeypatch` (the pytest built-in) *is* allowed and expected — it is how the fakes get injected. `pytest-mock`'s `mocker` fixture is allowed only for `monkeypatch`-style patching, not for building behaviour.
- **`filterwarnings=error` is on.** If a fake or a test emits a `DeprecationWarning`, the test fails. Write clean code.

---

## 3. Step 1 — Read the source and report. Write no tests yet.

This step has caught real errors in this spec twice already. Do it properly.

Read these files end to end: `src/core/fixer.py`, `src/core/publisher.py`, `src/core/scanner.py`, `src/core/paths.py`, `tests/conftest.py`, `tests/unit/conftest.py`, `tests/helpers/tree_guard.py`, `pytest.ini`, `.coveragerc`, `.gitattributes`.

Then produce a report answering **every** question below. Where the answer is "the source does X", quote the line number. Do not answer from memory of how these SDKs usually work.

### 3.1 — Fixer: how the Anthropic client is created

- Is `anthropic` imported at module top level, or inside the function?
- Is the client constructed once at import, once per call, or stored on `self`?
- What exact expression constructs it (`anthropic.Anthropic(...)`, `Anthropic(...)`, something else)?
- Where does the API key come from — constructor argument, `os.environ`, `os.getenv` with a default?
- **Therefore: what is the single name I must `monkeypatch` to inject a fake?** State it as a concrete `monkeypatch.setattr("...", ...)` target string.

### 3.2 — Fixer: the live call and its response shape

- What method is called, with what keyword arguments (model, max_tokens, messages, system, temperature)?
- How is the response read? `response.content[0].text`? Something else? Is there any indexing that could raise `IndexError` on an empty response?
- Is the returned text post-processed (stripped, fence-removed, banner-prepended) before being returned?

### 3.3 — Fixer: the six exception handlers (lines ~312–361)

For **each** `except` clause, report:

| # | Exception type(s) caught, exactly as written | Exact return value / string prefix | Line numbers |
|---|---|---|---|
| 1 | | | |
| ... | | | |

Do not guess the SDK exception names. Read them. If a handler catches a bare `Exception`, say so. If two handlers catch types where one is a subclass of the other, note the ordering — it determines which one a test can actually reach.

### 3.4 — Fixer: `save_fixed_code` and the write error path (~419–422)

- What exception type does the `except` at ~419 catch — `OSError`, `IOError`, `Exception`?
- What is the exact return string?
- What `open()` arguments are used (mode, `encoding`, `newline`)? Confirm `newline=""` is still there.
- Does it create parent directories?

### 3.5 — Publisher

- Full signature of `__init__` and every public method.
- Exact expression that constructs the GitHub client — again, give me the `monkeypatch.setattr` target string.
- Where is `GITHUB_TOKEN` read, and what exactly triggers automatic dry-run?
- What does `_redact()` take and return? What does it consider secret?
- How is the branch name built from `branch_prefix` and the timestamp? Is the timestamp taken from `datetime.now()`, and is it UTC or local? (This determines whether a test needs to freeze time.)
- What is the exact sequence of PyGithub calls on the happy path? List them in order — `Github(...)`, `get_repo`, `get_branch`, `create_git_ref`, `get_contents`, `update_file`, `create_pull`, or whatever it actually is.
- What does the method return on success — a PR object, a URL string, a dict?

### 3.6 — Scanner error paths

- How does the scanner open files (encoding, `errors=` parameter)?
- What happens on a `UnicodeDecodeError` — is it caught, and what is the file counted as?
- What happens when `tokenize` raises on invalid Python? Is there a fallback path, or is the file skipped?
- Does `files_scanned` count files that failed to read?

### 3.7 — Test infrastructure

- Does `tests/helpers/` contain an `__init__.py`? Whatever it does, `tests/fakes/` must match it.
- Does `pytest.ini` set `testpaths` or a custom `python_files` pattern? This determines whether files under `tests/fakes/` risk being collected as tests.
- Exactly how does `project_tree_guard` decide a file is an unexpected leftover, and what will it do if a test writes `payment_fixed.py` into a `tmp_path` directory (which is outside the project tree) versus into the repo?

**Stop here and show me the report before continuing.** I will confirm or correct it.

---

## 4. Step 2 — Build the fakes

Location: `tests/fakes/`. Files must be named so pytest does **not** collect them as tests — use `fake_anthropic.py` and `fake_github.py`, never `test_*.py`. Match `tests/helpers/` on the `__init__.py` question.

### 4.1 — `tests/fakes/fake_anthropic.py`

Requirements:

- A `FakeAnthropic` class whose constructor accepts whatever the real one accepts (per §3.1) and **records** it — at minimum the API key — on `self.init_kwargs`.
- A `.messages` attribute exposing a `.create(**kwargs)` method.
- `.create()` appends the full kwargs dict to `self.calls` (a list) so tests can assert on the prompt, model, and `max_tokens`.
- `.create()` behaviour is configurable at construction time by exactly one of:
  - `response_text="..."` — return a canned successful response, or
  - `raise_exc=SomeException("msg")` — raise that exception.
  If both or neither are given, raise `ValueError` immediately. A fake that silently does the wrong thing is worse than no fake.
- The success response must be a small class (`FakeMessage`, `FakeTextBlock`) that mirrors the **real** shape you found in §3.2 — typically `.content` as a list of blocks each having `.text`. Do not return a dict if the source does attribute access.
- Add a `FakeAnthropicEmptyContent` variant returning `content=[]`, so §5.4 can test the `IndexError` case if §3.2 showed one is reachable.
- No sleeps, no sockets, no imports from `src/`.

Write a short module docstring explaining, in plain English, why this exists rather than a `MagicMock`: so that a typo in a test raises `AttributeError` instead of silently passing.

### 4.2 — `tests/fakes/fake_github.py`

Requirements:

- `FakeGithub(token)` — records the token on `self.token`.
- `.get_repo(full_name)` — returns a `FakeRepo` if `full_name` matches the one it was configured with; otherwise raises the same exception type the real PyGithub raises for a missing repo (get the type from §3.5 / the PyGithub source, do not invent it).
- `FakeRepo` implements **only** the methods §3.5 said are actually called, with the same signatures. Do not implement the whole PyGithub surface.
- Every mutating call appends a tuple like `("create_git_ref", ref, sha)` to a shared `self.events` list, in order. Tests assert on `events` — this is how we verify the *sequence*, not just the outcome.
- `create_pull(...)` returns a `FakePR` with at least `.number` and `.html_url`.
- Configurable failure injection: a constructor argument like `fail_on="create_pull"` plus `fail_with=SomeException(...)` that makes exactly that call raise. This is how §7.4 tests error paths without a separate fake per scenario.

### 4.3 — Sanity tests for the fakes themselves

Add `tests/unit/test_fakes_selfcheck.py` (marker: `unit`). Three or four small tests:

- `FakeAnthropic(response_text=..., raise_exc=...)` raises `ValueError`.
- A successful `.create()` records the call and returns a block whose `.text` matches.
- `FakeGithub.get_repo("nope/nope")` raises the expected type.
- `FakeGithub(fail_on="create_pull", ...)` raises only on `create_pull` and records the earlier events.

A fake with a bug produces a green suite that tests nothing. This is cheap insurance.

---

## 5. Step 3 — `fixer.py`, the live Anthropic path

New file: `tests/unit/test_fixer_live_path.py`, marker `unit`.

### 5.1 — Happy path

Inject `FakeAnthropic(response_text=...)` via the `monkeypatch` target from §3.1. Call `fix_code()` with `demo_mode` off (confirm from source exactly how the live path is selected — it may be a constructor flag, an env var, or the presence of a key). Assert:

- The returned string equals the fake's text, after whatever post-processing §3.2 described.
- `fake.calls` has length 1.
- The prompt sent contains both `change_description` and the original code. Assert on substrings, not on the whole prompt — the prompt wording will change and a whole-string assertion would be a brittle test.
- `model` and `max_tokens` match what the source passes.

### 5.2 — API key handling

- With no key in the environment (the `clean_env` fixture already handles this), assert the documented behaviour — does it fall back to demo mode, or return an `ERROR:` string? Characterize what actually happens.
- With a key set via `monkeypatch.setenv`, assert the fake received it.
- Assert the key never appears in the returned string. If a test needs a key value, use `sk-ant-fake-DO-NOT-USE`.

### 5.3 — One test per exception handler

For each row of your §3.3 table, one test:

```
FakeAnthropic(raise_exc=<the exact exception type>)
  -> fix_code(...) returns a string
  -> the string starts with "ERROR:"
  -> the string contains <the distinguishing text for that handler>
  -> pytest.raises is NOT used — fix_code must never propagate
```

Assert on a distinguishing substring per handler, so that a copy-paste bug where two handlers return the same message is caught. If you find two handlers that genuinely return identical strings, that is a finding — report it, and pin it with a characterization test rather than fixing it.

If any SDK exception cannot be constructed without arguments (several require a `response` or `body`), note it in your report and construct it the minimum valid way. Do not substitute a different exception type silently.

### 5.4 — Malformed responses

If §3.2 showed indexing that could raise, add tests for empty `content`, and for a block missing `.text`. Characterize: does the caller crash, or is it caught by handler #6?

### 5.5 — Coverage checkpoint

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit -q --cov=src/core/fixer --cov-report=term-missing
```

Report the remaining missing lines before moving on.

---

## 6. Step 4 — `fixer.py`, the write error path

New file: `tests/unit/test_fixer_write_errors.py`, marker `unit`.

**On Windows, do not try to create permission errors with `os.chmod`.** The read-only bit behaves differently from POSIX permissions and produces flaky tests. Instead, monkeypatch the builtin:

```python
def _boom(*args, **kwargs):
    raise PermissionError(13, "Permission denied")

monkeypatch.setattr("builtins.open", _boom)
```

Scope the patch as narrowly as you can, and be aware that patching `builtins.open` globally can break pytest's own machinery if it is left active across a teardown — `monkeypatch` undoes it automatically, but keep the patched region to a single call.

Tests:

1. `PermissionError` on write → returns the exact string from §3.4, does not raise.
2. `OSError(28, "No space left on device")` → same handler, same string shape.
3. Directory does not exist → characterize. Does it create parents, or return an error?
4. Empty `fixed_code` → already pinned in Phase 1 as "refuses"; do not duplicate, just confirm the existing test still passes.
5. Confirm the happy path still writes with `newline=""` — write CRLF content to a `tmp_path` file and assert the bytes on disk are unchanged. Use `tmp_path`, never the repo tree, so `project_tree_guard` stays quiet.

---

## 7. Step 5 — `publisher.py`

New file: `tests/unit/test_publisher.py`, marker `unit`.

### 7.1 — Dry run

- No `GITHUB_TOKEN` in env (the `clean_env` fixture gives you this; note that the real `.env` on this machine **does** contain a working token, which is exactly why the `no_dotenv` autouse fixture from Phase 1 matters — verify it is in force here).
- Assert dry-run engages automatically.
- Assert the fake GitHub client was **never constructed** — `fake.events` empty, or better, patch the constructor with something that raises if called at all.

### 7.2 — Token mode, happy path

- `monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_do_not_use")`.
- Inject `FakeGithub`.
- Assert `fake.events` matches the exact expected sequence from §3.5, in order.
- Assert the returned value (PR object / URL / dict — whatever §3.5 said) is correct.

### 7.3 — `_redact()`

- Direct unit tests: a string containing the token → token replaced; a string without it → unchanged; empty string; `None` if the signature allows it.
- Then the integration-flavoured assertion that matters: trigger a failure while a token is set, and assert the token string does not appear anywhere in the returned error message. This is the test that actually protects the user.

### 7.4 — Failure paths

Using `fail_on` from §4.2, one test each for the calls that can realistically fail: repo not found, branch ref already exists, file update conflict, PR creation rejected. For each, assert the publisher returns a sensible error rather than raising, **if** that is what the source does. If the source does propagate, characterize that instead and flag it as a Phase 3 candidate.

### 7.5 — Branch naming

If §3.5 showed the branch name embeds a timestamp, freeze it — monkeypatch the `datetime` reference the module actually uses (patch it where it is *looked up*, not where it is defined) and assert the branch equals `f"{branch_prefix}/20260801-175241"` or whatever the format string produces. Also test a custom `branch_prefix`.

---

## 8. Step 6 — Meta-tests carried forward from Phase 1

Add to `tests/meta/`, marker `meta`.

### 8.1 — `DOTENV_IMPORTING_MODULES` cannot go stale

`tests/meta/test_dotenv_registry.py`: walk `src/`, read each `.py` file as text, find every module containing `from dotenv import load_dotenv` (also match `import dotenv` if present), and assert every such module appears in `DOTENV_IMPORTING_MODULES` in `tests/conftest.py`. Import the list from conftest rather than re-parsing it.

The failure message must be actionable — name the offending file and say "add it to DOTENV_IMPORTING_MODULES in tests/conftest.py". A meta-test with a cryptic message is a meta-test people delete.

### 8.2 — Marker partition invariant

`tests/meta/test_marker_partition.py`: replace any fixed test-count assertion with the durable invariant — the number of tests collected under `-m unit` plus `-m meta` plus `-m integration` equals the total collected. Use pytest's collection programmatically (`pytest.main` with a collecting plugin, or parse `--collect-only -q` output from a subprocess using `sys.executable`).

If a subprocess is needed, remember `--disable-socket` applies to the child too, and the child must run from the project root. Prefer an in-process approach if you can make it clean.

This is what catches the marker-leak class of bug that bit Phase 1, and unlike `assert count == 165` it does not need editing every time a test is added.

---

## 9. Verification

Run all of these from `C:\Maintaining Apis\self-maintaining-apis`. Paste the real output — not a summary — into your report.

### 9.1 — Full suite

```powershell
.\venv\Scripts\python.exe -m pytest
```

### 9.2 — Marker partition, by hand as well as by test

```powershell
.\venv\Scripts\python.exe -m pytest -m unit --collect-only -q | Select-Object -Last 3
.\venv\Scripts\python.exe -m pytest -m meta --collect-only -q | Select-Object -Last 3
.\venv\Scripts\python.exe -m pytest -m integration --collect-only -q | Select-Object -Last 3
.\venv\Scripts\python.exe -m pytest --collect-only -q | Select-Object -Last 3
```

The three category totals must sum to the overall total.

### 9.3 — Coverage

```powershell
.\venv\Scripts\python.exe -m pytest --cov=src --cov-report=term-missing
```

Report the per-file table in full.

### 9.4 — No network was attempted

```powershell
.\venv\Scripts\python.exe -m pytest -p no:randomly -q
```

Any `SocketBlockedError` means a fake is incomplete and something reached for the real SDK. Fix the fake; do not add `@pytest.mark.enable_socket`.

### 9.5 — Tree is clean

```powershell
git status --porcelain
```

Only intended new files. No stray `*_fixed.py`, no `payment_fixed_fixed.py`, no `.coverage` variants outside what `.gitignore` covers.

---

## 10. Acceptance criteria

Phase 2 is done when **all** of these hold:

1. Full suite passes, exit code 0, no warnings, no xpass.
2. `src/core/fixer.py` ≥ **85%** statement coverage.
3. `src/core/publisher.py` ≥ **85%** statement coverage.
4. `src/core/scanner.py` stays ≥ 97% (no regression).
5. `src/core/paths.py` stays at 100%.
6. Every `except` clause in `fixer.py` lines ~312–361 has a dedicated test asserting a distinguishing message.
7. `tests/fakes/` contains hand-written fakes with self-check tests; no `MagicMock` used to construct behaviour anywhere in Phase 2.
8. Both meta-tests from §8 exist and pass.
9. No file under `src/` was modified. `git diff --stat 5c06617 -- src/` shows only the Phase 1 fixes already committed at the gate.
10. Zero network calls; `--disable-socket` never disabled or bypassed.

`detector.py` and `main.py` remaining at 0% is expected and acceptable — they are Phase 3 and Phase 4. Do not chase the 85% *total* gate this phase.

---

## 11. Hard boundaries

- Do not modify `src/`.
- Do not modify `pytest.ini`, `.coveragerc`, or `.gitattributes`.
- Do not add `@pytest.mark.enable_socket` anywhere.
- Do not add `__init__.py` to `src/` or `src/core/`.
- Do not add new runtime dependencies. Everything needed is installed.
- Do not write to the repo tree from tests — use `tmp_path`.
- Do not merge PR #1.
- If any of these blocks you, stop and report rather than working around it.

---

## 12. Commit plan

One commit per logical unit, each independently green:

```powershell
git add tests/fakes/ tests/unit/test_fakes_selfcheck.py
git commit -m "Phase 2: hand-written fake Anthropic and GitHub clients"

git add tests/unit/test_fixer_live_path.py
git commit -m "Phase 2: fixer live API path and exception handler tests"

git add tests/unit/test_fixer_write_errors.py
git commit -m "Phase 2: fixer write error paths"

git add tests/unit/test_publisher.py
git commit -m "Phase 2: publisher dry-run, token mode, redaction and failure paths"

git add tests/meta/
git commit -m "Phase 2: meta-tests for dotenv registry and marker partition"

git add docs/phase2-fakes-and-error-paths-spec.md
git commit -m "docs: Phase 2 spec"

git push
```

---

## 13. What to report back

1. The §3 source report, **before** any test code.
2. After implementation: full output of §9.1 through §9.5.
3. A list of every characterization test you added, with one line each on what surprised you.
4. Any place where the spec was wrong about the source. This has happened twice. Say so plainly rather than bending the tests to fit.
5. Anything you think should carry forward into Phase 3.
