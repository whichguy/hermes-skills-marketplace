# Kanban SDLC Validation Plan — 3-Tier Test Strategy

Validates the `kanban-sdlc.sh` script and its guardrails without requiring a live model.
All Tier 1 and Tier 2 tests are deterministic — no model, no network, no side effects.

## Tier 1: Script Logic Tests (8 tests)

Deterministic tests of the script itself — no kanban board needed.

| # | Test | Command | Expected |
|---|---|---|---|
| 1.1 | Syntax check | `bash -n kanban-sdlc.sh` | Exit 0, no errors |
| 1.2 | Missing args | `./kanban-sdlc.sh` | Exit 1, shows Usage |
| 1.3 | Nonexistent dir | `./kanban-sdlc.sh /nonexistent "test"` | Exit 1, error message |
| 1.4 | Dry-run mode | `./kanban-sdlc.sh --dry-run /tmp/proj "test"` | Exit 0, prints "DRY RUN", no tasks created |
| 1.5 | Lock prevents overlap | Create lock file, run script | Exit 1, "already running" |
| 1.6 | Stale lock auto-removed | Create lock with mtime >1hr ago, run script | Proceeds, lock removed |
| 1.7 | Lock cleaned on exit | Run dry-run, check lock file | Lock file does not exist after |
| 1.8 | Pre-flight: missing skill | Run with `--skill nonexistent-skill` | Exit non-zero, error message |

## Tier 2: Guardrail Enforcement Tests (5 tests)

Tests that guardrails actually prevent the crash modes they're designed for.

| # | Test | Setup | Expected |
|---|---|---|---|
| 2.1 | create_task() validates JSON | Corrupt kanban CLI output | Script detects and exits non-zero |
| 2.2 | create_task() validates ID format | Task ID not matching `t_[a-f0-9]+` | Script detects and exits non-zero |
| 2.3 | Idempotency key prevents duplicates | Run same project+goal twice | Second run detects existing T1, skips |
| 2.4 | Watchdog: silent on healthy board | Run watchdog on board with no stuck tasks | Exit 0, no output |
| 2.5 | Watchdog: detects stuck running | Create task stuck >24h | Output includes task ID + reclaim hint |

## Tier 3: Live Demonstration Scenarios (3 demos)

Requires a running kanban board with worker + reviewer profiles.

### Demo 3.1: Happy-Path Chain
```bash
./kanban-sdlc.sh /opt/data/projects/kanban-test "add a power() method to Calculator"
```
**Expected:** All 5 phases complete without manual intervention. 14+ tests pass. All handoff files present.

### Demo 3.2: Block → Fix → Re-Review
1. Run chain with a deliberate bug in implementation
2. T4 reviewer blocks with findings
3. Create fix task, implement fix
4. Unblock T4 for re-review
5. T4 approves, T5 passes

**Expected:** Fix cycle works. No crash loop. T4 re-reviews successfully.

### Demo 3.3: Idempotent Rerun
1. Run Demo 3.1 successfully
2. Run the exact same command again
3. Script detects existing T1 (idempotency key), skips chain creation

**Expected:** Second run exits 0 with "chain already exists" message. No duplicate tasks.

## Board Cleanup

After each demo:
```bash
hermes kanban archive <task_id>  # Archive completed tasks
# Or for full reset:
hermes kanban list --status done | xargs -I{} hermes kanban archive {}
```

## Results Template

```
Demo: <name>
Date: <YYYY-MM-DD>
Tester: <name>

| Phase | Task ID | Status | Duration | Notes |
|---|---|---|---|---|
| T1 Research | | | | |
| T2 Tests | | | | |
| T3 Implement | | | | |
| T4 Review | | | | |
| T5 Final test | | | | |

Issues found:
- 

Pass/Fail: 
```
