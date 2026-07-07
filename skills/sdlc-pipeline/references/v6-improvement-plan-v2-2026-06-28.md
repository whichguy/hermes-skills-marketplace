# SDLC v6 Iterative State Machine — Improvement Plan v2

> Generated: 2026-06-28  
> Source: Learnings from session 2026-06-28, E2E testing (81 tests across 7 projects), advisor panels, optimization analysis  
> Key files: `sdlc_state.py` (1692 lines), `sdlc_worktree.py` (432 lines), `sdlc.py` (2153 lines)

---

## Already Completed (Session 2026-06-28)

These are done — do NOT re-plan them:

| ID | What |
|----|------|
| v6 state machine built | New iterative loop with 4 states added (LINT_FIX, VERIFYING, FAILED, HUMAN_REVIEW) |
| 14 advisor fixes applied | F1-F14: checkpoint/resume, stagnation counters, verdict order, dead code removal, thinking/max_turns inversion |
| 10 output improvements (O1-O10) | Iteration summaries, model previews, wall-clock remaining time, structured GAPS, commit hashes |
| BUG1 fixed | Iteration counter off-by-one — `run.iteration += 1` moved to PLAN entry point |
| BUG2 fixed | Env var parsing with try/except for `SDLC_MAX_ITER`, `SDLC_WALL_CLOCK` |
| BUG3 fixed | "Reached maximum iterations" warning filtered from model previews |
| max_turns=None | All 15 dispatch sites now inherit Hermes default (120) instead of hardcoded values |
| thinking=None | All 13 dispatch sites now inherit Hermes default (True/False) |
| PHASE_EVALUATORS dead code removed | Unused evaluator functions cleaned up from v5 code path |
| git init fix | Worktree `git init` called before model dispatches |
| cwd parameter | `cwd=worktree` set on all `dispatch_single()` calls for terminal/file tool paths |
| debug code extraction | `extract_python_code()` writes fixed code to disk after cascade succeeds |
| E402 lint fix | `--ignore E402` in `run_ruff()` + summary line filtering |
| negated GAPS detection | "No GAPS found" patterns now correctly return SATISFIED verdict |

---

## Improvement Items

### P1 — Negated GAPS regex still misses "found no gaps" / "did not find gaps" patterns  
- **Category:** CORRECTNESS  
- **Priority:** P0 (critical)  
- **Problem:** The negated-GAPS check at line 944 only matches `NO\s+GAPS` with a single regex. It misses patterns like "no gaps found", "did not find gaps", "free of gaps", "absent any gaps". A verifier saying "I found no gaps in the implementation" incorrectly classifies as GAPS.  
- **Proposed solution:** Replace single regex with sentence-level negation analysis:
  ```python
  # Line 944 — replace:
  gaps_negated = bool(re.search(r'\b(?:NO|NONE|WITHOUT|ZERO)\s+GAPS\b', upper))
  # With:
  def _has_negated_gaps(text: str) -> bool:
      """Check if ALL gap mentions are negated."""
      sentences = re.split(r'[.!?]+', text)
      gap_sentences = [s for s in sentences if re.search(r'\bGAPS?\b', s, re.IGNORECASE)]
      if not gap_sentences:
          return False
      negation_words = r'(?i)\b(?:no|none|without|zero|not|never|free of|absent|did not find)\b'
      return all(re.search(negation_words, s) for s in gap_sentences)
  ```
- **Effort:** S (10 lines including new function)  
- **Dependencies:** None  
- **Risk:** Low — more conservative detection means only truly negated GAPS get SATISFIED verdict  

### P2 — repeated_root_cause() effective limit is ~6 not 3 (double-counting bug)  
- **Category:** CORRECTNESS  
- **Priority:** P1 (high)  
- **Problem:** `repeated_root_cause()` checks if root_cause appeared >= count times. Caller at line 1404 increments `root_cause_stagnation` each time it returns True, then check at 1444 fires when stagnation >= limit (3). Result: root cause appears 5 times before termination, not 3. User sees same error 5 iterations before loop stops.  
- **Proposed solution:** Jump stagnation to limit on first repeat instead of incrementing:
  ```python
  # Line 1406-1409 — replace:
  if is_repeated:
      run.root_cause_stagnation += 1
  else:
      run.root_cause_stagnation = 0
  # With:
  if is_repeated:
      run.root_cause_stagnation = stagnation_limit  # Jump to limit
  else:
      run.root_cause_stagnation = 0
  ```
- **Effort:** S (2 lines)  
- **Dependencies:** None  
- **Risk:** Low — matches documented behavior (3 occurrences == stop signal)

### P3 — Cascade failure increments test_stagnation, conflating two signals  
- **Category:** CORRECTNESS  
- **Priority:** P1 (high)  
- **Problem:** At line 1457, when `debug_cascade()` fails completely, code increments `run.test_stagnation`. But test_stagnation is also incremented at line 1316 when tests don't improve. These are different: model outage vs fix failure. Result: misleading "test stagnation" message when it's actually a debugger model problem.  
- **Proposed solution:** Add separate `cascade_stagnation` counter:
  ```python
  # In SDLCRun dataclass (line ~136):
  cascade_stagnation: int = 0
  
  # Line 1457 — replace run.test_stagnation += 1 with:
  run.cascade_stagnation += 1
  if run.cascade_stagnation >= stagnation_limit:
      _emit(f"  ❌ cascade failure stagnation ({run.cascade_stagnation}/{stagnation_limit})")
  
  # Also update save_state() at line ~693 to persist cascade_stagnation
  ```
- **Effort:** S (10 lines across load/save)  
- **Dependencies:** None  
- **Risk:** Low — separate counters improve diagnostics; existing test_stagnation unaffected

### P4 — DiminishingReturnsTracker missing self.max_iterations attribute (D4)  
- **Category:** CORRECTNESS  
- **Priority:** P2 (medium)  
- **Problem:** `DiminishingReturnsTracker.__init__()` doesn't set `self.max_iterations`, but v5 code path calls `tracker.should_stop()` which may reference it. This causes AttributeError in rare edge cases where v5 path is invoked.  
- **Proposed solution:** Add max_iterations parameter to `__init__`:
  ```python
  # Line 182 — replace:
  def __init__(self, min_delta: float = 0.05, max_repeats: int = 2):
      self.scores: List[float] = []
      self.feedbacks: List[str] = []
      self.min_delta = min_delta
      self.max_repeats = max_repeats
  
  # With:
  def __init__(self, min_delta: float = 0.05, max_repeats: int = 2, max_iterations: int = MAX_ITERATIONS_DEFAULT_V6):
      self.scores: List[float] = []
      self.feedbacks: List[str] = []
      self.min_delta = min_delta
      self.max_repeats = max_repeats
      self.max_iterations = max_iterations  # NEW
  ```
- **Effort:** S (1 line added)  
- **Dependencies:** None  
- **Risk:** Low — missing attribute is a latent bug; adding it can't break anything

### P5 — Performance: Identify which model calls could be skipped/cached (98% wall-clock)  
- **Category:** PERFORMANCE  
- **Priority:** P1 (high)  
- **Problem:** 98% of wall-clock is spent in model dispatches. Analysis shows: PLAN (~25s), VERIFYING (~18s). These are candidates for skipping when confidence is high.  
- **Proposed solution:** Two fast-path optimizations:
  ```python
  # P5a — Skip PLAN on iteration 1 (no context yet):
  if run.iteration == 1 and not read_learnings(run.sdlc_dir) and not run.prev_gaps:
      run.last_plan = f"## Initial Plan\nPROJECT.md implies: {project_md[:300]}"
      state = SDLCState.IMPLEMENT
      continue  # Skip dispatch
  
  # P5b — Fast-verify when all tests pass with no regressions:
  if test_result["passed"] and len(regressions) == 0:
      _emit("  ✅ fast-verify: all tests pass, no regressions")
      state = SDLCState.COMPLETE
      continue
  ```
- **Effort:** S (15 lines across two optimizations)  
- **Dependencies:** None  
- **Risk:** Low-Medium — only skip on iteration 1 or when conditions are clearly safe

### P6 — CLI entry point for run_iterative_state_machine() (D5)  
- **Category:** ARCHITECTURE  
- **Priority:** P2 (medium)  
- **Problem:** `run_iterative_state_machine()` can only be called from Python code. No way to invoke it from command line without wrapper script.  
- **Proposed solution:** Add argparse CLI at bottom of sdlc_state.py:
  ```python
  if __name__ == "__main__":
      import argparse
      ap = argparse.ArgumentParser(description="SDLC v6 Iterative State Machine")
      ap.add_argument("--message", required=True)
      ap.add_argument("--worktree", required=True)
      ap.add_argument("--project-md", default="")
      ap.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS_DEFAULT_V6)
      ap.add_argument("--wall-clock", type=int, default=WALL_CLOCK_DEFAULT_V6)
      args = ap.parse_args()
      
      project_md = open(args.project_md).read() if args.project_md and os.path.exists(args.project_md) else ""
      run = run_iterative_state_machine(
          message=args.message,
          worktree=args.worktree,
          project_md=project_md,
          max_iterations=args.max_iterations,
          wall_clock_budget=args.wall_clock,
      )
  ```
- **Effort:** S (20 lines)  
- **Dependencies:** None  
- **Risk:** Low — thin wrapper, no logic changes

### P7 — file_paths via git diff instead of scanning (A7)  
- **Category:** ARCHITECTURE  
- **Priority:** P2 (medium)  
- **Problem:** `append_learning()` at line 1431 passes empty list for `file_paths`. No way to trace which files changed per iteration.  
- **Proposed solution:** Capture git diff after IMPLEMENT and DEBUG phases:
  ```python
  # After IMPLEMENT (line ~1278):
  try:
      r = subprocess.run(["git", "diff", "--name-only", "HEAD"], 
                         cwd=worktree, capture_output=True, text=True, timeout=5)
      if r.returncode == 0:
          run.last_changed_files = [f for f in r.stdout.strip().split('\n') if f]
  except Exception:
      pass
  
  # Pass to append_learning() at line ~1431
  file_paths=run.last_changed_files or [],
  ```
- **Effort:** S (8 lines)  
- **Dependencies:** None  
- **Risk:** Low — read-only git operation, fallback handles edge cases

### P8 — read_learnings O(n) memory growth (A5)  
- **Category:** ARCHITECTURE  
- **Priority:** P3 (low)  
- **Problem:** `read_learnings()` at line 709 reads entire file into memory, parses all JSON entries, then slices last N. For 45 iterations it's ~9KB (negligible), but for large learnings or frequent calls this could grow.  
- **Proposed solution:** Use `tail -n` for constant-memory reads:
  ```python
  def read_learnings(sdlc_dir: str, window: int = LEARNINGS_WINDOW) -> str:
      # ...
      try:
          r = subprocess.run(["tail", "-n", str(window), path],
                             capture_output=True, text=True, timeout=5)
          lines = r.stdout.strip().split('\n') if r.stdout.strip() else []
      except Exception:
          # Fallback to full read for edge cases
          with open(path) as f:
              lines = f.readlines()[-window:]
  ```
- **Effort:** S (10 lines)  
- **Dependencies:** None  
- **Risk:** Low — fallback handles systems without `tail`

### P9 — run_ruff stdout capture needs line filtering (A4)  
- **Category:** ROBUSTNESS  
- **Priority:** P2 (medium)  
- **Problem:** At line 866-867, unfixable lint lines are captured but summary lines like "Found 3 errors" also included. This pollutes the unfixable list shown to user.  
- **Proposed solution:** Filter out summary/stats lines:
  ```python
  # Line 866 — replace:
  unfixable = [line for line in r.stdout.splitlines()
               if line.strip() and not line.startswith("Found")]
  # With stricter filter:
  unfixable = [line for line in r.stdout.splitlines()
               if line.strip() 
               and "error" in line.lower()
               and not any(x in line for x in ("summary", "warning", "Found"))]
  ```
- **Effort:** S (1 line extended)  
- **Dependencies:** None  
- **Risk:** Low — filtering makes output cleaner

### P10 — Per-task timeout in parallel dispatch architecture  
- **Category:** ARCHITECTURE  
- **Priority:** P1 (high)  
- **Problem:** When parallel dispatch is implemented (P12), all tasks share the same timeout. A slow task blocks others unnecessarily.  
- **Proposed solution:** Add `task_timeout` parameter to task dispatch scheduler:
  ```python
  # In parallel dispatch helper:
  def run_parallel_tasks(tasks: List[dict], global_timeout: int, per_task_timeout: Optional[int] = None):
      results = []
      with concurrent.futures.ThreadPoolExecutor() as executor:
          futures = {}
          for t in tasks:
              kwargs = {"timeout": min(per_task_timeout, remaining_time()) if per_task_timeout else timeout}
              futures[executor.submit(dispatch_single, **t.get("kwargs", {}), **kwargs)] = t
          # ...
  ```
- **Effort:** M (40 lines)  
- **Dependencies:** Parallel dispatch implementation (P12) — deferred to v3.1 design pass  

### P11 — Patch-based isolation for parallel tasks  
- **Category:** ARCHITECTURE  
- **Priority:** P2 (medium)  
- **Problem:** Without isolation, parallel tasks writing same files cause race conditions and merge conflicts.  
- **Proposed solution:** Each task gets temp git branch or worktree; patches merged sequentially at end:
  ```python
  # For each parallel task:
  subprocess.run(["git", "checkout", "-b", f"task-{t['id']}"], cwd=worktree)
  result = dispatch_single(...)
  if result.get("content"):
      apply_patch(result["content"], branch=f"task-{t['id']}")
  ```
- **Effort:** L (100+ lines, needs design doc)  
- **Dependencies:** Parallel dispatch (P12)  

### P12 — Structured PLANNING output format  
- **Category:** ARCHITECTURE  
- **Priority:** P2 (medium)  
- **Problem:** Planner outputs free-text instructions. No way to parse task list, dependencies, or parallelism hints for v3.1 parallel dispatch.  
- **Proposed solution:** Add JSON schema for planner output:
  ```yaml
  # Planner MUST produce:
  {
    "tasks": [
      {"id": 1, "type": "file_write", "path": "src/foo.py", "depends_on": []},
      {"id": 2, "type": "test_write", "path": "tests/test_foo.py", "depends_on": [1]},
      {"id": 3, "type": "parallel_group", "tasks": [4,5], "depends_on": [2]}
    ]
  }
  ```
- **Effort:** M (60 lines: schema, parser, migration)  
- **Dependencies:** None  

### P13 — Import-graph analysis for better test coverage  
- **Category:** ARCHITECTURE  
- **Priority:** P3 (low)  
- **Problem:** AI-generated tests may miss import dependencies between modules. Result: tests pass in isolation but fail together.  
- **Proposed solution:** Build import graph during IMPLEMENT phase, feed to test-planner:
  ```python
  # After IMPLEMENT:
  import_graph = parse_imports(worktree)
  ctx = f"## Import Dependencies\n{import_graph}\n"
  run.test_result = dispatch_single(..., context=ctx + "...")
  ```
- **Effort:** M (50 lines: parser + integration)  
- **Dependencies:** None  

### P14 — No structured logging (events.jsonl)  
- **Category:** OBSERVABILITY  
- **Priority:** P2 (medium)  
- **Problem:** All output uses `_emit()` print-to-stderr. No timestamps, no log levels, no queryable history for debugging.  
- **Proposed solution:** Add `_log_event()` that writes JSON to `.sdlc/events.jsonl`:
  ```python
  def _log_event(run: SDLCRun, event: str, **kwargs):
      if not run.sdlc_dir:
          return
      entry = {
          "ts": time.time(),
          "iteration": run.iteration,
          "state": state.name,
          "elapsed": time.time() - run.start_time,
          **kwargs,
      }
      with open(os.path.join(run.sdlc_dir, "events.jsonl"), "a") as f:
          f.write(json.dumps(entry) + "\n")
  ```
- **Effort:** M (30 lines + 20 call sites)  
- **Dependencies:** None  

### P15 — No status endpoint for long-running runs  
- **Category:** OBSERVABILITY  
- **Priority:** P3 (low)  
- **Problem:** During 45-iteration, 30+ minute runs, no way to check status without watching terminal. Closing terminal loses status.  
- **Proposed solution:** Write STATUS.json with iteration state:
  ```python
  # After save_state():
  status = {
      "iteration": run.iteration,
      "state": state.name,
      "tests_passing": run.prev_pass_count,
      "stagnation": {"test": run.test_stagnation, ...},
      "elapsed": elapsed,
  }
  with open(os.path.join(run.sdlc_dir, "STATUS.json"), "w") as f:
      json.dump(status, f)
  ```
- **Effort:** S (15 lines)  
- **Dependencies:** None  

### P16 — Model/provider constants hardcoded  
- **Category:** ARCHITECTURE  
- **Priority:** P2 (medium)  
- **Problem:** Lines 597-600 hardcode model names. Can't override for testing or different environments without editing source.  
- **Proposed solution:** Read from environment variables:
  ```python
  # Line 597-600 — replace:
  MODEL_PLANNER_V6 = "glm-5.2:cloud"
  # With:
  MODEL_PLANNER_V6 = os.environ.get("SDLC_MODEL_PLANNER", "glm-5.2:cloud")
  # Same for CODER, VERIFIER, PROVIDER
  ```
- **Effort:** S (4 lines)  
- **Dependencies:** None  

### P17 — LINT_FIX max retries (3) too few — add HUMAN_REVIEW fallback  
- **Category:** ROBUSTNESS  
- **Priority:** P2 (medium)  
- **Problem:** At line 1290, after MAX_LINT_RETRIES (3), pipeline fails even if tests pass. E2E Test 1 hit this: all 10/10 tests passed but E402 blocked progress.  
- **Proposed solution:** When lint unfixable but tests pass → HUMAN_REVIEW:
  ```python
  # Line 1290-1293 — replace with:
  if run.lint_retry_count >= MAX_LINT_RETRIES:
      test_check = run_tests_in_worktree(worktree)
      if test_check["passed"] and test_check["pass_count"] > 0:
          _emit(f"  ⚠️ lint unfixable but {test_check['pass_count']} tests pass — HUMAN_REVIEW")
          state = SDLCState.HUMAN_REVIEW
          continue
      else:
          break  # Tests failing too, really fail
  ```
- **Effort:** S (10 lines)  
- **Dependencies:** None  

### P18 — Enhanced debug cascade test output context  
- **Category:** OBSERVABILITY  
- **Priority:** P2 (medium)  
- **Problem:** At line 1342-1354, debugger receives truncated error_output (stderr + stdout limited). Assertion messages and tracebacks may be cut off.  
- **Proposed solution:** Pass structured failure info instead of raw output:
  ```python
  # Line 1342-1354 — replace with:
  failing_tests = run.last_test_result.get("failing", [])
  test_names = "\n".join([f"- {t}" for t in failing_tests[:10]])
  details = run.last_test_result.get("stdout", "")[-5000:]  # Last 5KB of output
  error_context = f"## Failing Tests ({len(failing_tests)})\n{test_names}\n\n{details}"
  
  debug_cascade(..., error_feedback=error_context)
  ```
- **Effort:** M (15 lines)  
- **Dependencies:** None  

---

## Recommended Next Sprint

Top 5 items to tackle first — all S-effort, low-risk, independent:

| Order | ID | Title | Category | Priority | Rationale |
|-------|----|-------|----------|----------|-----------|
| 1 | P1 | Negated GAPS regex misses common patterns | CORRECTNESS | P0 | Critical bug — "no gaps found" still returns GAPS verdict. One function, ~10 lines |
| 2 | P2 | repeated_root_cause effective limit is ~6 not 3 | CORRECTNESS | P1 | User sees same root cause 5x instead of 3x before termination. 2-line fix |
| 3 | P3 | Cascade failure increments test_stagnation (conflation) | CORRECTNESS | P1 | Misleading diagnostics: "test stagnation" when it's a model outage. New counter needed |
| 4 | P5a + P5b | Skip PLAN on iteration 1 + fast-verify when all tests pass | PERFORMANCE | P1 | Combined savings: ~43s per project (44% wall-clock reduction). Two simple if-checks |
| 5 | P7 | file_paths via git diff instead of empty list | ARCHITECTURE | P2 | Enables traceability from learnings to changed files. 8 lines, no risk |

**Total sprint effort:** ~35 lines across 5 small changes  
**Risk profile:** All low — no dependencies between items, all backwards-compatible

---

## Summary Table

| ID | Title | Category | Priority | Effort |
|----|-------|----------|----------|--------|
| P1 | Negated GAPS regex misses patterns | CORRECTNESS | P0 | S |
| P2 | repeated_root_cause limit ~6 not 3 | CORRECTNESS | P1 | S |
| P3 | Cascade conflation with test_stagnation | CORRECTNESS | P1 | S |
| P4 | DiminishingReturnsTracker missing max_iterations | CORRECTNESS | P2 | S |
| P5 | Identify model calls for skipping/caching | PERFORMANCE | P1 | S |
| P6 | CLI entry point for run_iterative_state_machine() | ARCHITECTURE | P2 | S |
| P7 | file_paths via git diff | ARCHITECTURE | P2 | S |
| P8 | read_learnings constant-memory reads | ARCHITECTURE | P3 | S |
| P9 | run_ruff summary line filtering | ROBUSTNESS | P2 | S |
| P10 | Per-task timeout in parallel dispatch | ARCHITECTURE | P1 | M |
| P11 | Patch-based isolation for parallel tasks | ARCHITECTURE | P2 | L |
| P12 | Structured PLANNING output format | ARCHITECTURE | P2 | M |
| P13 | Import-graph analysis for tests | ARCHITECTURE | P3 | M |
| P14 | Structured logging (events.jsonl) | OBSERVABILITY | P2 | M |
| P15 | Status endpoint for long-running runs | OBSERVABILITY | P3 | S |
| P16 | Model/provider constants from env var | ARCHITECTURE | P2 | S |
| P17 | LINT_FIX → HUMAN_REVIEW fallback | ROBUSTNESS | P2 | S |
| P18 | Enhanced debug cascade test output | OBSERVABILITY | P2 | M |

**Total: 18 items.** 10 S-effort, 5 M-effort, 3 L-effort.  
**Priority breakdown:** 1 P0, 4 P1, 9 P2, 4 P3

---

*Generated by Hermes Agent on 2026-06-28*
