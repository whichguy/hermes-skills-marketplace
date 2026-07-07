# Plan → Review → Implement → Quality Review — Devloop Learnings System (2026-07-05)

Real run of Pattern 9: the user asked to "plan it out, get advisor feedback,
then implement" for the N1/N2/N3 devloop learnings system fixes, then
"quality review changes" after implementation.

## Context

After commit `4d0c6f1`, rich learnings fields flow into both `LEARNINGS.jsonl`
(bridge-level) and `LESSONS.jsonl` (project-local). But the consolidator only
reads `LEARNINGS.jsonl` — project-local learnings are written but never read
back. Same class of gap as P9 (fixed on write side, still broken on read side).

Additionally, the P9 fix introduced a third extraction point, making dedup
coupling more fragile.

## Phase 1 — The Plan (N1/N2/N3)

### N1: Consolidator reads LESSONS.jsonl (cross-project learning)

- `dispatch.py:_git_history_learnings` only scans `LEARNINGS.jsonl`
- Fix: read `target_dir/.devloop/LESSONS.jsonl` directly, merge entries
- Concerns: discovery, volume, schema mismatch
- Effort: ~30-45 min

### N2: Eliminate triple-extraction risk

- After P9, failure conditions extracted in 3 places (bridge, project bridge path, project direct path)
- Fix: extract ONCE in bridge, store in `devloop_result.failure_conditions`, project reads directly
- Effort: ~20-30 min

### N3: Clean up duplicate import

- `project.py:323` and `project.py:337` both do `import devloop_bridge as _br`
- Fix: hoist to single import at top of block
- Effort: ~2 min

### Implementation Order

N3 → N2 → N1 → tests → full suite

## Phase 2 — Advisor Review

### Dispatch Plan

| # | Seat | Model | Toolsets | Est. time |
|---|---|---|---|---|
| 1 | Reasoner | deepseek-v4-pro:cloud | file, terminal | ~2-4 min |
| 2 | Coder | kimi-k2.7-code:cloud | file, terminal | ~1-3 min |

**Synthesis:** GLM-5.2 (dispatched after both land)

### Review Prompt

Advisors were asked to:
1. Verify plan assumptions against actual source code
2. Identify issues, risks, or better approaches
3. Confirm implementation order
4. For N1: is the discovery approach sound?
5. For N2: is changing devloop_result shape the right approach?

### Results

| Seat | Model | Time | Key Finding |
|---|---|---|---|
| Reasoner | deepseek-v4-pro | 133.5s | Plan is sound; N1 discovery needs configurable root |
| Coder | kimi-k2.7-code | 73.3s | Agrees with DeepSeek; N2 approach is correct |

**Synthesis:** GLM-5.2 landed (37.5s, 7.6K chars). Key refinements:
- Drop glob discovery for N1 → direct `target_dir/.devloop/LESSONS.jsonl` read
- Drop source tagging (YAGNI)
- `_mechanical_learnings_fallback` gets LESSONS content via merged journal
- Mirror rich fields in `failure_result` (test would break otherwise)
- Update consolidator prompt text to mention both journal sources
- `os.path.isfile` guard for fresh worktrees
- N2 before N3 order (N2's restructure eliminates the duplicate import naturally)

## Phase 3 — Implementation (completed 2026-07-05)

### N2 — Eliminate triple-extraction risk

- `_append_run_learning` now RETURNS the extracted rich fields dict
- `_run` captures the return and exposes `learnings_text`/`references`/`failure_conditions` directly in `devloop_result`
- `project.py` consumes `devloop_result` rich fields directly (no re-extraction)
- `failure_result` mirrors the new keys (`test_failure_result_shape_matches_run_shape` passes)
- Only the direct runner path still synthesizes (one extraction point, not three)
- Tests: 445 passed after N2+N3

### N3 — Clean up duplicate import

- Single `import devloop_bridge` at top of synthesis block (was duplicate in if/else)
- Naturally resolved by N2's restructure

### N1 — Consolidator reads LESSONS.jsonl

- `dispatch.py:_git_history_learnings` now reads `target_dir/.devloop/LESSONS.jsonl` in addition to `LEARNINGS.jsonl`, with same last-20 cap
- Project-local learnings (now rich after P9) reach the planner's git history context
- Consolidator prompt updated to mention both journal sources
- Guarded with `os.path.isfile` (may not exist on fresh worktree)
- Tests: 445 passed after N1

### New Tests

- `test_consolidator_reads_project_lessons_jsonl` — verifies LESSONS.jsonl content appears in consolidator output
- `test_devloop_result_has_rich_fields` — verifies `devloop_result` has `learnings_text`/`references`/`failure_conditions` keys, and `failure_result` mirrors them

### Final

- **Commit:** `4da32ee` — 4 files changed, +191/-28 lines
- **Tests:** 445 → 447 (2 new)
- **Pushed:** `main → main` on GitHub

## Phase 4 — Quality Review (completed 2026-07-05)

After implementation, the user asked to "quality review changes." A 2-seat
panel (DeepSeek + Kimi, GLM synthesis) reviewed commit `4da32ee` against the
actual source code.

### Dispatch Plan

| # | Seat | Model | Toolsets | Est. time |
|---|---|---|---|---|
| 1 | Reasoner | deepseek-v4-pro:cloud | file, terminal | ~2-4 min |
| 2 | Coder | kimi-k2.7-code:cloud | file, terminal | ~1-3 min |

**Synthesis:** GLM-5.2 (dispatched after both land)

### Results

| Seat | Model | Time | Key Finding |
|---|---|---|---|
| Reasoner | deepseek-v4-pro | 144.0s | N1/N2/N3 correct; flagged `_coerce_qa` unbundled change |
| Coder | kimi-k2.7-code | 114.7s | N1/N2/N3 correct; **found AVOID: double-prefix bug** at dispatch.py:489 |

**Synthesis:** GLM-5.2 (25.7s, 5.7K chars). Consensus:
- N1/N2/N3 implementation is correct
- **One real bug:** `AVOID:` double-prefix at `dispatch.py:451/490` — when a `failure_conditions` entry already starts with `AVOID:`, the rendering `f"    AVOID: {fc}"` produces `AVOID: AVOID: ...`
- Risk: Low — can ship, but fix the bug first

### Bug Fix

- **Commit:** `f511f95` — 2 files changed, +56/-2 lines
- **Fix:** Strip existing `AVOID:`/`DO NOT` prefix before re-prefixing in both LEARNINGS.jsonl and LESSONS.jsonl journal readers
- **Tests:** 447 → 448 (1 new: `test_avoid_double_prefix_stripped_in_consolidator`)
- **Pushed:** `main → main` on GitHub

## Key Learnings

1. **The user explicitly wants this 4-phase workflow** for non-trivial changes:
   plan → advisor review → implement → quality review. Don't skip Phase 2 or
   Phase 4 even if the plan looks obvious.
2. **Phase 4 caught a real bug** that both the controller and the
   implementation-phase advisors missed. A 2-seat quality review costs ~4
   minutes and catches bugs that would otherwise ship.
3. **Write the plan to a file** so advisors can read it from disk (avoids
   context-size limits and shell escaping issues).
4. **Dispatch advisors in parallel** via `terminal(background=true,
   notify_on_complete=true)` — each seat is independently tracked.
5. **Use foreground `subprocess.run()` for synthesis** — the synthesis model
   reads files from disk and writes a result. Background + polling wastes
   tool calls. Confirmed in both runs: GLM synthesis took 37.5s and 25.7s via
   foreground `subprocess.run()` — one tool call, no polling.
6. **The review prompt MUST include** the preamble: "Before identifying issues,
   verify each claim against the actual source files."
7. **Controller implements, not fixer** — for changes where the controller
   already has full context (plan + advisor feedback fresh in mind), the
   controller can implement directly rather than dispatching a fixer. This
   is faster (no dispatch overhead) and the controller can verify each step
   inline. Reserve fixer dispatch for when the controller lacks context or
   the changes are mechanical/boilerplate.
8. **Run tests after each step** — N2+N3 tested together (445), then N1 tested
   separately (445), then new tests added (447), then quality review fix (448).
   This isolates failures to the step that introduced them.
9. **Quality review is not the same as implementation review.** Phase 2 reviews
   the PLAN (does the approach make sense?). Phase 4 reviews the CODE (are
   there bugs?). Both are needed for non-trivial changes.
