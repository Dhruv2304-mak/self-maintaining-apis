# 0001. Verification emits evidence, not verdicts

- **Status:** Accepted
- **Date:** 2026-08-02
- **Context:** Pre-implementation architecture review, taken before the Verification Loop was built

## Context

The system detects a breaking change in a vendor API, locates affected code in a target repository, generates a fix, and opens a pull request. Nothing in that chain establishes whether the fix is correct.

The Verification Loop was proposed to close that gap. Design review of that proposal, conducted before implementation, found four errors in it and several structural decisions that needed to be taken at the same time. This record captures the resulting architecture. It is written before the code exists, so it describes intent rather than current behaviour.

## Decisions

### 1. Verification emits evidence; policy produces verdicts

The Verification Engine returns a structured body of observations about a proposed patch. It does not return pass/fail, safe/unsafe, or any other judgement.

A separate Trust & Policy engine converts evidence plus configuration into a decision.

The original design had verification act as a publication gate that blocked the PR on failure. Two problems: a binary gate destroys information, and the system then optimises for passing the gate rather than for being correct. More fundamentally, the verdict is a policy decision rather than an engineering one. One user wants a full green suite plus two human approvals; another wants anything that compiles to auto-merge. With the verdict baked into the verification engine, serving both requires forking the engine.

This is the decision from which the rest of the architecture follows.

### 2. Verification is an extractable service, not just a separate module

The Verification Engine's entire interface is: **in**, a repository at a known commit plus a proposed patch; **out**, structured evidence about that patch.

It knows nothing about vendors, documentation, LLMs, pull requests, or users. If the name of any specific vendor, model provider, or forge appears anywhere inside it, the boundary has been violated.

Recommended layout:

```
src/engines/verification/
    contracts.py      the interface, and nothing else
    orchestrator.py   signal composition and sequencing
    sandbox/          isolation, provisioning, resource limits
    signals/          one module per independent signal
    evidence.py       report construction
```

Four reasons the boundary is drawn this hard:

- **Security requires a process boundary regardless.** This component executes untrusted third-party code — user repositories and their test suites, some of which will eventually be adversarial. Designing it now as an in-process module behind a narrow interface makes the later extraction to a separate service a deployment change rather than a rewrite.
- **It is independently testable.** Verification correctness can be measured against a fixture corpus with none of the rest of the platform present. No other component has this property.
- **It is independently useful.** Grading a patch against a repository stands on its own, separate from autonomous change delivery. Embedding it inside `publisher.py` forecloses that permanently.
- **It is the component most likely to be rebuilt,** as we learn what actually predicts a merged PR. A component expected to be replaced should have the cleanest seam.

**Enforcement:** `verification/` may not import from `detector/`, `publisher/`, or any vendor-specific module. This is enforced by an automated test, in the same way network isolation is currently enforced in the test harness.

### 3. Symbol verification is the primary signal; test execution is corroborating

The primary check is that every symbol a patch references exists in the target SDK version, with a compatible signature.

The original design treated running the repository's own test suite as the primary signal. That is wrong in a way specific to this product. If a vendor replaces `Charge.create` with `PaymentIntent.create` and we rewrite the call, the repository's tests mock the vendor SDK and pass — and they would pass for almost any rewrite preserving the call shape, including a hallucinated method that does not exist. Test suites verify that we did not break the application. They do not verify that we performed the migration correctly. Those are different claims.

Symbol verification directly catches API hallucination, the most common failure mode of LLM-generated code, at a fraction of the cost of a full test run.

### 4. Static verification is the floor; dynamic verification is an enhancement

Static verification applies universally. Dynamic verification raises confidence where the environment permits. Signals compose additively rather than degrading down a ladder.

This inverts the original hierarchy, which designed dynamic-first with static as a fallback. Reproducing an arbitrary repository's build environment — interpreter, dependency versions, private registries, required services, secrets — is the hardest practical problem in the system, and a substantial fraction of real repositories will never be reliably buildable by us. Dynamic-first means designing for the minority case and degrading into the majority case.

### 5. Migration Synthesis emits patches and never touches the filesystem

Output is a structured `Patch`, not a rewritten file and not a file written to disk.

Whole-file replacement fails on four independent grounds:

1. **Blast radius.** A model error anywhere in the file ships alongside the intended change. A three-line migration should not be able to reformat two hundred lines.
2. **Reviewability.** Reviewers approve diffs. A whole-file rewrite forces the reviewer to diff it themselves, which is the cost this system exists to remove.
3. **Composability.** Two migrations touching the same file cannot be combined if each claims ownership of the whole file.
4. **Diff size is itself a signal.** A large diff for a small semantic change is evidence of a bad generation. Whole-file output destroys that signal by making every diff large. Patch minimality is free verification: expecting three lines and receiving a hundred is grounds for rejection before any test runs.

A `Patch` is stored structured and serialised to unified diff. It carries the target path, an ordered set of hunks, and **the content hash of the base file each hunk was computed against**. Without base hashes a patch is meaningless, because the repository may have moved since the scan. Patches must be multi-file (one API change affects many call sites) and reversible — rollback needs it, and apply-then-revert returning the original bytes is a useful self-test.

**Two invariants to enforce in code:**

- The synthesis engine never touches the filesystem. The prototype's `save_fixed_code` — a generator that writes files — is a design error inherited from the prototype and is to be **removed rather than ported forward**.
- Only two components apply patches: the verification sandbox and the delivery engine. Everything else passes them around as data.

**Drift:** between scan and delivery the repository may change, and base hashes make that detectable. On drift, re-derive rather than force-apply — regenerate against the new base and re-verify. Force-applying a patch to a changed file is how autonomous systems destroy user code, and it must be structurally impossible rather than merely discouraged.

### 6. A Migration is an immutable proposal

A `Migration` represents "at this moment, given this evidence, this is the change we propose." It never changes after creation.

Everything mutable lives in separate records referencing the migration ID:

```
Migration            (immutable)
   ├── VerificationReport   many, one per verification run
   ├── TrustAssessment      many, one per evaluation
   ├── DeliveryRecord       zero or one PR
   └── Outcome              merged / modified / reverted / closed
```

Three reasons: an audit trail requires knowing what was believed *at the time*; confidence recalibration requires re-scoring historical migrations without corrupting the original record; and a migration verified twice under different conditions has two reports, not one overwritten field.

Consequences for the object's shape:

- `confidence` and `verification report` do **not** live on the Migration.
- `affected files` is removed — derivable from the patch, and duplicated state drifts.
- `source API` / `target API` are referenced by ChangeEvent ID rather than copied.
- Timestamps are creation-only. A mutable `updated_at` implies mutation.
- Added: base commit and per-file content hashes; model identity and prompt version; the IDs of the ChangeEvent and Finding that produced it; and the migration **class** (a categorical label such as `method_rename` or `parameter_removal`) which is what makes historical priors computable.

`reasoning` — the natural-language explanation of why the change is correct — stays, with elevated status. It is what a human reviewer actually reads. It is a first-class deliverable with its own quality bar, not a debug string.

### 7. Type the boundaries, not the internals

Objects crossing engine boundaries are typed. Intermediate values inside an engine are not.

The benefit is not primarily type safety. It is that **the boundaries become the platform's internal API**, which is what makes swapping any adapter possible at all — you cannot swap one forge for another if the interface is an untyped dictionary whose shape is whatever the first implementation happened to produce. Secondarily, typed boundaries make the pipeline introspectable, and a system operating unattended must be able to explain its own state. Dictionaries do not describe themselves.

Over-modelling is a real failure mode that produces ceremony without safety. The rule is boundaries only.

**Cost:** roughly two days now — five modules, 195 tests, one developer holding full context. It rises superlinearly, and after the next two milestones it touches persisted data. This is the cheapest it will ever be, which is why it is sequenced first.

### 8. The pipeline is not linear

The stage objects are right; the arrows are wrong. Three specific corrections:

- **Detection is continuous and event-driven,** not a pipeline stage. It emits ChangeEvents into a queue.
- **Verification failure feeds back into synthesis** for a bounded number of refinement attempts. A failed patch plus the reason it failed is a far better prompt than the original. This loop is likely worth more to output quality than prompt engineering, and a linear model cannot express it.
- **Delivery is conditional,** gated by policy, and may never occur.

## Resulting architecture

Six engines:

```
1. CHANGE INTELLIGENCE      sources → ChangeEvent
                            fetch, normalise, snapshot, diff, classify

2. IMPACT ANALYSIS          ChangeEvent + Repository → Finding[]
                            (the current scanner, renamed for what it does)

3. MIGRATION SYNTHESIS      Finding + ChangeEvent → Migration
                            LLM-driven; produces patches, never files

4. VERIFICATION             Migration + Repository → VerificationReport
                            sandboxed; emits evidence, never verdicts

5. TRUST & POLICY           VerificationReport + History → TrustAssessment + Decision
                            calibrated confidence; enforces the non-negotiable floor

6. DELIVERY                 Decision + Migration → DeliveryRecord
                            forge-agnostic; captures outcomes
```

Shared models:

```
ChangeEvent          what the vendor changed, classified, with provenance
Finding              where it affects a specific repository
Patch                structured diff, base-hash anchored, reversible
Migration            immutable proposal: patch + reasoning + provenance
VerificationReport   evidence from one verification run
TrustAssessment      calibrated confidence at a point in time
DeliveryRecord       the PR we opened
Outcome              what the human actually did
```

All language-agnostic and forge-agnostic. **This constraint is the load-bearing one.**

Execution flow:

```
  vendor sources
        │  (continuous, event-driven)
        ▼
  CHANGE INTELLIGENCE ──► ChangeEvent ──► queue
                                            │
                                            ▼
                                    IMPACT ANALYSIS
                                            │
                                            ▼
                          ┌───────► MIGRATION SYNTHESIS
                          │                 │
              refine loop │                 ▼
              (bounded)   │          VERIFICATION
                          │                 │
                          └───── fail ──────┤
                                            ▼
                                    TRUST & POLICY
                                            │
                                  ┌─────────┴─────────┐
                                  ▼                   ▼
                              DELIVERY            suppress
                                  │              (logged, surfaced)
                                  ▼
                               Outcome ──────► calibration
```

The two features a linear pipeline cannot express — the bounded refinement loop, and outcome feedback into calibration — are essential rather than decorative.

**Persistence:** content-addressed blob storage for vendor snapshots; relational storage for events, migrations, reports, deliveries, and outcomes. Outcomes instrumented from day one.

**Trust layer:** cross-cutting rather than a pipeline stage. Reads from every engine, owns calibration, enforces the floor, and owns the user-facing explanation of uncertainty.

**Adapter seams:** five — source, language, build, model, forge — each defined now with exactly one implementation.

## Consequences

- `save_fixed_code` and all filesystem writes leave Migration Synthesis. Any work depending on that method, including planned tests of its write-error paths, is obsolete.
- Verification and Trust & Policy are separate engines with a typed contract between them. The evidence schema is a published contract, not an internal detail.
- Every decision is reconstructible from stored evidence, because evidence persists independently of any verdict derived from it.
- Verification cannot be defeated by a repository whose test suite mocks the vendor SDK.
- Repositories with no runnable test suite remain verifiable at the static floor.
- An import-restriction test is required, alongside the existing network-isolation enforcement.
- The typed-boundary refactor is sequenced before further feature work, on cost grounds.

## Sequence

1. Cut the typed model boundaries (decisions 6, 7)
2. Convert synthesis to patch output and remove filesystem writes (decision 5) — unblocks everything downstream
3. Build the benchmark corpus: 10–15 real historical migrations with known-good and known-bad fixes, owned as a standing asset rather than a sprint deliverable
4. Verification v1 — symbol verification and static analysis first, sandboxed test execution second
5. Instrument outcome capture before the first external PR, not after

## Notes

Calibration rules, the signal set, and how uncertainty is presented are Trust & Policy concerns and belong in a separate record. Two constraints from that work bear on this one and are stated here for completeness: confidence is never self-reported by a model, and signals are floored by the weakest critical signal rather than averaged.
