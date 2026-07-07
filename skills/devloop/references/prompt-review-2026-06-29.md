# Prompt review (2026-06-29) + step-2 (B1) authoring blueprint

Two `prompt-reviewer` passes over the model-facing prose: `spike/spike_skill.md` (the de-risk
instrument) and `SKILL.md` (the orchestrator). Findings + what was applied + the section spec.

## spike/spike_skill.md — APPLIED (rewritten + re-validated)
The review found the prose was loose enough that a "pass" could be untrustworthy. Fixes applied:
- **Assumption loophole CLOSED** (critical): "state assumptions explicitly" contradicted "don't
  invent a target" — a model could "assume" a missing number and PROCEED. Now: may only restate
  requester-supplied values; a missing target → ROUTE_HUMAN_REVIEW, even if labeled an assumption.
- **Exhaustive marker whitelist** (only the 8 permitted `[DEVLOOP-SPIKE]` tokens; no stray
  SUGGESTION/NOTE) — kills the runtime-trailer noise in scoring.
- **No code fences** around markers (a fenced marker is invisible to the parser); bare lines only.
- **No preamble grouping** — each PHASE marker immediately before its own content (kills the
  "table of contents" vacuous-pass).
- One-marker-each; STOP only at VERIFY with no self-justification; HUMAN_REVIEW ends output;
  headless "never ask a clarifying question"; DECISION after the DoD text.
- **Re-validated live**: clean task → clean PROCEED+pass, no stray trailer; loophole probe
  ("acceptably fast") → ROUTE_HUMAN_REVIEW with "I must not invent thresholds or label them as
  assumptions." Loophole confirmed closed; fidelity preserved.

## SKILL.md — APPLIED
- **C-1 (clarified, NOT inverted)**: the reviewer claimed `if state.validate_charter(charter):
  ROUTE_HUMAN_REVIEW` is inverted and said add `not`. **That is WRONG** — `validate_charter`
  returns an ERROR LIST (`[]` == valid), so the truthy branch fires on errors → correct. The
  reviewer assumed a boolean. The prose was clarified (and a "do not add `not`" warning added) so
  the next reader can't make the same misread. Lesson: a reviewer misreading prose IS a prose bug.
- **C-2**: ported the measurable-target rule into Phase 0 DoD authoring (was only in the spike).
- **C-3**: added "you have NO authority to declare COMPLETE — only `gate.stop_condition()` does."
- **H-1**: advisor blocking/advisory split made structural (model can't reclassify `blocking:true`).
- **H-3**: added a mid-loop ambiguity handler (PLAN/BUILD/VERIFY/DEBUG → append blocking q →
  ambiguity_gate → HUMAN_REVIEW; never resolve by inference).
- **H-4**: "the controller" → "you (the model) ARE the controller; you MUST call on_rebuild_fail/
  on_replan/backoff_exhausted." **H-5**: kanban-split row now STOPs the run + checkpoints + routes
  to HUMAN_REVIEW with a proposed decomposition (was undefined). **M-1**: fixed invalid pseudocode
  `min(...)` syntax. **M-2**: wall-clock backstop = runtime-enforced, not the model. **M-4**:
  separated structural validity from the gate outcome for empty assumptions.

## SKILL.md — DEFER TO B1 (these sections get rewritten when authored)
- **H-2** (categorical "never re-plan except…") — partly applied to the back-off note; finalize in
  the `plan`/`debug_cascade` sections.
- **M-3** (lint "not a separate state" → specify: inline retry; lint-cap-exhausted ⇒ BUILD fails ⇒
  then `on_rebuild_fail()`) — belongs in the `implement` section.

---

# B1 authoring blueprint — the 7 versioned prompt sections
Each section must specify: input · model (via `ask`) · output schema · gates called · failure modes.

- **intake** — in: raw request. model: `ask planner` (GLM-5.2). out:
  `{interpreted_intent, assumptions:[{text,confidence∈[0,1]}], open_questions:[{text,blocking}]}`.
  rules: never add an assumption the request doesn't support; a quantitative target with no
  requester number → blocking open_question (NOT an assumption); confidence is epistemic not
  aspirational (1.0 only for facts stated verbatim). fail: malformed → retry once → HUMAN_REVIEW.
- **dod_synthesis** — in: intake output. model: `ask planner`, alignment-checked by DeepSeek. out:
  `{criteria:[{id,text,verify_intent,measurable}]}`. rules: stable unique `id` per criterion
  (threads end-to-end, never regenerated); `verify_intent` must be test-encodable; `measurable:false`
  ⇒ blocking open_question; no invented numbers. fail: any `measurable:false` not converted ⇒ error,
  do not checkpoint.
- **plan** — in: locked Charter + `blast_radius.scope()`. model: `ask planner`. out:
  `{files,order,rationale}`. rules: blast-radius-first (scope from `blast_radius`, model picks ONLY
  order); write-once (no revisit unless back-off prescribes REPLAN within budget); scope-over-threshold
  ⇒ STOP + propose kanban + HUMAN_REVIEW. gates: checkpoint plan. **Also wire the `scan_degraded`/
  `truncated` contract: force a whole-suite VERIFY when blast_radius signals degraded** (roadmap gap).
- **implement** — in: Charter, plan, blast-scoped cross-file context, SHOWN tests. model:
  `ask qwen3-coder-next`. out: changes in the WORKTREE (never main). rules: worktree-only; inject
  cross-file contracts before dependents; lint sub-gate inline via `evidence.run()` — lint-cap
  exhausted ⇒ BUILD fails ⇒ `state.on_rebuild_fail()` (M-3); "it looks right" without a passing
  evidence.run is inadmissible.
- **design_test_suites** — in: DoD ids+verify_intents, worktree state. model: DeepSeek (≠ implementer).
  out: ≥1 test per verify_intent, each annotated `# dod:<id>`; holdout tests separate. rules: generate
  FROM ids not from reading code; `check_structural_coverage` must pass (fail-closed: 0 tests ⇒ block);
  `judge_assertions` (2 distinct models, ≠ implementer) must confirm each assertion encodes its
  criterion before VERIFY. **Derive test→criterion from actually-collected annotated nodes; reject any
  id with no real node** (closes the vacuous-coverage forge — roadmap A1).
- **debug_cascade** — in: evidence failure signal, last-20 LEARNINGS, DoD, failure count. model:
  Kimi→Qwen→DeepSeek via `ask` (stop on first passing evidence.run). rules: consult back-off table
  FIRST; same failure 2× ⇒ suspect wrong test ⇒ re-audit via `judge_assertions` before touching code;
  `on_rebuild_fail()` per step; no re-plan; a new evidence.run is the ONLY success signal.
- **council_dod_check** — in: Charter, full evidence ledger (by id), judge_verdicts, coverage_ok.
  model: `advisors` via `gate.council_gate()`. rules: pass ALL oracle artifacts into
  `gate.stop_condition(charter, ledger, council_affirmed, coverage_ok, judge_verdicts)` (gate consumes,
  doesn't re-run); fail-closed on None/partial quorum; evaluate completeness AND satisfaction; model
  must NOT read council output as COMPLETE.

**Code guard for B2** (kernel can't self-enforce today): assert `judge_a != judge_b != implementer`
model-id at the `judge_assertions` dispatch site — wiring one model twice makes a==b agreement
automatic and the anti-gaming oracle degenerates to self-approval.
