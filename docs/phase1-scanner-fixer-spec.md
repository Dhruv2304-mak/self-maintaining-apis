# Phase 1 — Scanner and Fixer Pure Logic

Implementation spec for Claude Code. Save to `docs/phase1-scanner-fixer-spec.md`
and commit it with the Phase 1 work.

Prerequisite: Phase 0 is committed (`ef13aa9`). The harness, safety fixtures and
27 meta-tests are green.

---

## 1. Scope

**In scope**

- All pure-logic tests for `src/core/scanner.py` and `src/core/fixer.py`.
- Exactly one change to product code: adding the `*_fixed.py` filter to the
  scanner, written red-green (§3).
- Test fixtures under `tests/unit/` and `tests/fixtures/`.

**Out of scope — do not touch**

- `detector.py`, `publisher.py`, `main.py` — Phases 2, 3 and 4.
- Any fake GitHub, fake HTTP, or fake filesystem. Phase 2.
- Error paths: missing files, permission errors, malformed encodings,
  tokenize failures on invalid Python. Phase 2.
- Integration between modules. Phase 3.
- CI configuration. Phase 5.
- Any refactor of scanner or fixer beyond the single filter change in §3.

**Target:** 45–60 tests, all marked `@pytest.mark.unit`, all under
`tests/unit/`. Expect the suite to go from 27 to roughly 72–87 tests.

---

## 2. Read the source first

This spec was written from architecture notes, **not** from reading the source.
Function names, signatures and return shapes in the sections below are
descriptive, not authoritative.

Before writing any test:

1. Read `src/core/scanner.py` and `src/core/fixer.py` in full.
2. Report the public API surface: every public function, its parameters, and
   the exact shape of what it returns. If findings are tuples, say what is in
   each position. If they are dicts or dataclasses, list the fields.
3. Report the line/column convention actually used — `tokenize` yields 1-based
   rows and 0-based columns, but the scanner may re-base either.
4. Report whether the scanner's public entry point takes a directory, a file,
   or both, and how keywords are passed.

**Then adapt this spec to the real API.** Where the spec and the code disagree,
the code wins. Do not reshape `src/` to match the spec. See §10.

---

## 3. The red test — scanner counts its own output

This is the deferred bug from the previous session. Write it first, confirm it
fails, then fix it.

**Behaviour today:** if `examples/payment_fixed.py` exists on disk, the scanner
reports its matches as new findings — 6 instead of 3. The fixer already skips
`*_fixed.py`, so no bad output is produced, but every count is inflated.

### 3.1 Write the failing test

In `tests/unit/test_scanner_fixed_file_filter.py`:

- Build a temp directory containing two files: `payment.py` with exactly three
  keyword occurrences, and `payment_fixed.py` with the same three.
- Assert the scan returns exactly three findings.
- Assert every finding's path ends in `payment.py` and none ends in
  `payment_fixed.py`.

Assert both the count **and** the paths. A count-only assertion can pass for the
wrong reason if the scan silently misses a file.

### 3.2 Confirm it fails for the right reason

Run it and paste the output. Expected: an assertion failure showing 6 where 3
was expected. If it fails any other way — collection error, zero findings,
exception — stop and report. Do not proceed to the fix.

### 3.3 Fix it

The bug exists because the skip predicate lives only in the fixer. Duplicating
it into the scanner recreates the same drift risk.

Extract it into a single shared predicate — a small module-level function in a
location both modules already import from, or a new `src/core/paths.py` if
there is no natural home. Have **both** scanner and fixer call it.

Constraints:

- Match the fixer's existing semantics **exactly**. Read the fixer's current
  check and preserve its behaviour on suffix, case and extension. If the fixer
  matches `_fixed.py` as a suffix, the shared predicate does the same; do not
  "improve" it to a glob or a regex.
- Change nothing else in either module. No renames, no reordering, no type
  hints, no docstring edits beyond one line describing the predicate.
- If extracting requires a new import cycle, stop and report instead.

### 3.4 Confirm green, and test the predicate directly

Re-run. Then add direct tests for the shared predicate: `payment.py` false,
`payment_fixed.py` true, `payment_fixed.txt`, `fixed.py`, `_fixed.py`,
`my_fixed_file.py`, and a path with directories in it. Pin actual behaviour on
the ambiguous ones — see §9.

---

## 4. Scanner tests

The scanner's distinguishing feature is tokenize-based **column-level** comment
and string masking. Most of the value here is in proving the masking is
column-accurate rather than line-accurate.

### 4.1 Core matching

- Keyword in ordinary code is found.
- Correct line number, correct column, correct matched text.
- Two occurrences on one line yield two findings with distinct columns.
- Multiple keywords in one scan; each finding attributed to the right keyword.
- Zero findings for a file with no matches.
- Empty file, whitespace-only file, comment-only file: zero findings, no error.

### 4.2 Masking — the important group

- Keyword in a `#` comment is not found.
- Keyword in a single-quoted and in a double-quoted string is not found.
- Keyword in a triple-quoted docstring is not found, including when the keyword
  is on an interior line of a multi-line docstring.
- Keyword in a raw string `r"..."` and a byte string `b"..."` is not found.
- Keyword inside escaped quotes within a string is not found.

**The column-level test.** A line containing a real call followed by a trailing
comment that repeats it:

```python
stripe.Charge.create(amount=100)  # old stripe.Charge.create call
```

Assert exactly one finding, at the column of the code occurrence. A line-level
masker fails this either by reporting two or by masking the whole line and
reporting none. This is the single most valuable scanner test in Phase 1.

Add the mirror case: a comment-only line whose comment contains the keyword,
directly above a real call, to confirm the mask does not leak across lines.

### 4.3 Directory traversal

- Nested subdirectories are scanned recursively.
- Findings from multiple files are all returned, each with its own path.
- Whether non-`.py` files are scanned: **characterize** (§9).
- Whether hidden directories, `__pycache__`, `venv/` are skipped:
  **characterize**. If `venv/` is not skipped, flag it prominently — scanning it
  would be slow and would produce nonsense findings.

### 4.4 Line endings

Generate a source file with CRLF line endings at runtime in binary mode (§6),
scan it, and assert line and column numbers match the LF equivalent. Windows
plus `core.autocrlf=true` makes this a live risk, not a theoretical one.

### 4.5 f-strings — characterize, do not guess

On Python 3.12+, f-strings tokenize into `FSTRING_START` / `FSTRING_MIDDLE` /
`FSTRING_END`, and the expression parts inside braces are **real tokens**. So:

```python
result = f"charge: {stripe.Charge.create(amount=100)}"
result = f"deprecated: stripe.Charge.create"
```

The first contains genuine code inside a string. The second contains only
literal text. These arguably deserve opposite answers.

Run both, report what the scanner actually does, and write tests pinning that
behaviour. Do **not** change the scanner to produce what you think is correct —
flag it in your summary and I will decide.

### 4.6 Substring semantics — characterize

Does `stripe.Charge.create` match inside `stripe.Charge.created` or
`my_stripe.Charge.create`? Report actual behaviour and pin it. Flag it if the
matching has no word-boundary handling, since that has real false-positive
consequences for the pipeline.

---

## 5. Fixer tests

### 5.1 Substitution

- `stripe.Charge.create(...)` becomes `stripe.PaymentIntent.create(...)`.
- Surrounding code is untouched.
- Multiple occurrences in one file are all substituted.
- Input with no occurrences comes back unchanged.
- Already-substituted input is unchanged when run again (idempotence).

### 5.2 Pin the prose mangling — deliberately

The README documents that demo mode rewrites

> still uses the old Charges API, which was removed

into a self-contradicting sentence, because the substitution is blind. **This is
documented intended behaviour, not a bug.**

Write a characterization test that asserts the known-bad output, with a comment
stating it is deliberate and pointing at the README section. If someone later
makes the fixer smarter without updating this test, the failure tells them they
changed a documented property rather than fixing a defect.

Do not fix the mangling. Do not soften the assertion.

### 5.3 `save_fixed_code` line-ending preservation — the critical group

`save_fixed_code` uses `newline=""` specifically so Python performs no line-end
translation in either direction. Every assertion here reads back in **binary**.

- Content with `\n` only: file on disk contains no `\r` byte at all.
- Content with `\r\n`: preserved as `\r\n`, not expanded to `\r\r\n`.
- Mixed `\n` and `\r\n` in one string: byte-for-byte identical on disk.
- No trailing newline: no newline added.
- Empty content: empty file.

Assert with `assert data == expected_bytes` on bytes read via
`open(path, "rb")`. A text-mode round-trip on Windows normalizes silently and
the test passes while proving nothing.

**Prove the test is not vacuous.** Add one test that writes the same content in
text mode to a scratch path and asserts the bytes *are* corrupted — `\r\n`
present where the input had `\n`. If that test ever passes trivially, the
platform assumption behind the whole group has changed. Mark it
`@pytest.mark.unit` and name it so its purpose is obvious.

### 5.4 Output path derivation

- `payment.py` maps to `payment_fixed.py` in the expected directory.
- A path already ending `_fixed.py` is skipped, using the shared predicate
  from §3.3 — assert the skip, and assert no `payment_fixed_fixed.py` is
  produced.
- Nested paths keep their directory.

### 5.5 Return contract

The fixer returns `"ERROR: ..."` strings and never raises. For pure-logic inputs
only, assert the return type is what the code documents. Do not manufacture I/O
failures — that is Phase 2.

---

## 6. Fixture policy

**Line-ending fixtures are generated at runtime, in binary mode, always.**

```python
path = tmp_path / "crlf_source.py"
path.write_bytes(b"import stripe\r\nstripe.Charge.create(amount=100)\r\n")
```

Never commit a file whose line endings the test depends on. `.gitattributes`
marks `tests/fixtures/**` as `binary`, which protects committed fixtures, but
runtime generation removes git from the question entirely and is preferred for
anything line-ending sensitive.

Rules:

- No `open(..., "w")` when the test asserts on bytes. Use `write_bytes` or
  `open(..., "wb")`.
- No `\n` in a string literal that is written in text mode and later compared
  byte-for-byte.
- Use the `tmp_path` fixture. Never write into the project tree — the tree
  guard will fail the run, correctly.
- Committed fixtures under `tests/fixtures/` are fine for content that is not
  line-ending sensitive (sample source files, keyword lists). Prefer inline
  string constants for anything under about 20 lines; a fixture file that has
  to be opened to understand the test is worse than a literal.

---

## 7. Markers and layout

```
tests/unit/test_scanner_matching.py
tests/unit/test_scanner_masking.py
tests/unit/test_scanner_traversal.py
tests/unit/test_scanner_fixed_file_filter.py
tests/unit/test_fixer_substitution.py
tests/unit/test_fixer_line_endings.py
tests/unit/test_fixer_paths.py
```

Adjust if the real API suggests a better split. Every test gets
`@pytest.mark.unit`, applied via `pytestmark = pytest.mark.unit` at module level
rather than per-function.

`tests/unit/conftest.py` already exists from Phase 0. Put shared source-string
constants there only if used by three or more modules.

`xfail_strict = true` is active. If you mark anything `xfail`, it must actually
fail, and it must be removed the moment it passes.

---

## 8. Verification commands

Run all of these and paste the output.

1. **Red test before the fix** — §3.2. Expected: assertion failure, 6 vs 3.
2. **Full suite after the fix**
   `.\venv\Scripts\python.exe -m pytest; Write-Output "exit: $LASTEXITCODE"`
   Expected: all green, zero warnings, exit 0.
3. **Coverage on the two target modules**
   `.\venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing`
   Report the `scanner.py` and `fixer.py` rows. Overall TOTAL will be around
   30–35% because three modules are still untested — that is expected, not a
   regression.
4. **Marker selection**
   `-m unit` selects only the new tests; `-m meta` still selects 27.
5. **Line-ending test is not vacuous** — §5.3's text-mode corruption test
   passes, proving the binary assertions have teeth.
6. **Tree guard clean under coverage**
   `.\venv\Scripts\python.exe -m pytest --cov -q; Write-Output "exit: $LASTEXITCODE"`
   Expected: exit 0.
7. **Demo file untouched**
   `git hash-object examples/payment.py`
   Expected: `ea25e24e68a1d1815e4780a3ea6900e60c02d3cd`.
8. **Product diff is minimal**
   `git diff --stat -- src/`
   Expected: only the §3.3 filter change. Paste the full `git diff -- src/`.

---

## 9. Characterization policy

Several sections say **characterize** rather than asserting an answer: f-string
handling, substring boundaries, non-`.py` files, directory skipping, and the
ambiguous `_fixed` predicate cases.

For each:

1. Run the code and observe what it does.
2. Write a test pinning that actual behaviour.
3. Add a comment marking it a characterization test, not a specification.
4. List every one of them in your summary, with the behaviour you found.

Do not change `src/` to make a characterization come out differently. If you
believe the behaviour is wrong, say so in the summary and leave the code alone.

---

## 10. Deviation reporting

If this spec is wrong about the code — a different signature, a different return
shape, a test that cannot be written as described — then:

- Adapt the test to the real code.
- Report the deviation explicitly, with the spec's assumption and the reality.
- Never edit `src/` to make the spec true.

The Phase 0 session found two genuine spec errors this way. Finding more is a
good outcome, not a failure.

---

## 11. Acceptance criteria

- The §3 red test was confirmed failing before the fix, with output shown.
- Full suite green, zero warnings, exit 0.
- `scanner.py` and `fixer.py` both at 85% branch coverage or above.
- Every new test marked `unit`; `-m meta` still selects exactly 27.
- No test contacts the network, launches a browser, reads `.env`, or writes
  into the project tree.
- All line-ending assertions read bytes in binary mode.
- `examples/payment.py` hashes to `ea25e24e…`.
- `git diff -- src/` shows only the shared `_fixed` predicate change.
- Every characterization is listed in the summary.

---

## 12. Commit message

Two commits.

```
Phase 1: scanner and fixer unit tests

Adds NN unit tests covering keyword matching, column-level comment and
string masking, directory traversal, demo-mode substitution and
line-ending preservation.
```

```
fix: scanner no longer counts its own *_fixed.py output

The skip predicate lived only in the fixer, so scans that ran after a fix
double-counted. Extracted to a single shared predicate used by both.
Regression test added first, confirmed failing.
```

Order them fix-first if the tests would otherwise be red at that commit.

**Do not commit until I have reviewed the output.**

---

## 13. Hard boundaries

Do not, under any circumstances:

- Modify `detector.py`, `publisher.py` or `main.py`.
- Modify `scanner.py` or `fixer.py` beyond the §3.3 predicate change.
- Modify `examples/payment.py`.
- Weaken `filterwarnings = error`, `--strict-markers`, `--disable-socket`,
  `xfail_strict`, or the tree guard.
- Add network access, real API calls, or browser launches to any test.
- Write into the project tree from a test.
- "Fix" the fixer's documented prose mangling.
