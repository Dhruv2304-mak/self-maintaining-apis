# Testing Architecture — self-maintaining-apis

**Audience:** Claude Code (implementation), reviewed by the project lead
**Scope:** Design only. No test code in this document.
**Status:** Proposed, ready for phased implementation.

---

## 1. Testing philosophy

Five principles, in priority order. When two conflict, the earlier one wins.

**1. Tests must never touch the outside world.** This tool's entire purpose is to open Pull Requests on real repositories and rewrite real source files. A careless test run must not be able to create a branch, open a PR, spend API credits, launch a browser, or modify a file outside a temporary directory. This is not a nice-to-have — it is the defining constraint of this particular test suite, and it should be enforced mechanically rather than by convention.

**2. Test behaviour at the module's public boundary.** Assert on what `scan()`, `fix()`, `save_fixed_code()` and `publish()` return and produce, not on private helpers. Private methods will be refactored; their tests would then have to be rewritten, which converts the suite from an asset into a tax.

**3. The suite must be deterministic and fast.** No network, no real clock dependence, no ordering dependence, no shared mutable state between tests. Target: the whole suite runs in under 10 seconds. A suite that takes a minute stops being run.

**4. Prioritise by blast radius, not by ease.** The code most worth pinning is the code where a silent regression causes real damage: the publisher writing to the wrong branch, the fixer corrupting line endings across a file, the scanner missing a match and leaving broken code in production. Trivial getters can stay untested indefinitely.

**5. Tests are documentation.** A new contributor should be able to read `tests/unit/test_scanner.py` and understand what the scanner guarantees. Test names are prose, not identifiers.

One explicit non-goal: this suite is not attempting to verify that the *fix content* is semantically correct Python. That is the model's job in live mode, and it is not deterministically testable. The suite verifies that the plumbing around the fix is correct.

---

## 2. Folder structure

```
tests/
├── conftest.py                  # global safety net + shared fixtures
├── unit/
│   ├── conftest.py              # unit-scoped fixtures
│   ├── test_scanner.py
│   ├── test_fixer_demo.py       # substitution logic, pure
│   ├── test_fixer_io.py         # save_fixed_code, line endings, encoding
│   ├── test_fixer_errors.py     # the four failure branches
│   ├── test_detector_parse.py   # HTML → changes, no fetching
│   └── test_publisher_logic.py  # branch naming, redaction, dry-run gating
├── integration/
│   ├── conftest.py
│   ├── test_pipeline.py         # main.py orchestration, all boundaries faked
│   ├── test_publisher_flow.py   # full publish sequence against a fake GitHub
│   └── test_cli.py              # argparse wiring for main.py and scanner.py
├── fixtures/
│   ├── repos/                   # small synthetic codebases to scan
│   ├── html/                    # saved docs pages for the detector
│   └── responses/               # canned API payloads
└── helpers/
    ├── fake_github.py           # in-memory PyGithub stand-in
    ├── fake_playwright.py       # in-memory browser stand-in
    └── builders.py              # constructors for test inputs
```

Three notes on this layout.

**`unit/` and `integration/` are separated so they can be run separately.** During development you run `unit/` on every save; `integration/` runs before commit and in CI. Enforce with pytest markers as well as directories, so selection works either way.

**`helpers/` is importable code, `fixtures/` is inert data.** Keeping fakes out of `conftest.py` prevents that file from growing into an unreadable 400-line dumping ground, which is the most common failure mode for pytest suites.

**`fixer` is split across three files.** It is the module with the most distinct responsibilities — substitution, file I/O, error handling — and a single `test_fixer.py` would become the largest and least navigable file in the suite.

---

## 3. Unit tests

Unit tests cover logic that is deterministic given its inputs and touches at most a temporary filesystem.

**`scanner.py` — the highest-value unit target in the project.**
- Keyword matched in plain code
- Match inside a comment is ignored when `skip_comments=True`
- Match inside a string literal is ignored
- Match inside a triple-quoted string is ignored
- **A line containing both real code and a trailing comment still reports the code** — this is the column-level masking behaviour, the scanner's most distinctive property, and the case a naive implementation gets wrong
- Match inside an f-string expression (a genuine ambiguity — decide the intended behaviour and pin it)
- `whole_word=True` rejects substring matches; `whole_word=False` accepts them
- Files in ignored directories are skipped
- `extra_ignored_dirs` is honoured
- A file with a syntax error falls back to plain line scanning rather than raising
- A non-UTF-8 file is handled without crashing
- An empty file, and a file with no matches, both return cleanly
- Multiple keywords, multiple matches per line
- Reported line numbers are 1-based and correct
- `*_fixed.py` files are excluded — currently a known bug; write this test first so it fails, then fix the code

**`fixer.py` demo mode — pure transformation.**
- `stripe.Charge.create` → `stripe.PaymentIntent.create`
- `source=` → `payment_method=`
- `confirm=True` is added
- All three transformations applied to one file in one pass
- Input with no target patterns returns unchanged content
- Already-migrated input is not double-transformed (idempotence)
- Occurrences inside strings and comments — decide and pin the intended behaviour, since blind substitution currently hits them

**`fixer.py` I/O.**
- **LF input produces LF output** — the single most important I/O test. On Windows, a naive write converts LF to CRLF and produces a diff touching every line of the file, which would make every generated PR unreviewable.
- CRLF input produces CRLF output
- Mixed line endings behave predictably
- Trailing newline presence is preserved
- UTF-8 content including non-ASCII survives a round trip
- Output path derivation is correct (`payment.py` → `payment_fixed.py`)
- `--in-place` overwrites the original; default mode does not

**`fixer.py` error branches.** All four documented failure paths return an `"ERROR: ..."` string rather than raising, and the returned message is informative. Verify explicitly that no exception escapes.

**`detector.py` parsing only.** Given saved HTML from `tests/fixtures/html/`, extract changes correctly. Covers: a page with real changelog entries, a page with only boilerplate (the current live behaviour), malformed HTML, empty HTML, and — once snapshot-diffing lands — old-vs-new snapshot pairs producing the correct delta.

**`publisher.py` logic in isolation.** Branch name format and UTC timestamping; `_redact()` removing tokens from arbitrary strings; dry-run engaging automatically when no token is present; repo-slug parsing and rejection of malformed slugs.

---

## 4. Integration tests

Integration here means *multiple internal modules composed together*, still with every external boundary faked. No test in this suite is ever integration-with-the-real-world.

**Pipeline orchestration (`main.py`)** — the primary integration surface:
- Detect → scan → fix → publish runs through in dry-run against a synthetic repo
- `--skip-detect` bypasses stage 1 and injects the known change
- **Three matches in one file produce one fix** — the de-duplication behaviour, which lives in `main.py` and cannot be tested at the unit level
- Matches across multiple files produce one fix per file
- Zero findings terminates cleanly without invoking the fixer or publisher
- A fixer error on one file does not abort the run for the remaining files
- `--open-pr` omitted means the publisher is never invoked
- Summary counts (examined / changed / skipped / failed) are arithmetically correct — these appear in the PR body, so wrong numbers are visible to reviewers
- Exit codes are correct for success, partial failure, and total failure

**Publisher flow against a fake GitHub:** default branch is read from the API rather than assumed; branch creation, blob-SHA lookup, and file update occur in the correct order; the create-file fallback triggers when the file does not exist on the branch; PR title and body are well-formed; an API failure at each stage is handled without a partially-created mess.

**CLI wiring:** every documented flag on `main.py` parses and reaches the right component; the standalone `scanner.py` CLI works; invalid arguments produce a helpful error rather than a traceback.

---

## 5. Mocking strategy

Mock at boundaries you do not own. Do not mock code you wrote — if a module is hard to test without mocking its internals, that is a design signal, not a mocking problem.

| Module | Approach |
|---|---|
| `scanner.py` | **No mocking.** Real files in `tmp_path`. It is filesystem logic; faking the filesystem would test nothing. |
| `fixer.py` demo | **No mocking.** Pure function. |
| `fixer.py` live | **Mock the Anthropic client.** Never a real call. Cover: normal response, malformed response, API error, timeout, rate limit. |
| `detector.py` | **Mock the fetch layer only.** Parsing runs on real saved HTML. Split fetch and parse into separate seams if they are currently entangled — this is a prerequisite for testing the module at all. |
| `publisher.py` | **Fake, not mock.** A hand-written in-memory GitHub stand-in in `helpers/fake_github.py` that records calls and returns realistic objects. Assertion-heavy `unittest.mock` chains against PyGithub's nested object model become unreadable and break on every refactor. |
| `main.py` | **Inject fakes for the four stages.** The orchestrator's job is sequencing and aggregation; test that, not the stages. |

A note on the fake-versus-mock choice for the publisher: a fake that maintains state lets you assert on *outcomes* ("a branch named `auto-api-fix/<timestamp>` exists and contains one commit touching one file") rather than on *call sequences* ("`create_git_ref` was called with these arguments"). Outcome assertions survive refactoring. Call-sequence assertions do not.

---

## 6. External dependencies that must never be contacted

Absolute prohibitions. Every one is enforced mechanically, not by reviewer vigilance.

1. **GitHub** — no HTTP to `api.github.com` or `github.com`. No branch creation, commit, PR, or repository read.
2. **The Anthropic API** — no calls, in any test, for any reason. Every call costs money and introduces non-determinism.
3. **Stripe's documentation site, or any documentation site** — the detector's targets are third-party servers that will change under us and rate-limit us.
4. **Any real browser process** — no Playwright launch, no Chromium subprocess.
5. **Any path outside `tmp_path`** — specifically not the project working tree, and never `examples/payment.py`, which is the project's only test input and must remain outdated.
6. **The real `.env` file and real environment credentials** — no test may read a genuine token, even to assert it is present.

**Enforcement.** Three layers in the root `conftest.py`, all autouse and session- or function-scoped as appropriate:

- **Socket blocking.** Adopt `pytest-socket` and disable network globally by default. Any test that opens a socket fails loudly with a clear message. This is the single highest-leverage line in the entire suite: it converts "we agreed not to call the network" into "the network is unreachable."
- **Environment scrubbing.** An autouse fixture that removes `GITHUB_TOKEN`, `ANTHROPIC_API_KEY` and related variables from the environment and prevents `.env` loading. Tests needing a token use an obviously fake value such as `ghp_TEST_NOT_A_REAL_TOKEN`.
- **Working-directory guard.** A session fixture that snapshots the project tree's mtimes and fails the run if any tracked file changed during testing. Cheap insurance against a path bug quietly overwriting a source file.

---

## 7. Naming conventions

**Files:** `test_<module>.py`, or `test_<module>_<concern>.py` when a module is split.

**Functions:** `test_<unit>_<condition>_<expected outcome>`. Read the name aloud; it should be a sentence describing a guarantee.

Good:
```
test_scanner_ignores_keyword_inside_comment
test_scanner_reports_code_when_line_has_code_and_comment
test_save_fixed_code_preserves_lf_line_endings_on_windows
test_publisher_uses_repo_default_branch_not_hardcoded_main
test_pipeline_deduplicates_three_matches_in_one_file_to_one_fix
test_fixer_returns_error_string_when_api_times_out
```

Avoid:
```
test_scanner_1
test_it_works
test_edge_case
```

**Classes:** group only when a set of tests genuinely shares setup — `TestScannerCommentMasking`. Do not group for the sake of it; pytest does not require classes.

**Markers:** `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.network_forbidden` (documentary — the socket block does the real work). Register all markers in `pytest.ini` so unknown-marker warnings stay meaningful.

**Parametrised cases** must carry explicit `ids`. `test_line_endings[lf]` is useful in a failure report; `test_line_endings[0]` is not.

---

## 8. Shared fixtures

**Root `conftest.py` — safety and universal scaffolding:**
- `block_network` (autouse, session) — the socket prohibition
- `clean_env` (autouse, function) — credential scrubbing
- `no_dotenv` (autouse, function) — prevents `.env` discovery
- `project_tree_guard` (session) — fails if tracked files are modified
- `frozen_clock` — fixed UTC time so branch names are deterministic and assertable
- `fixtures_dir` — path to `tests/fixtures/`

**Repository and file fixtures:**
- `synthetic_repo` — a small Python codebase in `tmp_path` with known match counts
- `outdated_payment_file` — a copy of the Stripe demo case, generated in `tmp_path`, **never the real `examples/payment.py`**
- `file_with_lf` / `file_with_crlf` / `file_with_mixed_endings` — line-ending inputs, written in binary mode
- `file_with_syntax_error` — exercises the tokenizer fallback
- `tricky_comments_file` — comments, strings, triple-quotes, f-strings, and the code-plus-comment line in one file

**Fakes and canned data:**
- `fake_github` — the in-memory GitHub, pre-seeded with a repo whose default branch is deliberately *not* `main`, so a hardcoded assumption fails the test
- `fake_anthropic_client` — configurable to return success, malformed output, or each error type
- `saved_docs_html` — parametrised over the HTML fixtures
- `fake_playwright` — returns canned page content without launching anything

**Configured components:**
- `scanner` / `fixer_demo` / `fixer_live` / `publisher_dry_run` — instances wired to fakes and temp paths, so individual tests contain assertions rather than setup

One critical detail on the line-ending fixtures: the repository has `core.autocrlf=true`. A fixture file committed with LF will be checked out with CRLF on Windows, silently destroying the very property the test asserts. **Line-ending fixtures must therefore be generated in binary mode at test runtime, not stored as files** — and the repository should additionally carry a `.gitattributes` rule marking `tests/fixtures/**` as binary. This is the subtlest trap in the whole plan and the one most likely to produce a confusing false pass.

---

## 9. Temporary file isolation

**`tmp_path` for everything, without exception.** Pytest's built-in fixture provides a unique directory per test, cleans up automatically, and retains the last few runs for post-mortem debugging.

Rules:
- Every fixture that creates files takes `tmp_path` and creates them inside it. No fixture uses a relative path, ever.
- No test writes to the current working directory. If a component defaults to CWD, the fixture that constructs it must override that default explicitly.
- Use `tmp_path_factory` for expensive session-scoped trees, but only for read-only data — a shared writable tree reintroduces inter-test coupling.
- `monkeypatch.chdir(tmp_path)` for any test exercising CWD-relative behaviour, so a bug cannot escape into the project directory.
- Assertions on file content in line-ending tests read in **binary mode**. Text mode normalises newlines on read and will make a broken implementation look correct.

The `project_tree_guard` fixture is the backstop for all of the above: if isolation fails anywhere, the run fails visibly rather than silently corrupting the working tree.

---

## 10. Testing GitHub publishing safely

Three layers, each independently sufficient to prevent a real API call — defence in depth, because this is the highest-consequence surface in the codebase.

**Layer 1 — Dry-run verification.** The publisher already enters dry-run when no token is present. Test that this gating is correct: no token means dry-run regardless of other flags; an explicit `--dry-run` forces it even when a token exists; and **dry-run performs zero network operations**, asserted by the socket block rather than by inspecting a mock.

**Layer 2 — The fake GitHub.** All non-dry-run publisher tests run against `helpers/fake_github.py`, which implements the small PyGithub surface actually used — `get_repo`, `default_branch`, `get_branch`, `create_git_ref`, `get_contents`, `update_file`, `create_file`, `create_pull` — as in-memory state. Tests then assert on resulting state: the branch exists, holds one commit, touches the expected path, and the PR has the expected base, head, title and body. The fake can also be configured to raise at any step, which is how the error-handling paths get covered.

**Layer 3 — Structural prohibitions.** The socket block makes real calls impossible. The environment scrub makes real tokens unavailable. Any test asserting on redaction uses a fake token string that is obviously non-functional.

**Explicitly out of scope:** no test hits GitHub even against a scratch repository. The convenience is not worth a suite that can create branches, and CI would need a real credential to run — which is exactly the failure mode this design exists to prevent.

**Token redaction deserves dedicated attention.** Test that `_redact()` handles the token appearing in an exception message, in a URL, in a log line, and multiple times in one string — and that a *partial* token prefix does not leak. Credential leakage into logs is a silent, high-severity failure, and it is cheap to pin.

---

## 11. Testing Playwright safely

**No test launches a browser.** Chromium startup costs seconds, needs a display or headless setup, behaves differently across environments, and hits the real network. All four properties are disqualifying.

The approach requires one prerequisite refactor: **`detector.py` must separate fetching from parsing.** Currently they are entangled, which makes the module effectively untestable. Split into a fetch layer (Playwright with `requests` fallback) and a parse layer (HTML string → list of changes). Once split:

- **Parsing is unit-tested directly** against saved HTML in `tests/fixtures/html/`, with no fake needed at all. This is where most detector value lives and it becomes trivially testable.
- **Fetch-layer logic is tested against `fake_playwright`**, a stand-in returning canned content. This covers the branching: Playwright succeeds; Playwright fails and `requests` takes over; both fail; and — the documented live behaviour — **the page never reaches network-idle and partial content is used anyway**. That last case is the detector's actual production path today and it is currently unverified.
- **Timeout handling is tested by making the fake raise the timeout exception**, not by waiting for a real timeout. No test should ever sleep.

Capture the HTML fixtures once, manually, from the real Stripe docs page, and commit them with a short note recording when they were captured. They are a snapshot of third-party output; treat them as data with a provenance date, not as ground truth.

When snapshot-diffing lands, the diff logic is pure and should be tested as a pure function: two HTML snapshots in, a list of changes out. That is the highest-value detector test set and it does not exist yet because the feature does not yet exist.

---

## 12. Coverage goals

Coverage is a diagnostic, not a target. Chasing a number produces tests that execute lines without asserting anything. Use it to find *unvisited* code, then judge whether that code matters.

| Module | Target | Rationale |
|---|---|---|
| `scanner.py` | 95% | Pure logic, no external boundary, cheap to cover completely |
| `fixer.py` | 90% | Demo mode and I/O fully covered; live-mode branches via the fake |
| `publisher.py` | 85% | Highest consequence; the uncovered remainder should be only defensive branches against PyGithub internals |
| `main.py` | 80% | Orchestration and argparse; some CLI surface is not worth exhaustive coverage |
| `detector.py` | 70% initially → 85% after the fetch/parse split | Honest reflection of a module that is mid-rework |
| **Overall** | **85%** | CI gate |

Set the CI gate at **80%** initially — comfortably below the 85% target, so the gate catches genuine regressions rather than blocking work on rounding. Ratchet it upward only when the suite is stable.

Two rules that matter more than the percentages:

- **Branch coverage, not line coverage.** Line coverage on a module full of `if/else` fallbacks — which describes most of this codebase — is misleadingly flattering.
- **Every error path in `publisher.py` and `fixer.py` must be covered, regardless of what the aggregate says.** These are the paths that run when something has already gone wrong, they are the least exercised in manual testing, and they are where the damage happens.

Exclude from measurement: `__main__` guards, the `helpers/` and `fixtures/` trees, and any pure-logging code.

---

## 13. What to write first, and why

Ordered by risk reduction per unit of effort.

**First: the safety harness** — `block_network`, `clean_env`, `no_dotenv`, `project_tree_guard`, plus `pytest.ini` and markers. Zero product tests, but until this exists, every subsequent test is a potential live API call or a potential overwrite of the working tree. Building it first also means the prohibitions are structural from day one rather than retrofitted after the first accident.

**Second: `save_fixed_code` line-ending preservation.** The narrowest test with the widest consequence. If this regresses on Windows, every generated PR shows a diff touching every line of the file, and the tool's core output becomes unreviewable — the product failure that most directly destroys its value. One test, five minutes, permanent protection.

**Third: scanner comment and string masking, including the code-plus-comment line.** This is the project's most distinctive piece of engineering and the behaviour most likely to be broken by a well-intentioned refactor toward "simpler" line-based scanning. Pin it before anyone is tempted.

**Fourth: findings de-duplication.** Three matches in one file must yield one fix. If this breaks, the tool produces duplicate or conflicting edits inside a single file — visible, embarrassing, and hard to diagnose after the fact.

**Fifth: publisher dry-run makes zero network calls.** Currently verified by hand, once. It is the safety property everything else depends on and it deserves a permanent regression guard rather than a memory of having checked.

**Sixth: the four fixer error branches.** Cheap to write, and they cover the paths that execute precisely when something has already gone wrong.

**Seventh: the scanner `*_fixed.py` exclusion** — written as a deliberately failing test against the known bug, then fixed. This establishes the red-green discipline on real defect, and closes an open issue in the process.

Only after these seven: the pipeline integration tests, then the detector work, which should follow rather than precede the fetch/parse refactor.

---

## 14. Estimated test count

| Area | Cases | Notes |
|---|---|---|
| Safety harness | 4–6 | Meta-tests proving the guards themselves work |
| `scanner.py` | 24–30 | Largest set; heavy parametrisation over comment and string forms |
| `fixer.py` demo | 10–12 | |
| `fixer.py` I/O | 12–15 | Line endings and encodings dominate |
| `fixer.py` errors | 8–10 | Four branches × failure modes |
| `detector.py` parse | 10–14 | Grows once snapshot-diffing lands |
| `detector.py` fetch | 8–10 | Against the Playwright fake |
| `publisher.py` unit | 12–15 | Branch naming, redaction, dry-run gating |
| `publisher.py` flow | 10–12 | Against the fake GitHub |
| Pipeline integration | 12–15 | |
| CLI | 8–10 | |
| **Total** | **≈ 120–150** | |

Roughly 75% unit, 25% integration. Expect around 100 of these to exist after Phase 3 and to cover most of the real risk; the remainder are completeness.

Treat these as a sizing estimate, not a quota. Parametrisation will inflate the raw count considerably — the scanner alone may report 40+ collected cases from a dozen written functions — and that is fine. Do not write tests to reach a number.

---

## 15. Phased implementation plan

Each phase ends in a committable, green state. Do not start a phase before the previous one passes.

**Phase 0 — Harness and safety (half a day).**
Add `pytest-socket`, `pytest-cov`, `pytest-mock`. Create `pytest.ini` with markers, test paths, and coverage config. Build the four autouse safety fixtures and the meta-tests proving they work. Add `.gitattributes` marking `tests/fixtures/**` as binary. Establish the directory skeleton.
*Exit criteria:* `pytest` runs, collects the meta-tests, and a deliberate network call inside a test fails the run.

**Phase 1 — Pure logic (one to two days).**
Scanner in full. Fixer demo mode and I/O, starting with line endings. This is where the bulk of the suite lands and where it is cheapest to write, because nothing needs faking.
*Exit criteria:* scanner ≥ 90%, fixer demo + I/O ≥ 85%, suite under 5 seconds.

**Phase 2 — Fakes and error paths (one to two days).**
Build `fake_github.py` and `fake_anthropic_client`. Cover the fixer's four error branches, publisher unit logic, redaction, and the dry-run zero-network guarantee.
*Exit criteria:* publisher ≥ 80%, every documented error branch covered, still no network.

**Phase 3 — Integration (one day).**
Pipeline orchestration with all boundaries faked, including de-duplication, summary-count arithmetic, partial-failure handling, and exit codes. Publisher flow against the fake. CLI wiring.
*Exit criteria:* overall ≥ 80%, the whole pipeline exercised without a single external call.

**Phase 4 — Detector, after the fetch/parse refactor (one to two days).**
Split fetch from parse — a source change, not a test change, and the reason this phase comes last. Then capture HTML fixtures, unit-test parsing, and test fetch branching against the Playwright fake, including the never-goes-idle path.
*Exit criteria:* detector ≥ 70%, no browser process launched anywhere in the suite.

**Phase 5 — CI and ratchet (half a day).**
GitHub Actions running the suite on push and PR, with the coverage gate at 80% and network access disabled at the workflow level as a further layer. Add a `make test` / task-runner entry point. Document in the README how to run unit-only versus the full suite.
*Exit criteria:* CI green, gate enforced, a coverage report published on each run.

**Total: roughly five to seven working days**, and the suite delivers most of its protective value by the end of Phase 2.

**Sequencing note for whoever implements this:** Phase 4 depends on a source refactor, so it is the one phase that can slip without blocking the others. If time is short, Phases 0–3 constitute a defensible production-quality suite on their own, and the detector — the module currently under active redesign — can be covered once its shape has settled. Writing detailed tests against code you are about to rewrite is the one form of test-writing that reliably wastes effort.
