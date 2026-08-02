# Slice Lifecycle

The standing process for all architectural work on BridgeAI. It governs how a change moves
from decision to committed code.

## Roles

| Role | Owner | Responsibility |
|---|---|---|
| CTO / Product Architect | human | Challenges assumptions, prioritises, reviews direction |
| Principal Architect | planning model | Owns all architectural decisions; writes specifications; reviews and accepts work |
| Implementation Engineer | coding agent | Executes one specification exactly; makes no architectural decisions |

**The load-bearing rule:** the implementation engineer never decides architecture, never
chooses a testing strategy, and never expands scope. If a specification is ambiguous, the
correct action is to stop and report the ambiguity as a blocker — never to resolve it.

## The eight steps

### 1. Repository Discovery

Run when repository state may have changed since the last slice: after any implementation,
after any manual edit, after any gap in the session, or whenever a specification would
otherwise rest on remembered facts.

Discovery is **read-only**. No file is created or modified, no branch is cut, nothing is
staged. Commands are echoed and their output pasted verbatim.

Discovery reports **observations, never verdicts**. Whether a fact constitutes
architectural drift is a judgement reserved to the architect. This mirrors ADR-0001: the
component that gathers evidence is not the component that decides what it means.

**Exit condition:** a Repository State Report whose facts the architect has read.

### 2. Architecture Decision Review

The architect checks the report against the governing ADRs. Three outcomes:

- No conflict — proceed.
- Conflict, and the code is wrong — the slice includes the correction.
- Conflict, and the **ADR** is wrong — stop. Amend or supersede the ADR before any
  implementation. An ADR is never silently worked around.

### 3. Slice Specification

One slice solves one architectural problem. It must be independently reviewable, fully
reversible, and leave the repository runnable.

Every specification contains, without exception:

- **Objective** — what is being built, in one paragraph
- **Scope** — every file that may be created or modified, and an explicit do-not-touch list
- **Implementation requirements** — constraints, invariants, edge cases, governing ADRs
- **Testing requirements** — decided by the architect, never by the implementer
- **Acceptance criteria** — measurable, each independently checkable
- **Expected repository state** — exact file count, verified by `git diff --stat`
- **Git checkpoint** — branch name, commit message, push policy
- **Rollback** — the exact commands that undo the slice
- **Deliverables** — what the implementer reports back

Prohibited in any specification: placeholder packages, empty abstractions, speculative
architecture, and any directory created before something goes in it.

**Never write more than one specification ahead.** The next slice is shaped by what the
current one reveals.

### 4. Implementation

The implementer executes the specification and stops. Work outside scope is a violation
regardless of whether the code is correct.

Reported back: summary, files changed with line counts, tests added, before-and-after test
results, architectural observations, assumptions made, blockers.

**Architectural observations are the most valuable deliverable.** They are how the
specification's blind spots surface, and they shape the next slice.

### 5. Review

Principal-engineer review of the transcript against: correctness, ADR compliance, scope
adherence, test quality, unnecessary complexity, edge cases, and technical debt introduced.

Scope adherence is checked first. A slice that exceeded scope is reviewed for that before
its code is read.

### 6. Accept, Amend, or Reject

- **Accept** — all criteria met, no violations. Proceed to checkpoint.
- **Amend** — sound direction, specific defects. A correction specification is issued
  against the same branch. Amendments are numbered (A, B, C) and appended, never folded
  silently into the original.
- **Reject** — architectural violation, or the specification was wrong. The branch is
  deleted. If the specification was at fault, it is rewritten before any retry.

Rejection must stay cheap. That is what the branch is for.

### 7. Git Checkpoint

Every slice runs on `arch/NN-short-name`, branched from a clean `main`.

The `arch/*` namespace is reserved and must not collide with branches the tool generates
for its own pull requests.

One commit per slice. The commit is a claim that the slice is complete, so it is made only
after every acceptance criterion passes. The commit message references the governing ADR.

No push, no pull request, and no merge to `main` until the slice is accepted.

### 8. Next Slice Selection

Chosen only after the current slice is accepted, and informed by its architectural
observations.

Selection favours: the decision that is cheapest to make now and most expensive later; the
work that unblocks the most downstream slices; and the change whose correctness can be
verified without external dependencies.

## Invariants

These hold across every slice.

1. `main` is always runnable. A slice that leaves it broken is rejected.
2. Every slice is reversible by deleting a branch.
3. Tests never contact the network, never launch a browser, and never write outside
   `tmp_path`.
4. No slice edits the test harness to make its own work pass. A harness change is its own
   slice with its own justification.
5. Existing tests are never modified to accommodate new code. If an existing test must
   change, that is an architectural signal requiring a decision, not an edit.
6. Internal commercial and strategic documents stay outside the repository.
