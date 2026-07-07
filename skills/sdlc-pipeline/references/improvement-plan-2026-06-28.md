# Improvement Plan — 2026-06-28 Session Learnings

> Compiled from 3 rounds of advisor review (7 dispatches), 14 bug fixes, and
> the full v6 iterative state machine design session.

## Remaining Code Concerns (from 3-advisor quality review)

| # | Issue | Source | Severity | Status |
|---|---|---|---|---|
| **A1** | "GAPS" substring false positive — "No GAPS found, all SATISFIED" matches GAPS | GLM | MEDIUM | **Not yet fixed** — apply `\bGAPS\b` word-boundary (same pattern as Fix 11) |
| **A2** | FAILED `break` exits before full `save_state` — checkpoint has stale `state` field | GLM | MEDIUM | **Not yet fixed** — add `save_state` call before each FAILED `break` |
| **A3** | `repeated_root_cause` effective limit is ~6 (3 matches × 2 stagnation increments), not 3 | GLM | LOW | Document as intentional or reduce count to 2 |
| **A4** | `run_ruff` captures all stdout as "unfixable" — includes summary lines | GLM | LOW | Parse ruff output: only capture lines with error codes |
| **A5** | `read_learnings` loads entire file into memory — O(n) for 45+ iterations | GLM | LOW | Use `collections.deque(maxlen=window)` or tail-read |
| **A6** | `git_commit` "nothing to commit" → `rev-parse HEAD` returns previous commit hash | GLM | LOW | Check if commit actually happened before capturing hash |
| **A7** | `file_paths` always empty in learnings — orchestrator doesn't track changed files | Kimi | MEDIUM | Run `git diff --name-only HEAD~1` after implement |
| **A8** | Cascade stagnation conflates two signals (model failure vs test failure) | GLM | LOW | Future: separate `cascade_stagnation` counter |
| **A9** | Coder has `terminal` toolsets but told not to run lint — risk of coder running ruff | Kimi | LOW | Accept risk or use `file` only |

## Process Learnings

| # | Learning | Impact | Improvement |
|---|---|---|---|
| **P1** | `execute_code` has 5-minute hard timeout — advisors reading 4 files with 10 turns take 3-8 min | HIGH | Always use `terminal(background=true, notify_on_complete=true)` for advisor dispatches with `--max-turns >= 8` |
| **P2** | Built standalone `orchestrator.py` first, then had to delete and integrate into `sdlc_state.py` | MEDIUM | Start from existing infrastructure — read `sdlc_state.py` BEFORE designing |
| **P3** | Verification system repeatedly flagged changes as unverified despite passing scripts | MEDIUM | Use `tempfile.mkstemp(prefix="hermes-verify-", dir="/tmp")` consistently |
| **P4** | `prompt_model.py` had stale `DEFAULT_MAX_TURNS` import — broke all advisor dispatches | HIGH | After removing constants from `model_utils.py`, grep ALL consumers |
| **P5** | Advisor reviews are most valuable when they read actual source files (`-t file,terminal`), not just the plan document | HIGH | Always give advisors file-reading toolsets for code reviews |
| **P6** | 3-seat panel catches issues single models miss — GLM found 6 bugs DeepSeek+Kimi missed | HIGH | Always use 3-seat panel for quality reviews |
| **P7** | 4-round deliberation pattern formalized mid-session — now Pattern 6 in advisors skill | MEDIUM | Already captured in advisors SKILL.md |
| **P8** | Plan went through 7 versions — iterative plan refinement is the natural workflow | LOW | Already captured as Pattern 7 in advisors skill |

## Design Gaps (for v3.1-Parallel and beyond)

| # | Gap | Severity | Next Step |
|---|---|---|---|
| **D1** | Parallel dispatch not implemented — 6 HIGH gaps identified by advisors | HIGH | Dedicated design pass: patch-based isolation, structured PLANNING output, import-graph analysis, per-task timeout, concurrency-safe LEARNINGS, parallel DEBUGGING |
| **D2** | No code quality gate — loop optimizes for test pass count only | MEDIUM | Add lightweight quality check in VERIFYING or separate post-loop pass |
| **D3** | No live E2E test yet — all verification is structural, not behavioral | HIGH | Run `run_iterative_state_machine()` with a simple PROJECT.md |
| **D4** | `DiminishingReturnsTracker.should_stop()` has pre-existing `AttributeError` | MEDIUM | Fix v5 tracker or document as known v5 issue |
| **D5** | No CLI entry point for `run_iterative_state_machine()` | MEDIUM | Add thin CLI wrapper or integrate into `pipeline.py` |
| **D6** | `PROJECT.md` config parsing regex is fragile | LOW | Use section-based parser instead of `re.DOTALL` + first-newline-stop |

## Priority Order

**Immediate (before live E2E test):**
1. **A1** — `\bGAPS\b` word-boundary (same pattern as Fix 11, 1-line change)
2. **A2** — save_state before FAILED breaks (prevents stale checkpoint)
3. **D3** — run live E2E test (validates the whole thing works)

**Near-term (next session):**
4. **D5** — CLI entry point for `run_iterative_state_machine()`
5. **A7** — capture changed files via `git diff --name-only`
6. **D4** — fix `DiminishingReturnsTracker` AttributeError

**Medium-term (v3.1-Parallel design pass):**
7. **D1** — parallel dispatch (6 gaps to design)
8. **D2** — code quality gate
9. **A3-A6, A8-A9** — remaining low-severity concerns
