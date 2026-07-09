# NBQ + Investigator Integration with Devloop

## Architecture: No Duplication, Two Layers

Devloop and the NBQ/investigator stack operate at **different decision layers**.
There is no duplication — they answer different questions:

```
┌─────────────────────────────────────────────────────────────────────┐
│  SCOUT PIPELINE (devloop_pipeline_cli.py)                           │
│  "What steps should we build?" → multi-step pathfinding             │
│                                                                     │
│  User Goal                                                          │
│    │                                                                │
│    ▼                                                                │
│  relentless-solve (subprocess, read-only, journal-resumable)        │
│    ├── CLARIFY: investigator/scripts/iterate.py                     │
│    │     ├── NBQ (infogain.py): ranks next-best questions by EVSI   │
│    │     ├── Research: full Hermes agent investigates top-K          │
│    │     ├── Tombstones: answered facts + known gaps                 │
│    │     └── Convergence: re-rank with evidence → stop when empty    │
│    ├── PLAN: task-decomposer → ordered steps with success criteria  │
│    ├── EXECUTE: hermes oneshot per task (bounded local retry)       │
│    └── HARVEST: fold evidence → next cycle                          │
│    │                                                                │
│    ▼                                                                │
│  scout-steps.json (ordered build steps, schema-validated)           │
│                                                                     │
│  For each step:                                                     │
│    ▼                                                                │
│  devloop runner.run_task()                                          │
│    ├── CHARTER: "What are the testable criteria for THIS step?"     │
│    │     dispatch.charter_via_ask (single model call)               │
│    │     + dispatch.refiner_via_ask (atomicize criteria)            │
│    │     + dispatch.advisor_via_ask (review blocking gaps)           │
│    ├── VAGUE_GOAL_GATE: deterministic marker check                  │
│    ├── AMBIGUITY_GATE: deterministic confidence check               │
│    ├── DESIGN: structured test spec → rendered pytest               │
│    ├── JUDGE: 2-model assertion judging (encodes criterion?)        │
│    ├── IMPLEMENT: coder writes code in worktree                     │
│    ├── LINT: py-syntax + ruff + mypy (+ 12 other file types)        │
│    ├── EVIDENCE: run tests, collect pass/fail per criterion         │
│    ├── REGRESSION: whole-suite regression gate                      │
│    ├── OVERFIT_AUDIT: 2-model audit for overfitting                 │
│    ├── COMMIT_SCOPE: classify changed files as deliverable/chaff    │
│    └── COMPLETE → merge to main                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Layer Separation (No Duplication)

| Layer | Question Answered | Tool | When |
|---|---|---|---|
| **Scout (relentless-solve)** | "What steps should we build? What's the happy path?" | investigator + NBQ | Before any devloop run, in the scout phase |
| **Devloop charter** | "What are the testable criteria for THIS step?" | charter_via_ask (single model call) | Per step, after scout decomposes the goal |
| **Vague goal gate** | "Is this goal measurable at all?" | gate.vague_goal_gate (deterministic) | After charter, before design |
| **Ambiguity gate** | "Is the charter confident enough to proceed?" | gate.ambiguity_gate (deterministic) | After charter, if vague goal gate passes |

The scout layer uses NBQ/investigator because the question "what steps should we
build?" is genuinely underspecified — the agent needs to research the codebase,
understand dependencies, and find the viable path. That's exactly what
investigator is designed for.

The devloop charter layer does NOT use NBQ/investigator because by the time a
step reaches devloop, the scout has already narrowed the scope to a single
well-defined task. The charter prompt asks one model: "turn this specific task
into testable criteria." This is a structured transformation, not an
investigation.

## The Gap: Direct Devloop Calls (Without Scout)

When a user calls devloop **directly** (not through the scout pipeline), the
charter phase has no NBQ/investigator pre-clarification. A vague request goes
straight to the planner model, which may fabricate benchmarks (caught by
vague_goal_gate) or produce a charter with blocking open_questions (caught by
ambiguity_gate).

### Current mitigation (sufficient)

The deterministic gates are the primary defense and they cost zero model calls:

1. **Vague goal gate** — checks if the request contains vague markers ("fast",
   "better", "robust") and whether the charter fabricated benchmarks not in the
   request. Routes to HUMAN_REVIEW if so.
2. **Ambiguity gate** — checks if the charter's confidence is above floor and
   whether it has blocking open_questions. Routes to HUMAN_REVIEW if so.
3. **Environment survey** — the charter prompt includes `_environment_survey()`
   which lists existing modules and public symbols, giving the planner context
   about the codebase.

### Pre-clarify hook (opt-in, not default)

An optional `pre_clarify=True` parameter on `run_task()` runs NBQ fast-rank
before the charter phase. If questions are above floor, the investigator
researches them and produces a refined prompt. This is NOT the default because:

- The deterministic gates already catch underspecification for free (0 model calls)
- Pre-clarify costs ~45s for NBQ fast-rank on every call, plus ~1-2 min for
  investigator when it fires — to save a ~5s charter model call that the gates
  already catch
- It over-triggers: well-specified requests (like the multi-file e2e) still
  produce questions above floor, causing unnecessary investigator runs
- When devloop is called through scout, the scout's clarify phase already
  resolved the unknowns — pre-clarify would be redundant

Use `pre_clarify=True` only when a caller KNOWS their request is vague and
wants the investigator to refine it before the charter phase.

### Implementation

The hook lives in `runner.py` before the charter phase:

```python
# PRE-CLARIFY: if the request is underspecified, use NBQ+investigator
# to refine it before the charter phase. Skipped when scout already
# clarified (well-specified requests yield an empty NBQ bucket).
if pre_clarify and real_judges:
    refined = _pre_clarify(request, target)
    if refined:
        request = refined
        loop._progress_event(run_dir, "pre_clarify",
            detail=f"refined vague request via investigator")
```

The `_pre_clarify` function:
1. Calls `infogain.run()` in fast-rank mode (single model call)
2. If no questions above floor → return None (well-specified, skip)
3. If questions above floor → calls `iterate.iterate()` in quick mode (K=2, 1 round)
4. Returns the refined prompt from the investigator

### Cost

- Well-specified requests: ~45s for the NBQ fast-rank call (one model call,
  then bucket is empty → skip)
- Underspecified requests: ~45s NBQ + ~1-2 min investigator = ~2-3 min total
- Scout pipeline calls: ~45s NBQ (bucket will be empty because scout already
  clarified) → skip

The cost is bounded and only fires when needed. The NBQ fast-rank call is
the gate — it's a single model call that determines whether the heavier
investigator loop is warranted.

## Configuration

| Setting | Default | Override |
|---|---|---|
| `pre_clarify` | `False` (opt-in only) | `--pre-clarify` CLI flag |
| `pre_clarify_floor` | `0.30` (matches NBQ discard_threshold) | `DEVLOOP_PRE_CLARIFY_FLOOR` env |
| `pre_clarify_model` | `glm` (follows NBQ defaults) | `DEVLOOP_PRE_CLARIFY_MODEL` env |

**Why opt-in, not default:** The deterministic gates (vague_goal_gate, ambiguity_gate)
already catch underspecification for zero model calls. Pre-clarify costs ~45s for NBQ
fast-rank on every call, plus ~1-2 min for investigator when it fires — to save a ~5s
charter model call that the gates already catch. It also over-triggers: well-specified
requests still produce questions above floor, causing unnecessary investigator runs.
When devloop is called through scout, the scout's clarify phase already resolved the
unknowns — pre-clarify would be redundant. Use `pre_clarify=True` only when a caller
KNOWS their request is vague and wants the investigator to refine it before charter.

## Progress Markers

The pre-clarify hook emits progress markers for visibility:

```
[devloop] ⏳ pre_clarify: checking if request needs clarification...
[devloop] ✅ pre_clarify (45s): well-specified, skipping investigator
```

Or when clarification is needed:

```
[devloop] ⏳ pre_clarify: checking if request needs clarification...
[devloop] ⏳ pre_clarify (45s): 3 questions above floor, investigating...
[devloop] ✅ pre_clarify (120s): refined request with 2 facts, 1 gap
```

## Test Coverage

- **Unit test**: `_pre_clarify` with a well-specified request → returns None
- **Unit test**: `_pre_clarify` with a vague request → returns refined string
- **Integration test**: `run_task` with `pre_clarify=True` and a well-specified
  request → charter phase receives the original request unchanged
- **Integration test**: `run_task` with `pre_clarify=False` → skips NBQ entirely
- **E2E test**: Direct devloop call on a vague request → pre-clarify fires,
  investigator researches, refined prompt reaches charter