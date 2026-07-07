# The devloop engine pipeline (9-step walkthrough)

The code-owned engine: `loop.run_v1` (loop.py) owns ALL sequencing — phases, back-off
counters, and gates are code the models cannot argue with. Models are dispatched per
phase as subprocesses (`hermes chat` via the `ask` skill, see `dispatch.py`) and their
outputs are verified, never trusted. The locked correctness goal is **0 false-completes**:
every guarantee is enforced by a gate in `gate.py`/`dod_oracle.py`/`evidence.py`, and
every guard on that false-complete surface carries a killing mutant in `tests/mutants.py`
(see TESTING.md's "Invariant for changes").

Replaced the legacy v5/v6 sdlc engine (deleted 2026-07-01, commit `0344872`; ~8,300 LOC
removed). Rollback anchor = parent commit `255390f`.

## 1. CHARTER draft (planner)

Returns `interpreted_intent`, DoD criteria (`id`, `criterion`, `verify_intent`, `tier`),
assumptions (`text`, `confidence`), and open questions (`text`, `blocking`). Each
criterion is **tier-scoped**: `unit` = isolated new-logic behavior; `integration` =
behavior through existing code's real public surface. The prompt carries an environment
survey (`dispatch._environment_survey`): target repo modules + public symbols, with an
align-and-reuse directive and (when modifying existing code) a required integration-tier
criterion. Unknown tiers fail-safe to `unit`.

## 2. REFINE (coder-model pass)

Atomicizes criteria; behavior-not-structure (no "X delegates to Y" criteria). Carries the
same environment survey.

## 3. ADVISOR (single model × majority vote)

Core-missing-only completeness review; blocking gaps append blocking `open_questions`.
(`config.ADVISOR_VOTES` controls votes. NOT the multi-seat `advisors` skill.)

## 4. VAGUE-GOAL GATE (`gate.vague_goal_gate`, deterministic)

A quality-goal marker ("faster/cleaner/optimize/…") with no measurable target in the
REQUEST, or a criterion quoting a number the request never stated, routes to HUMAN_REVIEW.
Code-enforced because the prompt-only version provably false-completed (spike_recal).

## 5. AMBIGUITY GATE (`gate.ambiguity_gate`)

Invalid charter shape / any blocking open_question / min assumption confidence below
`config.CONFIDENCE_FLOOR` → HUMAN_REVIEW. Read the value from `config.py`.

## 6. DESIGN (designer, structured)

Returns a JSON spec; `render.py` renders ONE canonical pytest function per criterion (node
ids known by construction; a designer cannot fabricate coverage) into a **per-run oracle
file** (`test_devloop_dod_<run-slug>.py`). Re-runs on the same repo ACCUMULATE DoD
protection; concurrent runs never merge-conflict. Header imports only what the tests
reference. `testgen.collect_spec_map` intersects with REAL `pytest --collect-only`.

Designers receive the repo's real module→symbol map (never invent a module) and each
criterion's tier with the discipline: unit tests mock external boundaries (never the
function under test) so a failure isolates to the new logic; integration tests use real
collaborators, no mocks. Execution ladder: per-criterion nodes → whole-suite regression →
pre-merge-sync combined-tree regression.

## 7. COVERAGE + QUALITY LINT gates

- **COVERAGE GATE** (`dod_oracle.check_structural_coverage`, fail-closed).
- **QUALITY LINT GATE** (`quality_lint.py`, 2026-07-05): static scan of rendered test files
  with AST for known-bad patterns (module-level `mock.patch`, `Mock` without call inspection,
  datetime string literals, weak substring command assertions, `assert_called_with` on
  non-Mock) in <100ms.

On failure, the run spends its ONE oracle regeneration budget on a **quality_lint redesign**:
the designer gets category + fix_hint feedback and regenerates the tests. If the redesign
passes quality_lint, the run continues to judges; otherwise it routes to HUMAN_REVIEW.

## 8. JUDGE-ONCE

Two distinct judges × `config.JUDGE_VOTES` majority confirm each criterion's tests encode
it; judged once up-front (tests are fixed after DESIGN). A judge-untrusted test = TEST fault:
the run first spends its ONE oracle regeneration (fresh design + full re-gate up-front,
2026-07-02), and only a still-untrusted oracle routes to HUMAN_REVIEW.

Judges now return `(bool, str)` (2026-07-05): a vote plus a one-sentence reason.
`dod_oracle.py` returns `judge_a_reason`/`judge_b_reason`; `runner._redesign` threads the
reason text into the designer feedback prompt. Backward-compatible `_unwrap()` normalizes
bare `bool` → `(bool, "")`.

## 9. IMPLEMENT → LINT → EVIDENCE loop

- **Coder** writes code in the worktree (prompt carries the DoD, assumptions, handoff-quality
  directives; on retry it also receives failing output + an independent diagnosis after
  `config.DIAGNOSE_AFTER_ATTEMPT`).
- **LINT gate** (`lint.py`) blocks syntax errors.
- **FROZEN-TESTS gate** verifies every pass that no test file was edited, moved, or deleted
  since DESIGN (contents pinned; violations are self-healed — originals restored and
  re-IMPLEMENT, since a coder cannot restore what it never saw).
- **Evidence** (`evidence.run`) executes each criterion's pytest nodes — **the subprocess
  exit code is the only pass signal**.
- **Back-off is code**: `config.MAX_LOCAL_REBUILDS` rebuild fails → REPLAN, `config.MAX_REPLANS`
  → HUMAN_REVIEW. On exhaustion with RED evidence, ONE **judged test repair** may fire: two
  auditors see criterion + test source + failing evidence; only a UNANIMOUS "the TEST asserts
  the wrong output" sends the oracle back through the designer → coverage → judges →
  re-frozen snapshot. Every invoke is FRESH; checkpoints are post-mortem artifacts only.
- **STOP** (`gate.stop_condition`) — COMPLETE iff every criterion has coverage + a trusted
  judge verdict + passing evidence.
- **REGRESSION GATE** (`gate.regression_gate`): the whole repo suite (`pytest -q` at the
  worktree root) must also be green. A modify task cannot break pre-existing tests and still
  COMPLETE. Red = feedback + re-IMPLEMENT under the same back-off.
- **GREEN-SIDE OVERFIT AUDIT** (2026-07-03): two auditors recompute asserted values and
  inspect implementation for special-casing that only mirrors a test. UNANIMOUS indictment
  spends the one shared regeneration budget; split vote is a non-blocking ⚠ advisory in the
  grounding. (Parallelized 2026-07-05.)
- **COMMIT-SCOPE GATE**: an auditor classifies each changed non-PROTECTED file as deliverable
  or scratch; scratch is deleted and FULL verification re-runs on the pruned tree — red
  restores every file. Only intended items reach the commit.
- **COMPLETE** emits the **grounding report**: per criterion — text, proving tests, judge
  votes, passing evidence — into the trace, `devloop_result.grounding`, and the summary.

## Pre-merge sync

If the target branch advanced past the run's fork point, a **pre-merge sync** (2026-07-02)
first merges the target into the run branch in a throwaway checkout and re-runs the
whole-suite regression on the COMBINED tree. Conflicts go to the coder LLM (code-guarded:
never test files, no markers may survive) and a red combination gets ONE bounded LLM fix;
the regression gate decides. Dirty tree / unresolved conflict / red combination / detached
HEAD / branch-switch mid-run degrade to a kept branch with the reason.

## Concurrent runs

Supported (2026-07-03): each run isolated in its own `<repo>/.worktrees/<name>` checkout on
branch `devloop/<name>`. Per-run oracle filenames prevent collisions. Merges land **lock-free
via git's atomic ref compare-and-swap** (2026-07-04): the squash is committed with
`git commit-tree` parented on the verified tip, then published with
`git update-ref refs/heads/<target> <new> <tip>`. A concurrent devloop merge or foreign write that
moved HEAD off `tip` makes the CAS refuse atomically (`tip-moved`), leaving the branch for
review. Cross-run SEMANTIC conflicts still degrade to branch-for-review by design. See
`terminal-contract.md` for the full CAS mechanics and residual.
