# Phase 0 — Testing Harness: Claude Code Implementation Spec

**Project:** `C:\Maintaining Apis\self-maintaining-apis`
**Scope:** Test infrastructure and safety guarantees only.
**Deliverable:** One Git commit. No product tests.
**Estimated effort:** One session (2–4 hours).

---

## 0. Read this first

This phase produces **zero tests of scanner, fixer, detector, publisher, or main**. Do not write them. Do not import those modules anywhere except where explicitly specified below. If you find yourself opening `src/core/scanner.py`, stop — that is Phase 1.

The purpose of this phase is to make it *structurally impossible* for later tests to contact GitHub, spend Anthropic credits, launch a browser, read real credentials, or modify the project working tree. Everything below serves that goal.

The only tests written in this phase are **meta-tests**: tests that prove the safety harness itself works.

---

## 1. Dependencies to install

Run in the project venv:

```powershell
.\venv\Scripts\python.exe -m pip install pytest-socket pytest-cov pytest-mock
```

`pytest` 9.1.1 is already installed. Do not upgrade or downgrade it.

After installing, record exact versions:

```powershell
.\venv\Scripts\python.exe -m pip freeze | Select-String "pytest|coverage|mock"
```

If a `requirements-dev.txt` does not exist, create one containing the four dev dependencies with pinned versions (`pytest`, `pytest-socket`, `pytest-cov`, `pytest-mock`). If `requirements.txt` exists, leave it untouched — dev dependencies go in the new file.

---

## 2. Directory structure to create

```
tests/
├── conftest.py
├── unit/
│   └── .gitkeep
├── integration/
│   └── .gitkeep
├── fixtures/
│   ├── repos/.gitkeep
│   ├── html/.gitkeep
│   └── responses/.gitkeep
├── helpers/
│   ├── __init__.py
│   └── tree_guard.py
└── meta/
    ├── test_network_blocking.py
    ├── test_env_isolation.py
    ├── test_tmp_isolation.py
    └── test_tree_guard.py
```

Notes:

- `tests/` already exists and is empty. Populate it; do not delete and recreate.
- `tests/helpers/` is a real Python package and needs `__init__.py`. No other directory gets one — pytest's rootdir-based collection handles the rest, and `pythonpath` in `pytest.ini` (§3) makes `tests.helpers` importable.
- `tests/meta/` holds only harness self-tests. It is deliberately separate from `unit/` and `integration/` so it can be excluded from ordinary runs later.
- `.gitkeep` files are empty placeholders so the empty directories are committed.

---

## 3. `pytest.ini` (new file, project root)

Create at the project root — not inside `tests/`.

```ini
[pytest]
minversion = 9.0
testpaths = tests
pythonpath = .

addopts =
    --strict-markers
    --strict-config
    --disable-socket
    -ra

markers =
    unit: fast, isolated tests of a single module
    integration: multiple internal modules composed, all external boundaries faked
    meta: tests that verify the test harness itself
    slow: takes longer than one second
    network_forbidden: documentary marker; the socket block does the actual enforcement

filterwarnings =
    error
    default::DeprecationWarning
```

Rationale for each non-obvious choice:

- **`--strict-markers`** turns a typo'd marker into an error rather than a silent no-op. Without it, `@pytest.mark.integraton` quietly does nothing.
- **`--strict-config`** makes an unknown key in this file an error.
- **`--disable-socket`** is the core safety guarantee, applied globally by default. It is in `addopts` rather than a fixture so it holds even for tests that somehow bypass conftest.
- **`-ra`** shows a short summary of everything non-passing at the end of the run.
- **`pythonpath = .`** puts the project root on `sys.path` so both `src.*` and `tests.helpers` import cleanly without an `__init__.py` in every directory.
- **`filterwarnings = error`** with a `DeprecationWarning` exemption: warnings from our own code become failures, but third-party deprecations (likely on Python 3.14) do not block the suite.

Coverage is deliberately **not** in `addopts`. Coverage instrumentation slows the suite, and Phase 1 will run these tests on every file save. Coverage is invoked explicitly (§8).

---

## 4. `.coveragerc` (new file, project root)

```ini
[run]
source = src
branch = True
omit =
    */venv/*
    */__pycache__/*
    src/__main__.py

[report]
show_missing = True
skip_covered = False
exclude_lines =
    pragma: no cover
    if __name__ == .__main__.:
    raise NotImplementedError
    if TYPE_CHECKING:

[html]
directory = htmlcov
```

`branch = True` is not optional. This codebase is dense with `if/else` fallback paths — Playwright-then-requests, update-then-create, tokenize-then-plain-scan — and line coverage on that shape is misleadingly flattering.

`source = src` means coverage measures the product code only. `tests/` is never measured.

---

## 5. `.gitattributes` (new file, project root)

```
tests/fixtures/** -text
tests/fixtures/** binary
```

**This is the single most important line in the phase and the easiest to skip.**

The repository has `core.autocrlf=true`. Without this rule, any fixture file committed with LF endings is checked out with CRLF on Windows. A future test asserting "LF input produces LF output" would then be handed CRLF input, and would pass while verifying nothing. The bug it exists to catch would ship.

Marking the fixture tree as binary disables all end-of-line conversion for it.

Add to `.gitignore` if not already present:

```
htmlcov/
.coverage
.pytest_cache/
```

---

## 6. `tests/conftest.py` — the safety fixtures

Four safety mechanisms plus one path helper. Implement each as described; do not add anything beyond this list in Phase 0.

### 6.1 `clean_env` — autouse, function scope

Removes credential environment variables before every test, using `monkeypatch.delenv(..., raising=False)` so it is safe when they are absent.

Variables to scrub, at minimum:
`GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_PAT`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`

Define this list as a module-level constant so later phases can extend it in one place.

The fixture must also set a sentinel variable — `SELF_MAINTAINING_APIS_TESTING=1` — which product code may later consult, and which meta-tests use to confirm the fixture ran.

### 6.2 `no_dotenv` — autouse, function scope

Prevents `.env` from being loaded during tests. The real `.env` contains a working GitHub token; nothing in the test suite may ever see it.

Implementation: monkeypatch `dotenv.load_dotenv` and `dotenv.main.load_dotenv` to a no-op that returns `False` and records that it was called. Also monkeypatch `dotenv.find_dotenv` to return an empty string.

Patch both names — modules that did `from dotenv import load_dotenv` at import time hold a reference to the original, so patching only the module attribute misses them. Where a `src` module has already bound the name, later phases will patch at that module's namespace; note this limitation in a comment rather than solving it now.

Must be ordered **after** `clean_env` so a `.env` load cannot repopulate a scrubbed variable. Express the ordering by having `no_dotenv` request `clean_env` as an argument.

### 6.3 Network blocking — configuration plus a defensive fixture

Primary enforcement is `--disable-socket` in `pytest.ini` (§3). No fixture is needed for the block itself.

Add one autouse function-scoped fixture, `assert_socket_disabled`, that verifies pytest-socket is actually active and fails loudly at setup if it is not. This catches the scenario where someone runs `pytest -p no:socket` or edits `addopts`, which would silently remove the guarantee everything else depends on.

Do **not** add a `--allow-hosts` allowlist. There is no host any test is permitted to contact.

For later phases: a test needing a socket must opt in explicitly with pytest-socket's `enable_socket` marker or fixture, and any such opt-in requires review. None exist in Phase 0.

### 6.4 `project_tree_guard` — session scope, hook-driven

Fails the entire run if any tracked project file is modified during testing. This is the backstop for temp-directory isolation: if a path bug lets a test write outside `tmp_path`, the run fails visibly instead of quietly corrupting source.

Implement the snapshot logic in `tests/helpers/tree_guard.py` as two plain functions:

- **`snapshot(root)`** — walks the tree and returns a mapping of relative path to `(size, mtime_ns)`. Excludes: `.git`, `venv`, `__pycache__`, `.pytest_cache`, `htmlcov`, `node_modules`, `.coverage`, and anything under `tests/fixtures` that later phases generate at runtime.
- **`diff(before, after)`** — returns three lists: added, removed, modified.

Wire it up with `pytest_sessionstart` and `pytest_sessionfinish` hooks in `tests/conftest.py`. On a non-empty diff, print each offending path with its change type and set the session exit status to failure.

Keep the logic in `helpers/` rather than inline in the hooks, because §9.4 meta-tests it directly.

### 6.5 `fixtures_dir` — session scope

Returns the absolute `Path` to `tests/fixtures/`. Trivial, but it prevents every later fixture from computing the path itself.

### Explicitly deferred

`frozen_clock`, `synthetic_repo`, `fake_github`, `fake_anthropic_client`, `fake_playwright`, and all file-content fixtures. They belong to Phases 1–4. Adding them now inflates this commit and they cannot be meaningfully tested until there is product code exercising them.

---

## 7. `tests/unit/conftest.py` and `tests/integration/conftest.py`

Create both as near-empty files containing only an autouse fixture that applies the corresponding marker to every test in the directory, plus a short docstring stating what belongs there and what does not.

This establishes the conftest hierarchy so Phase 1 has an obvious place to put scoped fixtures, and it means directory placement and marker selection can never drift apart.

---

## 8. Meta-tests

Roughly 12–16 test functions across four files. These are the only tests in this phase.

### 8.1 `tests/meta/test_network_blocking.py`

- A direct `socket.socket()` connection attempt raises pytest-socket's blocked-socket error
- `socket.create_connection` to any host raises
- A `requests.get` call raises rather than performing a request
- A DNS lookup via `socket.getaddrinfo` raises
- The `assert_socket_disabled` fixture reports the guard as active

Use an unroutable target such as `127.0.0.1:9` so a mistakenly-unblocked call fails fast rather than hanging.

### 8.2 `tests/meta/test_env_isolation.py`

- Each scrubbed variable is absent from `os.environ` during a test
- The `SELF_MAINTAINING_APIS_TESTING` sentinel is present and set to `1`
- **Contamination test:** at module scope — before any fixture runs — set `os.environ["GITHUB_TOKEN"]` to a fake value, then assert inside the test body that it is gone. Module-level code executes at import, fixtures execute later, so this deterministically proves the scrub actually removes a pre-existing value rather than merely observing one that was never set.
- Calling `dotenv.load_dotenv()` does not populate any scrubbed variable and returns falsy
- `dotenv.find_dotenv()` returns empty

### 8.3 `tests/meta/test_tmp_isolation.py`

- `tmp_path` exists, is a directory, and is empty at test start
- A file written to `tmp_path` is readable back with exact bytes
- Two tests receive different `tmp_path` values (record the path from one test in a module-level list and assert difference in the next — acceptable coupling here, since proving isolation requires comparing across tests)
- **Binary round-trip:** write bytes containing `\n` in binary mode, read back in binary mode, assert the bytes are unchanged. This proves the read/write discipline that Phase 1's line-ending tests depend on, and confirms nothing in the environment is normalising newlines.
- `monkeypatch.chdir(tmp_path)` leaves the real working directory restored afterwards

### 8.4 `tests/meta/test_tree_guard.py`

Tests the `snapshot`/`diff` functions from `helpers/tree_guard.py` directly, against a throwaway tree built in `tmp_path` — never against the real project tree.

- Snapshot of an unchanged tree diffs empty
- A modified file is reported as modified
- A new file is reported as added
- A deleted file is reported as removed
- Excluded directories (`__pycache__`, `venv`) are absent from the snapshot
- Content change with a preserved mtime is still detected via size

Mark every file in `tests/meta/` with the `meta` marker via an autouse fixture in a `tests/meta/conftest.py`.

---

## 9. Verification commands

Run in order from the project root. All must pass before committing.

**1 — Collection succeeds and markers are registered**

```powershell
.\venv\Scripts\python.exe -m pytest --collect-only -q
.\venv\Scripts\python.exe -m pytest --markers
```

Expect the meta-tests collected and all five custom markers listed.

**2 — Full harness run**

```powershell
.\venv\Scripts\python.exe -m pytest
```

Expect all meta-tests passing, zero warnings, runtime under 3 seconds.

**3 — Marker selection works**

```powershell
.\venv\Scripts\python.exe -m pytest -m meta
.\venv\Scripts\python.exe -m pytest -m "not meta"
```

The second must collect zero tests without error.

**4 — Strict markers actually reject typos**

```powershell
.\venv\Scripts\python.exe -m pytest -m nonexistent_marker
```

Expect an error, not a silent empty run.

**5 — The network block is real**

Temporarily disable it and confirm the meta-tests fail:

```powershell
.\venv\Scripts\python.exe -m pytest tests/meta/test_network_blocking.py -p no:socket
```

Expect failures. This proves the tests are testing something. **Re-run command 2 afterwards to confirm the harness is back to green.**

**6 — Coverage configuration is valid**

```powershell
.\venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing
```

Expect a coverage report over `src` showing near-zero coverage — correct at this stage, since no product tests exist. Confirm branch coverage columns appear and `venv` is absent from the report.

**7 — The working tree is untouched**

```powershell
git status --porcelain
```

Only the new files from this phase should appear. If any `src/` file shows as modified, the tree guard failed to catch something — investigate before committing.

---

## 10. Acceptance criteria

Every item must be true before the commit.

**Structural**
- [ ] All directories and files from §2 exist; empty directories contain `.gitkeep`
- [ ] `pytest.ini`, `.coveragerc`, `.gitattributes`, `requirements-dev.txt` exist at the project root
- [ ] `.gitignore` includes `htmlcov/`, `.coverage`, `.pytest_cache/`
- [ ] `tests/helpers/__init__.py` exists; no other test directory has one

**Functional**
- [ ] `pytest` runs green with zero warnings in under 3 seconds
- [ ] All five markers are registered and `--strict-markers` rejects an unknown one
- [ ] Every meta-test in §8 exists and passes
- [ ] Disabling the socket plugin makes the network meta-tests fail (verification command 5)
- [ ] `--cov` produces a valid branch-coverage report scoped to `src`

**Safety**
- [ ] No test imports `src.core.scanner`, `src.core.fixer`, `src.core.detector`, `src.core.publisher`, or `src.main`
- [ ] No test reads the real `.env`
- [ ] No test writes outside `tmp_path`
- [ ] `git status` shows no modification to any pre-existing file except `.gitignore`
- [ ] `examples/payment.py` is byte-for-byte unchanged — confirm explicitly

**Documentation**
- [ ] `tests/conftest.py` opens with a docstring explaining that these fixtures are safety guarantees and must not be weakened without review
- [ ] `README.md` gains a short "Running tests" section with the three commands a contributor needs

---

## 11. Commit

Single commit, all files staged together. Suggested message:

```
Add Phase 0 testing harness: pytest config, safety fixtures, meta-tests

Establishes test infrastructure with structural guarantees that no test
can reach the network, read real credentials, or modify the working tree.

- pytest.ini with strict markers and global socket blocking
- .coveragerc with branch coverage scoped to src/
- .gitattributes marking tests/fixtures as binary (core.autocrlf=true
  would otherwise corrupt line-ending fixtures on checkout)
- conftest hierarchy with autouse credential scrubbing and .env blocking
- session-scoped project tree guard
- meta-tests proving each guarantee holds

No product tests yet; scanner/fixer/detector/publisher follow in Phase 1+.
```

CRLF warnings from git on commit are expected and harmless given `core.autocrlf=true`.

---

## 12. Out of scope — do not do these

- Any test of scanner, fixer, detector, publisher, or main
- Any fake or stub for GitHub, Anthropic, or Playwright
- Fixtures for synthetic repos, file content, or line endings
- GitHub Actions or any CI configuration (Phase 5)
- Refactoring any file under `src/`
- Fixing the known `*_fixed.py` scanner bug (Phase 1, deliberately as a failing test first)
- Adding a coverage threshold gate — the number would be near zero and would block the commit

If any of these seems necessary to complete Phase 0, stop and flag it rather than expanding scope.
