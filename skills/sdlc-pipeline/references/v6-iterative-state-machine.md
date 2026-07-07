# v6 Iterative State Machine — Architecture & Design Decisions

> Created: 2026-06-28 | Session: SDLC orchestrator redesign (5→45 iteration scaling)

## Overview

The v6 iterative state machine extends `sdlc_state.py` (the SDLC pipeline's state
machine module) with a new execution loop designed for **45-iteration runs** where
stagnation detection is the primary terminator, not max-iterations.

## Key Design Decisions

### 1. 45-Iteration Scaling (not 5)

The user corrected from 5 to 45 iterations. This fundamentally changes the design:

| Parameter | v5 (5 iter) | v6 (45 iter) |
|---|---|---|
| `max_iterations` default | 3 | **45** |
| `wall_clock_budget` | none | **7200s (2 hours)** |
| Primary terminator | Max iterations | **Stagnation counters** |
| `LEARNINGS_WINDOW` | 10 | **20** |
| Checkpoint/resume | Not needed | **Critical** (ITERATION_STATE.json) |
| `MAX_RESUMES` | N/A | **3** across runs |

### 2. Three Independent Stagnation Counters

Each counter tracks a different failure mode. All three must hit `STAGNATION_LIMIT` (3)
independently — a single counter at 3 triggers FAILED.

- **`test_stagnation`** — test pass count not improving (Δ ≤ 0) or regressions
- **`root_cause_stagnation`** — same root cause appearing in LEARNINGS.jsonl
- **`gap_stagnation`** — verifier returning identical GAPS text

### 3. LEARNINGS.jsonl (Append-Only Learning Journal)

Structured JSONL entries appended during DEBUGGING. Each entry captures:
- `iteration`, `ts`, `phase`, `failures`, `root_cause`, `fix`, `learning`
- `file_paths`, `model`, `commit_hash`, `severity`, `regression`

The planner reads the last `LEARNINGS_WINDOW` (20) entries as context.
`repeated_root_cause()` checks BEFORE appending (off-by-one fix from v3 review).

### 4. Checkpoint/Resume (ITERATION_STATE.json)

Atomic saves via `tempfile.mkstemp` + `os.replace`. Persists:
- `total_resume_count`, `human_review_count`, `iteration`
- All three stagnation counters

On resume, if `total_resume_count >= MAX_RESUMES` (3), aborts immediately.

### 5. LINT_FIX as Script-Only State

No model dispatch — runs `ruff format` + `ruff check --fix --unsafe-fixes`.
If unfixable lint remains, appends errors to the plan and loops back to IMPLEMENT.
Max 3 retries (`MAX_LINT_RETRIES`), then FAILED.

### 6. Tight/Wide Loop Routing

```
DEBUGGING → root_cause_stagnation == 0 → RUN_TESTS (tight loop: re-run tests)
DEBUGGING → root_cause_stagnation >= 1 → PLAN (wide loop: re-plan with learnings)
DEBUGGING → root_cause_stagnation >= 3 → FAILED
```

### 7. Impasse Diagnosis

On FAILED, dispatches DeepSeek for root-cause analysis:
- Reads last 20 learnings + PROJECT.md + stagnation counters
- Identifies structural blocker (constraint conflict, missing capability, ambiguous criterion)
- Suggests specific PROJECT.md changes to unblock

### 8. HUMAN_REVIEW State

Triggered when verifier returns UNCERTAIN 2 consecutive times.
Presents 4 options: continue with guidance, update PROJECT.md, accept partial, abort.
Max `MAX_HUMAN_REVIEWS` (3) before forced FAILED.

## New States (4 added to existing 12)

| State | Type | Description |
|---|---|---|
| `LINT_FIX` | Script-only | ruff format + check, no model |
| `VERIFYING` | Model (DeepSeek) | Check acceptance criteria |
| `FAILED` | Terminal | Stagnation or max iterations |
| `HUMAN_REVIEW` | Terminal | UNCERTAIN × 2, needs human |

## New Helper Functions (14)

| Function | Purpose |
|---|---|
| `save_state()` | Atomic JSON save with tempfile |
| `load_state()` | Load checkpoint JSON |
| `read_learnings()` | Read last N LEARNINGS.jsonl entries |
| `append_learning()` | Append structured learning entry |
| `repeated_root_cause()` | Check root_cause frequency (off-by-one safe) |
| `read_code_state()` | Read .py files from worktree for planner context |
| `run_ruff()` | Run ruff format + check, return {clean, unfixable} |
| `run_tests_in_worktree()` | Run pytest, return structured result with passing_names |
| `extract_verdict()` | Parse SATISFIED/GAPS/UNCERTAIN from verifier output |
| `extract_debug_info()` | Parse root_cause/fix/learning from debugger output |
| `parse_project_config()` | Parse Configuration section from PROJECT.md |
| `iterative_transition()` | Transition function for v6 state machine |
| `run_iterative_state_machine()` | Main v6 execution loop |
| `_emit_iterative_summary()` | Final summary + impasse diagnosis |

## Model Assignment

| Phase | Model | Provider |
|---|---|---|
| PLANNING | `glm-5.2:cloud` | `ollama-glm` |
| IMPLEMENTING | `qwen3-coder-next:q4_K_M` | `ollama-glm` |
| VERIFYING | `deepseek-v4-pro:cloud` | `ollama-glm` |
| DEBUGGING | cascade (Kimi → Qwen → DeepSeek) | `ollama-glm` |

## Backward Compatibility

v5 `run_state_machine()`, `default_transition()`, and `DiminishingReturnsTracker`
are fully preserved. Callers choose v5 or v6 by which function they invoke.

## Integration Pattern

The v6 state machine was integrated into the existing `sdlc_state.py` module
(part of the `ask` skill's scripts directory), NOT built as a standalone script.
A standalone `orchestrator.py` was initially built, then deleted per user
correction: "integrate into the SDLC skill, don't build standalone."

## Verification

12/12 ad-hoc checks passed (2026-06-28):
- py_compile, import, 16-state enum, SDLCRun v6 fields, constants (45/7200/3)
- All 14 helpers exist, learnings round-trip + off-by-one, state persistence
- Verdict extraction, config parsing, iterative_transition, v5 backward compat
