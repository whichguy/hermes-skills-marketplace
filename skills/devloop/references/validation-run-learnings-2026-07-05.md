# Devloop Deep Learnings — 2026-07-05 Validation Run

## Run Summary

**Request:** Build calendar-quick-add skill (same request that failed 5x before fixes)
**Result:** COMPLETE on first round, 0 rebuilds, 0 test redesigns
**Total wall-clock:** 659s (11.0 min)
**Implementation:** 280-line `nl_calendar.py`, 4 criteria all PASS

## Phase Timeline

| Phase | Duration | % of Total | Type |
|-------|----------|------------|------|
| Charter + ambiguity gate | ~0s | 0% | LLM (cached?) |
| Coverage + quality lint | ~0s | 0% | Deterministic |
| **Judge** (2 models × 4 criteria) | **56.5s** | **8.6%** | LLM (parallel) |
| **Implement** (coder writes code) | **226.0s** | **34.3%** | LLM (single model) |
| Evidence (pytest per criterion) | ~0.5s | 0.1% | Subprocess |
| Regression (full suite) | ~0.2s | 0% | Subprocess |
| **Overfit audit** (2 auditors × 4 criteria) | **357.6s** | **54.2%** | LLM (**SEQUENTIAL!**) |
| Commit scope audit | 18.0s | 2.7% | LLM |
| Grounding + terminal | ~0s | 0% | Deterministic |

## Key Learnings

### 1. The 3-Layer Defense Works — But It Wasn't Needed

The quality lint gate passed (ok=True) because the designer produced clean tests from the start. The prompt negative examples prevented bad patterns before they could form. The `_lit()` datetime fix meant rendered tests used real `datetime()` objects. The ANSWERS plumbing meant the designer saw "use real datetime objects" and complied.

**Learning:** The best gate is the one that never triggers. Prevention (prompt hardening) > detection (static gate) > correction (judge rejection + redesign). The 3 layers form a defense-in-depth where each layer is cheaper than the one below.

### 2. The Overfit Audit Is the New Bottleneck (54% of wall-clock)

The overfit audit took **357.6 seconds** — more than half the entire run. It runs 2 auditor models × 4 criteria = 8 model calls **sequentially**:

```python
for cid in ids:              # 4 criteria, sequential
    votes = []
    for aud in (overfit_a, overfit_b):  # 2 auditors, sequential
        votes.append(bool(aud(by_id[cid], inv.get(cid, []))))
```

Compare to the judges, which run **in parallel** via `ThreadPoolExecutor` (56.5s for the same 2×4=8 calls). The overfit audit is doing the same work but 6x slower because it's sequential.

**Learning:** The overfit audit should use the same `ThreadPoolExecutor` pattern as `dod_oracle.judge_assertions()`. This would cut 357s → ~60s, saving ~5 minutes per run.

### 3. Implementation Is 34% — Reasonable But Could Be Faster

The coder took 226s (3.8 min) to write 280 lines. This is a single LLM call with file tools. There's no parallelism opportunity here — the coder needs to see the full test spec and write one coherent implementation.

### 4. No Progress Output During the Run

The CLI produces **zero output** until the run completes. For 11 minutes, the user sees nothing. The trace is written to `trace.jsonl` but only accessible if you know where to look.

**Learning:** Devloop should emit progress to stderr during the run:
- `[charter] Decomposing request...` (0s)
- `[design] Generating tests for 4 criteria...` (0s)
- `[quality_lint] Checking rendered tests... ✅` (0s)
- `[judge] Asking 2 judges × 4 criteria... ✅ 4/4 trusted` (56s)
- `[implement] Coder writing implementation (attempt 0)...` (226s)
- `[evidence] Running 4 criteria tests... ✅ 4/4 pass` (0.5s)
- `[regression] Full suite... ✅ green` (0.2s)
- `[overfit_audit] Auditing 4 criteria × 2 models... ✅ no overfit` (357s)
- `[commit_scope] Classifying changed files... ✅ 1 deliverable` (18s)
- `[complete] Merged to master`

### 5. The Designer Produced Excellent Tests

The rendered tests are textbook quality:
- `test_c1`: Uses `date.today() + timedelta(days=1)` for relative dates — no hardcoded dates
- `test_c2`: Tests all 3 fallback layers (known_places, geocode_fn, pass-through)
- `test_c3`: Uses `MagicMock` with `assert_called_once()` and `call_args[0][0]` inspection — exactly the pattern judges want
- `test_c4`: Tests `main()` with DI (`gws_runner=mock_fn, geocode_fn=lambda`) — the exact pattern that failed 5x before

**Learning:** The prompt negative examples + ANSWERS plumbing + `_lit()` fix together produced the correct test patterns on the first try. No redesign was needed.

### 6. All 4 Criteria Were unit-tier — No Integration Tests

The charter decomposed the request into 4 unit-tier criteria. No integration-tier criteria were generated. This means the CLI was tested via direct function call, not subprocess. The judges accepted this, but it's a gap — the skill has a CLI entry point that was never tested as a real CLI.

**Learning:** The charter phase could benefit from automatically generating at least one integration-tier criterion for skills with CLI entry points. This would catch issues that unit tests miss (argparse behavior, exit codes, stderr output).

### 7. The Implementation Is Solid But Missing Known Places and SKILL.md

Devloop produced `nl_calendar.py` (280 lines) and the test file, but did NOT produce:
- `known_places.json` — mentioned in the request but not generated
- `SKILL.md` — mentioned in the request but not generated
- `test_calendar_quick_add.py` — devloop's own test file, not a user-facing test

The charter didn't decompose these as separate criteria, so devloop didn't build them.

**Learning:** The charter phase may be under-decomposing deliverables. "Include SKILL.md with Hermes frontmatter, known_places.json, and tests" should produce criteria for each artifact, not just the code logic.

## Parallelism Opportunities

### Opportunity 1: Parallelize the Overfit Audit (HIGH IMPACT, LOW RISK)

**Current:** 2 auditors × 4 criteria = 8 sequential calls = 357s
**Proposed:** Fire all 8 calls concurrently via ThreadPoolExecutor = ~60s
**Savings:** ~5 minutes (297s) per run
**Risk:** None — the judges already use this pattern successfully
**Implementation:** Replace the nested for-loop with `concurrent.futures.ThreadPoolExecutor`

### Opportunity 2: Run Commit Scope Audit Concurrently With Overfit (MEDIUM IMPACT, LOW RISK)

**Current:** Overfit audit (357s) → commit scope audit (18s) = 375s total
**Proposed:** Run both concurrently — they examine different things (overfit checks test quality, scope checks file classification). They share no state.
**Savings:** ~18s
**Risk:** Low — scope audit reads changed files, overfit reads test source + implementation. No write conflicts.
**Implementation:** Submit both to a ThreadPoolExecutor, wait for both

### Opportunity 3: Parallel Evidence Runs (LOW IMPACT, ALREADY FAST)

**Current:** 4 criteria run sequentially (0.2s each = 0.8s total)
**Proposed:** Run all 4 in parallel
**Savings:** ~0.6s
**Risk:** Low — each evidence run is an independent pytest subprocess
**Assessment:** Not worth the complexity — evidence is already <1s

### Opportunity 4: Parallel Charter + Environment Survey (MEDIUM IMPACT)

**Current:** Charter decomposition → environment survey → refine → advisor (all sequential)
**Proposed:** Run environment survey concurrently with charter draft (the survey doesn't depend on the charter)
**Savings:** ~10-20s
**Risk:** Low — survey just reads files, charter is LLM reasoning
**Assessment:** Marginal — charter phase was ~0s in this run (may have been cached)

### NOT Parallelizable

- **Implementation:** Single coherent code write, can't be split
- **Judges → Implementation:** Sequential dependency — can't implement until tests are trusted
- **Evidence → Stop check → Regression:** Sequential dependency chain
- **Quality lint → Judges:** Sequential — lint must pass before judges run

## Information Emission Improvements

### What Devloop Currently Emits

| Channel | When | What |
|---------|------|------|
| `trace.jsonl` | Every step | Structured JSON (step, ok, reason, timestamps) |
| `events.jsonl` | Finalize only | Commit/merge events |
| stdout | End only | Final summary (COMPLETE or HUMAN_REVIEW) |
| stderr | Never | Nothing |

### What's Missing

1. **No progress during the run** — 11 minutes of silence
2. **No estimated completion time** — user can't tell if it's 2min or 20min
3. **No phase timing in the output** — user doesn't know which phase was slow
4. **No "what devloop is doing right now"** — user can't tell if it's stuck or working
5. **No quality gate result in output** — user doesn't know if the lint gate passed
6. **No judge reasoning in output** — even with judge_reason text, it's only in the trace

### Proposed: stderr Progress Stream

```python
# In loop.py, add a lightweight progress emitter:
import sys

def _progress(step, detail="", ok=None):
    """One-line progress to stderr — doesn't interfere with stdout JSON output."""
    marker = "✅" if ok else "⏳" if ok is None else "❌"
    print(f"[devloop] {marker} {step}: {detail}", file=sys.stderr, flush=True)

# Usage:
_progress("charter", "decomposing request...")
_progress("design", f"generating tests for {len(crit)} criteria...")
_progress("quality_lint", "checking rendered tests", ok=quality_ok)
_progress("judge", f"2 judges × {len(ids)} criteria", ok=all_trusted)
_progress("implement", f"coder attempt {attempt}...")
_progress("evidence", f"{passed}/{total} criteria pass", ok=all_pass)
_progress("regression", "whole-suite", ok=reg_ok)
_progress("overfit_audit", f"auditing {len(ids)} criteria", ok=no_overfit)
_progress("complete", f"merged to {target}")
```

This would give the user real-time visibility without breaking the JSON output contract.