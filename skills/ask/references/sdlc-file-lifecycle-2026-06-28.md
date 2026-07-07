<!--
model: deepseek-v4-pro:cloud
provider: ollama-glm
elapsed: 55.0s
chars: 15776
session_id: 20260628_015614_d53215
thinking: high
-->

Now I have the complete picture. Let me trace the actual file flows from the code and produce the plan section.

---

## File Lifecycle Design

### Current State (from code audit)

The v6 state machine in `sdlc_state.py` already has implicit file I/O at each phase, but it's undocumented and inconsistent:

| Phase | Actually READS | Actually WRITES | Where |
|---|---|---|---|
| PLAN | PROJECT.md (in-memory), LEARNINGS.jsonl (via `read_learnings`), source .py files (via `read_code_state`), prev_gaps (in-memory) | `run.last_plan` (in-memory only), ITERATION_STATE.json (checkpoint) | Lines 1174-1215 |
| IMPLEMENT | `run.last_plan` (in-memory) | `*.py`, `test_*.py` (via coder's terminal/file tools) | Lines 1218-1278 |
| LINT_FIX | `*.py` files (via ruff) | `*.py` files (ruff format in-place) | Lines 1281-1296 |
| TESTING | `*.py`, `test_*.py` (via pytest) | Nothing (read-only) | Lines 1299-1331 |
| DEBUG | source .py (via `read_code_state`), test output (in-memory) | LEARNINGS.jsonl (appended), fixed `*.py` (overwritten) | Lines 1334-1462 |
| VERIFYING | PROJECT.md (in-memory), source .py (via `read_code_state`) | `run.prev_gaps` (in-memory), ITERATION_STATE.json | Lines 1465-1546 |
| IMPASSE | PROJECT.md (in-memory), LEARNINGS.jsonl (via `read_learnings`) | Nothing (stdout only) | Lines 1650-1675 |

**Critical gaps found:**

1. **PLAN.md doesn't exist on disk.** The plan lives only in `run.last_plan` (a Python string) and in `ITERATION_STATE.json`. If the orchestrator crashes between PLAN and IMPLEMENT, the plan is recoverable from the checkpoint — but the IMPLEMENT phase reads it from memory, not from a file. This means the coder model never sees a `PLAN.md` file in the worktree; it only sees the plan text embedded in its prompt context.

2. **GAPS.md doesn't exist on disk.** Same pattern — `run.prev_gaps` is in-memory and checkpointed, but never written as a standalone file. The next PLAN phase sees it via `run.prev_gaps` injected into context (line 1181-1182), not by reading a file.

3. **LEARNINGS.jsonl is the only .sdlc/ file that persists across iterations.** ITERATION_STATE.json is overwritten each iteration. LEARNINGS.jsonl is append-only. There's no PLAN.md or GAPS.md on disk at all.

4. **The planner consumes LEARNINGS.jsonl as raw JSON.** `read_learnings()` (line 709-728) returns `"\n".join(json.dumps(e) for e in recent)` — a string of JSON objects separated by newlines. The planner model has to parse JSON in its head. This is the "critical blocker" the advisors identified.

5. **No file-based handoff between phases.** PLAN → IMPLEMENT passes data through `run.last_plan` (Python string). VERIFYING → PLAN passes data through `run.prev_gaps` (Python string). If the orchestrator process dies, these survive in ITERATION_STATE.json but are invisible to the models — the models only see what's in their prompt context.

6. **Resume loads from ITERATION_STATE.json but doesn't reconcile with .sdlc/ files.** If LEARNINGS.jsonl has 15 entries but ITERATION_STATE.json says iteration 3, there's no consistency check. The checkpoint wins silently.

---

### Design: File Lifecycle Per Phase

#### .sdlc/ Directory Structure (complete)

```
.sdlc/
├── ITERATION_STATE.json    # Checkpoint — overwritten each iteration
├── LEARNINGS.jsonl         # Append-only — one entry per DEBUG phase
├── PLAN.md                 # NEW — written by PLAN, read by IMPLEMENT
├── GAPS.md                 # NEW — written by VERIFYING, read by PLAN
├── events.jsonl            # P14 (future) — structured event log
└── STATUS.json             # P15 (future) — live status for polling
```

#### Phase-by-Phase Specification

**PLAN phase**

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

**IMPLEMENT phase**

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

**VERIFYING phase**

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

**DEBUG phase**

| Aspect | Specification |
|---|---|
| READS | `*.py` source files (via `read_code_state`), test output (via `run.last_test_result`) |
| WRITES | `LEARNINGS.jsonl` entry (appended), fixed `*.py` files (overwritten) |
| Missing file handling | Source files missing → fatal (nothing to debug). Test output missing → proceed with empty error context. |
| Stale file handling | LEARNINGS.jsonl is append-only — never stale. Fixed source files overwrite previous versions. |
| Update strategy | **Append** to LEARNINGS.jsonl. **Overwrite** source files with fixed code. |

**IMPASSE diagnosis (FAILED terminal state)**

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

---

### LEARNINGS.jsonl Consumption — The Critical Blocker

**Problem:** `read_learnings()` returns raw JSON. The planner model sees:

```json
{"iteration": 3, "root_cause": "missing import for pytest", "fix": "added import", ...}
{"iteration": 4, "root_cause": "TypeError on None input", "fix": "added None guard", ...}
```

This is hard for an LLM to parse usefully. The model has to mentally extract root_cause and fix from JSON, correlate across entries, and identify patterns — all in a single forward pass.

**Solution: Structured text summary instead of raw JSON.**

Replace `read_learnings()` output format with a human-readable summary that the planner can consume directly:

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

This gives the planner: (a) recurring patterns via Counter, (b) chronological history via bullets, (c) fix/learning per entry. No JSON parsing required.

**Code change:** Replace `read_learnings(run.sdlc_dir)` call at line 1174 with `read_learnings_formatted(run.sdlc_dir)`. Keep `read_learnings()` for internal use (repeated_root_cause, impasse diagnosis).

---

### GAPS.md Lifecycle

**Problem:** GAPS currently exists only in-memory and in ITERATION_STATE.json. The proposal adds GAPS.md as a file, but the lifecycle is unspecified.

**Design:**

| Event | GAPS.md action |
|---|---|
| First run (no prior GAPS) | File doesn't exist. PLAN phase skips it. |
| VERIFYING returns GAPS | **Overwrite** GAPS.md with structured gap analysis. Include iteration number and timestamp in header. |
| VERIFYING returns SATISFIED | **Do not delete** GAPS.md. It documents what was wrong and how it was fixed — valuable for post-mortem. |
| Next PLAN phase | **Read** GAPS.md if it exists. The planner sees the most recent gap analysis. |
| GAPS.md grows too large | Not a concern — it's overwritten each time, so it's always exactly one iteration's gaps (~500-2000 chars). |

**Why overwrite, not append:** GAPS.md represents the CURRENT gap state. When the planner addresses gaps and the verifier finds new ones, the old gaps are resolved. Appending would create confusion about which gaps are still open. The iteration history is preserved in LEARNINGS.jsonl and ITERATION_STATE.json.

---

### Resume Consistency

**Problem:** If ITERATION_STATE.json says iteration 5 but LEARNINGS.jsonl has 8 entries (from a run that crashed after appending learnings but before saving state), which wins?

**Design: ITERATION_STATE.json is authoritative. LEARNINGS.jsonl is advisory.**

On resume:
1. Load ITERATION_STATE.json → restore iteration, stagnation counters, prev_gaps, last_plan
2. LEARNINGS.jsonl is read fresh each PLAN phase — it always reflects ground truth
3. If LEARNINGS.jsonl has more entries than the iteration count suggests, that's fine — the planner sees all of them
4. If PLAN.md exists but ITERATION_STATE.json says state=INIT, the PLAN.md is from a previous run — it will be overwritten
5. If GAPS.md exists but run.prev_gaps is empty, the GAPS.md is from a previous run — the planner will read it and it may or may not still be relevant

**No reconciliation needed.** The checkpoint is the source of truth for state machine position. The .sdlc/ files are the source of truth for content. They can disagree without causing corruption — the worst case is the planner sees slightly stale gap/learning data, which is harmless.

**One edge case to handle:** If ITERATION_STATE.json is corrupt/missing but .sdlc/ files exist, treat as fresh start. The files will be overwritten. This is already the behavior — `load_state()` returns `{}` on JSONDecodeError.

---

### Fallback Design: "Model Didn't Read the File"

**Problem:** The planner prompt says "read LEARNINGS.jsonl" but the model might ignore it. No detection or fallback exists.

**Design: Lightweight heuristic detection, not enforcement.**

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

This is a diagnostic, not a gate. The pipeline continues. If the plan is bad, tests will fail and the debug loop will catch it. The warning helps with post-mortem: "did the model ignore the file, or was the file irrelevant?"

---

### Summary of Code Changes in sdlc_state.py

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

**Total: ~60 lines of new code, 8 lines of modifications. No new dependencies. All backwards-compatible — existing behavior unchanged when files are missing.**