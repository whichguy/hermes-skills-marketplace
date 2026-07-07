# SDLC Control Channel — File Lifecycle Design

> Produced by DeepSeek V4 Pro (2026-06-28) after a 3-seat advisor panel
> (DeepSeek + Kimi + Qwen, GLM synthesis) reviewed the original control
> channel adoption plan. The panel unanimously recommended DEFER, but
> this design addresses all 6 gaps they identified so implementation
> can proceed when a trigger condition fires.

## Verdict: DEFER until trigger condition

No active problem. Current prompts are ~2-8% of 128K+ context windows.
Zero incidents, zero overflow, zero checkpoint bugs traced to this.

**Trigger conditions:**
1. Phase prompt exceeds model context window
2. Pipeline uses smaller-context model (4K context)
3. Checkpoint/resume bug traces to lost in-memory state
4. New phase needs access to prior artifacts

## .sdlc/ Directory Structure (complete)

```
.sdlc/
├── ITERATION_STATE.json    # Checkpoint — overwritten each iteration
├── LEARNINGS.jsonl         # Append-only — one entry per DEBUG phase
├── PLAN.md                 # NEW — written by PLAN, read by IMPLEMENT
├── GAPS.md                 # NEW — written by VERIFYING, read by PLAN
├── events.jsonl            # P14 (future) — structured event log
└── STATUS.json             # P15 (future) — live status for polling
```

## Phase-by-Phase File Lifecycle

### PLAN phase

| Aspect | Specification |
|---|---|
| READS | `PROJECT.md` (always, from worktree root), `LEARNINGS.jsonl` (optional — skip if missing or empty), `GAPS.md` (optional — skip if missing, first-run), `*.py` source files (conditional — only after first IMPLEMENT, skip if no .py files exist) |
| WRITES | `PLAN.md` (always — overwrite) |
| Missing file handling | `LEARNINGS.jsonl` missing → empty learnings context. `GAPS.md` missing → no gap context (first run). `*.py` files missing → no code context (first run). None are fatal. |
| Stale file handling | `PLAN.md` from previous iteration is overwritten. `LEARNINGS.jsonl` is append-only so it's never stale — it only grows. `GAPS.md` from previous iteration is overwritten when new gaps are found. |
| Update strategy | **Overwrite** `PLAN.md`. The plan is a complete replacement, not a delta. |

**Code change in `sdlc_state.py` PLAN block (after line 1211):**

```python
# Write PLAN.md to .sdlc/ for file-based handoff
plan_path = os.path.join(run.sdlc_dir, "PLAN.md")
with open(plan_path, "w") as f:
    f.write(run.last_plan)
```

### IMPLEMENT phase

| Aspect | Specification |
|---|---|
| READS | `PLAN.md` (always — from `.sdlc/`), `PROJECT.md` (optional — for context) |
| WRITES | `*.py` source files, `test_*.py` files (always — via coder's tools) |
| Missing file handling | `PLAN.md` missing → fatal error (should never happen; PLAN always writes it). `PROJECT.md` missing → proceed without it (coder has plan). |
| Stale file handling | Source files from previous iteration are overwritten by coder's tools. |
| Update strategy | **Overwrite** source files. Coder writes complete files, not patches. |

**Code change in `sdlc_state.py` IMPLEMENT block (line 1234, add to prompt context):**

```python
# Read PLAN.md from .sdlc/ for file-based handoff
plan_path = os.path.join(run.sdlc_dir, "PLAN.md")
plan_content = ""
if os.path.exists(plan_path):
    with open(plan_path) as f:
        plan_content = f.read()
# Use plan_content instead of run.last_plan in the prompt
```

### VERIFYING phase

| Aspect | Specification |
|---|---|
| READS | `PROJECT.md` (always), `*.py` source files (always — via `read_code_state`) |
| WRITES | `GAPS.md` (conditional — only if verdict is GAPS) |
| Missing file handling | `PROJECT.md` missing → fatal (can't verify without criteria). `*.py` files missing → fatal (nothing to verify). |
| Stale file handling | `GAPS.md` from previous iteration is overwritten when new gaps are found. If verdict is SATISFIED, `GAPS.md` is NOT deleted (preserves history for debugging). |
| Update strategy | **Conditional overwrite** — write only when verdict is GAPS. If verdict is SATISFIED, leave existing `GAPS.md` untouched (it documents what WAS wrong). |

**Code change in `sdlc_state.py` VERIFYING block (after line 1521):**

```python
# Write GAPS.md to .sdlc/ for file-based handoff to next PLAN
gaps_path = os.path.join(run.sdlc_dir, "GAPS.md")
with open(gaps_path, "w") as f:
    f.write(f"# Gap Analysis — Iteration {run.iteration}\n\n{gaps}")
```

### DEBUG phase

| Aspect | Specification |
|---|---|
| READS | `*.py` source files (via `read_code_state`), test output (via `run.last_test_result`) |
| WRITES | `LEARNINGS.jsonl` entry (appended), fixed `*.py` files (overwritten) |
| Missing file handling | Source files missing → fatal (nothing to debug). Test output missing → proceed with empty error context. |
| Stale file handling | LEARNINGS.jsonl is append-only — never stale. Fixed source files overwrite previous versions. |
| Update strategy | **Append** to LEARNINGS.jsonl. **Overwrite** source files with fixed code. |

### IMPASSE diagnosis (FAILED terminal state)

| Aspect | Specification |
|---|---|
| READS | `PROJECT.md` (always), `LEARNINGS.jsonl` (always — last 20 entries), `PLAN.md` (optional — last plan attempted), `GAPS.md` (optional — last gaps found) |
| WRITES | Nothing (output to stderr only) |
| Missing file handling | All optional except `PROJECT.md` and `LEARNINGS.jsonl`. Missing `PLAN.md` → note in diagnosis. Missing `GAPS.md` → note in diagnosis. |

**Code change in `sdlc_state.py` IMPASSE block (line 1655, expand context):**

```python
# Read PLAN.md and GAPS.md for richer diagnosis context
plan_path = os.path.join(run.sdlc_dir, "PLAN.md")
gaps_path = os.path.join(run.sdlc_dir, "GAPS.md")
extra_context = ""
if os.path.exists(plan_path):
    with open(plan_path) as f:
        extra_context += f"\n\n## Last Plan\n{f.read()[:2000]}"
if os.path.exists(gaps_path):
    with open(gaps_path) as f:
        extra_context += f"\n\n## Last Gaps\n{f.read()[:2000]}"
# Append extra_context to the diagnosis prompt
```

## LEARNINGS.jsonl Consumption — The Critical Blocker

**Problem:** `read_learnings()` returns raw JSON. The planner model sees:

```json
{"iteration": 3, "root_cause": "missing import for pytest", "fix": "added import", ...}
{"iteration": 4, "root_cause": "TypeError on None input", "fix": "added None guard", ...}
```

This is hard for an LLM to parse usefully. The model has to mentally extract
root_cause and fix from JSON, correlate across entries, and identify patterns —
all in a single forward pass.

**Solution: Structured text summary instead of raw JSON.**

Replace `read_learnings()` output format with a human-readable summary:

```python
def read_learnings_formatted(sdlc_dir: str, window: int = LEARNINGS_WINDOW) -> str:
    """Read LEARNINGS.jsonl and return a structured text summary for PLANNING context."""
    entries = _read_learnings_raw(sdlc_dir, window)
    if not entries:
        return ""
    
    lines = ["## Accumulated Learnings\n"]
    lines.append(f"{len(entries)} debug iterations recorded.\n")
    
    # Group by root_cause to surface patterns
    from collections import Counter
    causes = Counter(e.get("root_cause", "unknown") for e in entries)
    if len(causes) > 1:
        lines.append("### Recurring Root Causes")
        for cause, count in causes.most_common(5):
            lines.append(f"- [{count}x] {cause[:120]}")
        lines.append("")
    
    # Most recent N entries as structured bullets
    lines.append(f"### Recent ({min(window, len(entries))} most recent)")
    for e in entries[-window:]:
        lines.append(f"- Iter {e.get('iteration', '?')}: {e.get('root_cause', '?')[:100]}")
        if e.get('fix'):
            lines.append(f"  Fix: {e['fix'][:100]}")
        if e.get('learning') and e['learning'] != e.get('root_cause', ''):
            lines.append(f"  Learning: {e['learning'][:100]}")
    
    return "\n".join(lines)
```

This gives the planner: (a) recurring patterns via Counter, (b) chronological
history via bullets, (c) fix/learning per entry. No JSON parsing required.

**Code change:** Replace `read_learnings(run.sdlc_dir)` call at line 1174 with
`read_learnings_formatted(run.sdlc_dir)`. Keep `read_learnings()` for internal
use (repeated_root_cause, impasse diagnosis).

## GAPS.md Lifecycle

| Event | GAPS.md action |
|---|---|
| First run (no prior GAPS) | File doesn't exist. PLAN phase skips it. |
| VERIFYING returns GAPS | **Overwrite** GAPS.md with structured gap analysis. Include iteration number and timestamp in header. |
| VERIFYING returns SATISFIED | **Do not delete** GAPS.md. It documents what was wrong and how it was fixed — valuable for post-mortem. |
| Next PLAN phase | **Read** GAPS.md if it exists. The planner sees the most recent gap analysis. |
| GAPS.md grows too large | Not a concern — it's overwritten each time, so it's always exactly one iteration's gaps (~500-2000 chars). |

**Why overwrite, not append:** GAPS.md represents the CURRENT gap state. When
the planner addresses gaps and the verifier finds new ones, the old gaps are
resolved. Appending would create confusion about which gaps are still open.
The iteration history is preserved in LEARNINGS.jsonl and ITERATION_STATE.json.

## Resume Consistency

**ITERATION_STATE.json is authoritative. LEARNINGS.jsonl is advisory.**

On resume:
1. Load ITERATION_STATE.json → restore iteration, stagnation counters, prev_gaps, last_plan
2. LEARNINGS.jsonl is read fresh each PLAN phase — it always reflects ground truth
3. If LEARNINGS.jsonl has more entries than the iteration count suggests, that's fine — the planner sees all of them
4. If PLAN.md exists but ITERATION_STATE.json says state=INIT, the PLAN.md is from a previous run — it will be overwritten
5. If GAPS.md exists but run.prev_gaps is empty, the GAPS.md is from a previous run — the planner will read it and it may or may not still be relevant

**No reconciliation needed.** The checkpoint is the source of truth for state
machine position. The .sdlc/ files are the source of truth for content. They
can disagree without causing corruption — the worst case is the planner sees
slightly stale gap/learning data, which is harmless.

**One edge case to handle:** If ITERATION_STATE.json is corrupt/missing but
.sdlc/ files exist, treat as fresh start. The files will be overwritten. This
is already the behavior — `load_state()` returns `{}` on JSONDecodeError.

## Fallback Design: "Model Didn't Read the File"

**Lightweight heuristic detection, not enforcement.**

After PLAN phase produces `run.last_plan`, check if the plan references learnings:

```python
def _plan_references_learnings(plan: str, learnings_ctx: str) -> bool:
    """Heuristic: does the plan appear to have consumed the learnings context?"""
    if not learnings_ctx:
        return True  # Nothing to reference — vacuously satisfied
    # Check if plan mentions any root_cause keywords from learnings
    learnings_lower = learnings_ctx.lower()
    plan_lower = plan.lower()
    # Extract distinctive words from learnings (root causes, fixes)
    keywords = set()
    for line in learnings_ctx.split('\n'):
        if 'root_cause' in line.lower() or 'fix:' in line.lower():
            words = re.findall(r'\b\w{5,}\b', line.lower())
            keywords.update(words)
    if not keywords:
        return True  # No distinctive keywords to check
    matches = sum(1 for kw in keywords if kw in plan_lower)
    return matches >= 2  # At least 2 keyword matches suggests consumption
```

If the plan doesn't reference learnings, emit a warning but don't block:

```
⚠️ plan may not have consumed learnings (0/15 keyword matches)
```

This is a diagnostic, not a gate. The pipeline continues. If the plan is bad,
tests will fail and the debug loop will catch it. The warning helps with
post-mortem: "did the model ignore the file, or was the file irrelevant?"

## Summary of Code Changes in sdlc_state.py

| Line | Change | Purpose |
|---|---|---|
| After 1211 | Write `PLAN.md` to `.sdlc/` | File-based handoff PLAN → IMPLEMENT |
| 1234 (prompt) | Read `PLAN.md` from `.sdlc/` instead of `run.last_plan` | IMPLEMENT reads plan from file |
| 1174 | Replace `read_learnings()` with `read_learnings_formatted()` | Structured text instead of raw JSON |
| After 1521 | Write `GAPS.md` to `.sdlc/` (conditional on GAPS verdict) | File-based handoff VERIFYING → PLAN |
| 1181-1182 | Read `GAPS.md` from `.sdlc/` instead of `run.prev_gaps` | PLAN reads gaps from file |
| 1655 (impasse) | Add `PLAN.md` and `GAPS.md` to diagnosis context | Richer impasse diagnosis |
| New function | `read_learnings_formatted()` | Structured text summary for planner |
| New function | `_plan_references_learnings()` | Heuristic detection (diagnostic only) |

**Total: ~60 lines of new code, 8 lines of modifications. No new dependencies.
All backwards-compatible — existing behavior unchanged when files are missing.**

## Advisor Panel Findings (2026-06-28)

3-seat panel (DeepSeek V4 Pro + Kimi K2.7 Code + Qwen 3.6 35B, GLM synthesis)
reviewed the original control channel adoption plan. Unanimous verdict: DEFER.

### Agreements (all 3)
- Defer — no active problem, current prompts are ~2-8% of 128K+ context windows
- ~40 line estimate is wrong — realistic is 80-150+ lines
- LEARNINGS.jsonl is the critical unhandled dependency
- "Zero impact on checkpoint/resume" is wrong — dual-source problem
- "Minimal test complexity" is wrong — needs filesystem setup
- Model file-reading reliability is a real risk (especially for local models)

### Gaps Found (all addressed in this design)
1. LEARNINGS.jsonl entirely unhandled → `read_learnings_formatted()` solution
2. GAPS.md lifecycle unspecified → overwrite-on-GAPS, preserve-on-SATISFIED
3. GAPS.md doesn't exist on first run → conditional creation
4. Resume consistency → JSON authoritative, files advisory
5. Fallback design → heuristic warning (diagnostic, not gate)
6. Impasse diagnosis → added PLAN.md + GAPS.md to context
