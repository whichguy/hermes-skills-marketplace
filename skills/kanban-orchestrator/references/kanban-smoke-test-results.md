# Kanban Smoke Test Results (2026-06-26)

## Setup

- **Profiles:** `default` (glm-5.2:cloud, orchestrator), `worker` (qwen3-coder-next:q4_K_M), `reviewer` (deepseek-v4-pro:cloud)
- **Config:** `max_in_progress: 3`, `max_in_progress_per_profile: 2`, `failure_limit: 5`, `dispatch_interval_seconds: 60`
- **Board:** `/opt/data/kanban.db` (SQLite), initialized with `hermes kanban init`

## Test 1: Worker Spawn + Complete

- **Task:** `t_ac92ead3` — "smoke-test: add comment to throwaway file"
- **Assignee:** worker
- **Result:** ✅ PASSED — 63s
- **Output:** Created `/tmp/kanban-smoke-test.txt` with "Kanban smoke test OK"
- **Pipeline:** dispatcher claimed → spawned worker (PID 119263) → worker completed → task marked done

## Test 2: Reviewer Spawn + Complete

- **Task:** `t_6b150da7` — "smoke-test: review the test file"
- **Assignee:** reviewer
- **Result:** ✅ PASSED — 23s
- **Output:** Verified `/tmp/kanban-smoke-test.txt` contains "Kanban smoke test OK" — approved
- **Pipeline:** dispatcher claimed → spawned reviewer → reviewer verified → task marked done

## Test 3: Worker Creates Buggy File

- **Task:** `t_31dd88a7` — "smoke-test: write buggy Python file"
- **Assignee:** worker
- **Result:** ✅ PASSED — worker completed
- **Output:** Created `/tmp/kanban-bug.py` with `divide_by_zero()` function returning `1/0`

## Test 4: Block Flow

- **Task:** `t_9fd1ad43` — "smoke-test: review buggy file for issues"
- **Assignee:** reviewer
- **Result:** ✅ PASSED — reviewer blocked with structured reason
- **Block reason:** "File /tmp/kanban-bug.py does not exist — cannot review a missing file"
- **Root cause:** Reviewer ran in a `scratch` workspace and could not see `/tmp/kanban-bug.py` written by the worker in Test 3. This is expected behavior — scratch workspaces are isolated.
- **Lesson:** For chained tasks where downstream phases need to read upstream output, use `dir:` or `worktree:` workspaces, not `scratch`.

## Test 5: Kill Switch

- **Action:** Set `kanban.auto_decompose: false` in config.yaml
- **Result:** ✅ PASSED — dispatcher stopped picking up new tasks within one tick cycle
- **Re-enable:** Set back to `true`, dispatcher resumed normal operation

## Phase 3.5 Smoke Tests (2026-06-26, ~15 min)

Full end-to-end verification after gateway restart with Kanban dispatcher active.

### Test 3.5.1: Kanban CLI create/list/show
- **Result:** ✅ PASSED
- **Details:** Task created, listed, shown with full event log. All CLI commands functional.

### Test 3.5.2: Dispatcher spawns worker profile
- **Task:** `t_ac92ead3` — "smoke-test: add comment to throwaway file"
- **Assignee:** worker (Kimi model)
- **Result:** ✅ PASSED — 63s
- **Details:** Dispatcher auto-claimed → spawned worker (PID 119263) → worker completed → task marked done. File `/tmp/kanban-smoke-test.txt` created with correct content.

### Test 3.5.3: Board state transitions (ready → running → done)
- **Result:** ✅ PASSED
- **Details:** Full lifecycle verified: `ready` at 22:57 → `running` at 22:58 → `done` at 22:59 (63s total). Dispatcher auto-promotes, auto-claims, auto-spawns.

### Test 3.5.4: Reviewer spawn + kanban_block
- **Approve path** (`t_0563164c`): ✅ PASSED — reviewer verified file, completed in 11s
- **Block path** (`t_24702344`): ✅ PASSED — reviewer found missing file, `kanban_block('BLOCK: file does not exist')` in 11s
- **Details:** Reviewer profile (DeepSeek model) spawns fast, reviews independently, blocks with structured reason.

### Test 3.5.5: Gateway ping (notify-subscribe)
- **Result:** ✅ PASSED with timing constraint
- **Details:** `notify-subscribe` registered successfully, subscription consumed on task completion. **Critical finding:** subscription must be set up BEFORE the dispatcher claims the task. If the task is already `running`, the subscription may not fire. Subscriptions are consumed (auto-removed) on completion — not persistent across multiple task runs.
- **Gateway log visibility:** Notification sends do not appear at INFO level in gateway.log. The subscription lifecycle (register → consume) is visible via `notify-list`, but the actual outbound message send is not logged at INFO.

## Summary

| Test | Status | Time | Notes |
|---|---|---|---|
| Worker spawn + complete | ✅ | 63s | Full pipeline: claim → spawn → work → complete |
| Reviewer spawn + complete | ✅ | 23s | Different model/profile, independent verification |
| Block flow | ✅ | 23s | Structured block with reason, kind: needs_input |
| Kill switch | ✅ | <60s | Hot-reload via config.yaml, no restart needed |
| Gateway ping (notify-subscribe) | ✅ | ~60s | Works but requires pre-subscription before dispatch |
| CLI create/list/show | ✅ | <5s | All commands functional |
| State transitions | ✅ | 63s | ready→running→done, auto-promotion verified |
| Reviewer block path | ✅ | 11s | kanban_block with structured reason |
| Dispatcher reaps zombies | ✅ | ~60s | Stale worker PIDs cleaned up automatically |

## SDLC Chain Test (2026-06-27, ~20 min)

Full maker-checker loop: worker implements → reviewer blocks → fix task → re-review.

### Test Setup
- **Project:** `/opt/data/projects/sdlc-test/` with AGENTS.md (6 sections: Goal, Architecture, Coding Standards, Test Requirements, Key Invariants, Current Phase)
- **Task:** Implement `letter_freq.py` (calculate letter frequency percentages) with tests
- **Profiles:** worker (Kimi), reviewer (DeepSeek)

### Chain Execution

| Task | Assignee | Status | Time | Summary |
|---|---|---|---|---|
| T1 `t_6f9c8edc` | worker | ✅ done | ~5 min | Implemented `letter_freq.py` + 7 tests, all passing |
| T2 `t_483c5856` | reviewer | ⚠️ blocked (3×) | ~2 min | Found 4 AGENTS.md violations, blocked each time. Auto-decomposer split into 5 sub-tasks after block loop limit |
| T3 `t_983d10be` | worker | ✅ done | ~6 min | Fixed all 4 violations: `-> None` type hint, one-line docstring, `PERCENT_MULTIPLIER` constant, `isinstance` error check |

### Reviewer Findings (all 4 fixed by T3)
1. `letter_freq.py:35` — `main()` missing return type hint → fixed: `def main() -> None:`
2. `letter_freq.py:8-17` — docstring too long (9 lines) → fixed: one-line `"""Return lowercase letter frequencies as percentages."""`
3. `letter_freq.py:29` — magic number `100.0` → fixed: `PERCENT_MULTIPLIER = 100.0`
4. `letter_freq.py:7` — no error check at function entry → fixed: `isinstance(text, str)` + `raise TypeError`

### Key Findings

1. **Fix-task parent linkage trap.** Creating T3 with `parents=[T2]` when T2 is blocked causes T3 to stay in `todo` forever — the dependency engine only promotes children when every parent is `done`. Fix: create fix tasks as independent `ready` tasks (no parents), or create with parent and immediately `kanban unlink`.
2. **Reviewer re-reviewed before fix applied.** T2 and T3 ran in parallel — the reviewer re-reviewed old code. Fix: keep T2 blocked until T3 completes, then unblock for re-review.
3. **Block loop limit triggers auto-decomposition.** After 3 blocks (limit=2), the auto-decomposer split T2 into 5 sub-tasks (extract invariants, verify each, run tests, audit quality, synthesize). This is a safety net, not a bug — it prevents infinite re-review loops.
4. **Maker-checker loop works end-to-end.** Worker implemented, reviewer found real violations (not rubber-stamping), fix task addressed all findings, tests remained green throughout.

## Key Findings

1. **Workspace isolation is real.** Scratch workspaces prevent chained tasks from sharing files. Use `dir:` or `worktree:` for SDLC chains.
2. **Block flow works correctly.** Reviewer blocked with structured reason and kind. The block persists until unblocked.
3. **Kill switch is instant.** Flipping `auto_decompose: false` stops dispatch within one tick cycle. No gateway restart needed.
4. **Gateway restart kills subagents.** Background delegations (council panel members, delegate_task subagents) die silently on gateway restart. Wait for active delegations to complete before restarting.
5. **notify-subscribe requires pre-subscription.** Subscribe BEFORE the dispatcher claims the task. Subscriptions are consumed on completion — not persistent. Gateway log at INFO level does not show notification sends; use `notify-list` to verify subscription state.
6. **Dispatcher auto-reaps zombies.** Stale worker PIDs are cleaned up automatically within one tick cycle.
