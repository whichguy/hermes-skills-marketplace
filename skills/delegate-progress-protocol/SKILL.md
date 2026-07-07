---
name: delegate-progress-protocol
description: >
  Mandatory controller behavior when dispatching delegate_task subagents.
  Three-phase protocol: (1) pre-dispatch plan shown to user, (2) incremental
  status updates every 2-3 minutes during execution, (3) structured completion
  summary. Applies to ALL delegate_task usage — development, research, code
  review, email processing, any parallel work.
version: 1.0.0
author: agent
metadata:
  hermes:
    tags: [delegation, subagent, status, progress, protocol, controller-behavior]
    related_skills: [subagent-driven-development, multi-model-dev-pipeline, kanban-orchestrator]
    config:
    - key: delegate-progress-protocol.enabled
      description: Enable the three-phase delegation progress protocol
      default: true
      prompt: Enable delegate-progress-protocol skill?
    category: autonomous-ai-agents
---

# Delegate Progress Protocol

## Purpose

Every `delegate_task` dispatch must follow this three-phase protocol. The
controller (you) is responsible for keeping the user informed throughout — the
user should never have to ask "Status?".

## Phase 1 — Pre-Dispatch Plan

**Before** calling `delegate_task`, present a brief dispatch plan to the user.

### Format

```
## 📋 Dispatch Plan

| # | Subagent | Goal | Toolsets | Model | Est. time |
|---|---|---|---|---|---|
| 1 | researcher-a | Scan wiki for approval engine architecture | file, search | default | ~3 min |
| 2 | researcher-b | Audit test coverage gaps in engine.py | terminal, file | kimi | ~5 min |
| 3 | reviewer | Compare plan vs codebase for missing imports | file | deepseek | ~4 min |

**Mode:** Individual dispatch (results stream in as each finishes)
**Status updates:** Every 2 minutes
**Completion:** Structured summary with per-subagent results
```

### Rules

1. **Always show the plan before dispatching.** Even for a single subagent.
   The user needs to know what's about to happen and correct course if needed.
2. **Estimate duration.** Based on task complexity: file reads (~2-3 min),
   code review (~3-5 min), multi-file analysis (~5-10 min), coding (~5-15 min).
   When unsure, estimate high.
3. **State dispatch mode.** Individual (default when user is waiting) or batch
   (fire-and-forget / cron only). See dispatch mode rules below.
4. **State the polling interval.** Default: every 2 minutes.
5. **For single subagents:** still show the plan — one row, same format.
   Simpler but consistent.

### When to skip the plan

- **Cron jobs / no_agent=True:** No human watching, skip the protocol entirely.
- **User explicitly says "just do it" or "don't plan, just dispatch":**
  Skip the plan, go straight to dispatch + status updates.
- **Retry of a failed subagent** within the same session where the user already
  approved the plan: skip re-planning, just note "Re-dispatching subagent N for
  retry" and resume status updates.

## Phase 2 — Incremental Status Updates

### Dispatch mode: individual (default when user is present)

Dispatch each subagent as a separate `delegate_task(goal=...)` call. Results
stream in independently as each finishes.

**Why individual dispatch:** The user sees partial results as they land. Batch
mode (`tasks=[...]`) waits for ALL subagents — can mean 20+ minutes of silence
with no way to check intermediate progress.

### The polling loop

Use **exactly one** poll timer at a time. The timer is a one-shot background
process, not a recurring alarm — the controller must not start another timer
until the current one has completed or been killed.

```bash
# Start a 2-minute poll timer — store the session_id!
terminal(command="sleep 120 && echo 'poll-ready'", background=true, notify_on_complete=true)
# → save the returned session_id as poll_timer_session_id
```

**Timer lifecycle rules:**
1. **Track the session_id.** Store it from the `terminal` response.
2. **One timer at a time.** Never have more than one `sleep N && echo 'poll-ready'` process running.
3. **Kill before spawn.** Before starting a new timer, kill the existing one using its tracked `session_id`:
   `process(action="kill", session_id=poll_timer_session_id)`
4. **Wait for it to fire.** The next poll starts only after the timer notification arrives (or you kill it early because a result came in).

When the timer fires, report status:

```markdown
⏱️ **Poll 3** — 6m elapsed | 1 completed · 2 running
  ✅ #2 researcher-b: Done (3 min) — found 4 coverage gaps in engine.py
  ⏳ #1 researcher-a: Running (6m) — scanning wiki...
  ⏳ #3 reviewer: Running (4m) — comparing plan vs code...
```

Then start the next single timer if any subagents are still running.

### Status update format

Each status update must include:

1. **Poll number** — sequential (Poll 1, Poll 2, ...)
2. **Elapsed time** — since first dispatch
3. **Per-subagent status:**
   - ✅ Completed — with elapsed time and brief result
   - ⏳ Running — with elapsed time and what it's doing (if known)
   - ❌ Failed — with error summary
4. **Next check** — when the next poll will fire

### When a subagent result arrives

Report it immediately — don't wait for the next poll cycle:

```
✅ **#2 researcher-b complete** (3m 12s)
  Found 4 coverage gaps:
  - test_apply_change: missing edge case for empty sheet
  - test_lock_column: no test for concurrent lock attempts
  - test_rollback: missing test for partial failure rollback
  - test_validation: no test for invalid column letter
```

### ⚠️ Kill the active poll timer when a subagent result arrives

When a subagent result message arrives, **kill the currently tracked poll timer**
before reporting the result, then decide whether to resume polling:

```python
# Kill the single tracked poll timer
if poll_timer_session_id:
    process(action="kill", session_id=poll_timer_session_id)
```

- If **other subagents are still running**, report the result immediately, then
  start **exactly one new poll timer** to continue the loop.
- If **all subagents have now returned**, report the result, present the
  completion summary, and do **not** start another timer.

**Why this matters:** A subagent result can arrive before the current poll timer
fires. If you report the result but leave the timer running, it will later fire
and produce a stale `[IMPORTANT: Background process ... completed]`
notification. With a single tracked timer, killing it on every result arrival
prevents stale notifications while still preserving the polling loop for any
remaining subagents.

**The rule:** Result arrives → kill tracked timer → report result → if others
remain, start one new timer → if all done, present completion summary.

| Scenario | Interval | Why |
|---|---|---|
| User actively waiting in chat | 2 min | Keep them informed, don't let them wonder |
| Long-running subagents (>10 min expected) | 3 min | Avoid spam for long waits |
| User said "just do it" / low engagement | 5 min | They don't want frequent updates |
| Cron job / no human watching | N/A | Skip polling entirely |
| User asked "Status?" prematurely | 1 min | Trust damaged — increase frequency |

**Default: 2 minutes.** Adjust based on context.

### Batch mode exception

If you must use batch mode (`tasks=[...]`):
- No intermediate results are available — the call blocks until ALL finish
- Start the polling loop anyway — report "N subagents running, batch mode,
  waiting for all to complete"
- If >10 minutes pass with no results, consider killing the batch and
  re-dispatching individually (see `subagent-driven-development` recovery
  pattern)

## Phase 3 — Completion Summary

When ALL subagents have returned, present a structured completion summary:

### Format

```
## ✅ Delegation Complete — 3/3 subagents finished (8m 32s total)

| # | Subagent | Time | Status | Key result |
|---|---|---|---|---|
| 1 | researcher-a | 5m 12s | ✅ | Wiki scan: 12 relevant pages found |
| 2 | researcher-b | 3m 12s | ✅ | 4 coverage gaps identified |
| 3 | reviewer | 4m 08s | ✅ | 2 blocking issues, 1 minor |

**Highlights:**
- Coverage gaps are in test_apply_change and test_lock_column
- Reviewer found missing import of `apply_swap` in engine.py
- All subagents completed within expected time estimates

**Next steps:**
- Fix the 2 blocking issues from reviewer
- Add tests for the 4 coverage gaps
```

### Rules

1. **Always include total elapsed time.** Wall clock from first dispatch to last
   result.
2. **Per-subagent row** with time, status (✅/❌), and one-line key result.
3. **Highlights section** — 2-4 bullet points synthesizing what the delegation
   accomplished.
4. **Next steps** — what should happen based on results. Be specific.
5. **Failures** — if any subagent failed, explain what went wrong and whether
   retry is needed.
6. **Verify claims** — for subagents that report file writes, URL creation, or
   external side effects, verify independently (read file, fetch URL, stat path)
   before reporting success.

## Dispatch Mode Decision Matrix

| Scenario | Mode | Rationale |
|---|---|---|
| User actively in chat | Individual | Results stream in; user sees progress |
| User said "just do it" | Individual | Still stream results; less frequent polls |
| Fire-and-forget (cron) | Batch | No one watching; consolidation fine |
| Subagents <2 min each | Either | Short enough that silence doesn't matter |
| Subagents >5 min each | Individual | Long silence erodes trust |
| User already asked "Status?" | Individual | Trust damaged — don't repeat |
| Subagents touch same files | Individual (serialized) | Avoid parallel file conflicts |

**Default: individual dispatch.** The slight overhead of multiple
`delegate_task` calls is negligible vs. the user seeing progress.

## Architecture: SOUL.md + Skill + Config Layering

This skill is part of a 3-layer behavioral directive pattern. See
`references/layering-guide.md` for the full rationale and when to use each
layer. In short:

- **SOUL.md** triggers the behavior every turn (no opt-in needed)
- **Skill** provides the format templates, decision matrix, and pitfalls
- **Config** provides the memory headroom for the protocol overhead

## Integration with Other Skills

### subagent-driven-development
That skill has its own embedded version of this protocol (specific to dev
work). When both skills are loaded, this general protocol takes precedence for
the communication format. The dev skill's two-stage review process still applies
for the actual review logic.

### multi-model-dev-pipeline
The pipeline stages already dispatch individually. This protocol's polling
loop wraps around the pipeline stages — report status between stages, not
mid-stage (stages are sequential, not parallel).

### kanban-orchestrator

Kanban tasks have their own lifecycle (todo → ready → in-progress → done) with
dashboard visibility. This protocol applies to `delegate_task` subagents, not
kanban workers. If using both, apply this protocol to any delegate_task calls
the orchestrator makes for quick subtasks.

**Kanban-aware polling variant:** When the orchestrator dispatches Kanban tasks
(via SDLC pipeline or direct kanban-orchestrator), the same 3-phase protocol
applies with one change: Phase 2 polls `hermes kanban list --json` instead of
waiting for subagent result messages. Everything else is identical — same timer
discipline (one tracked timer, kill-before-spawn), same status format, same
completion ceremony.

**Status mapping for Kanban tasks:**
| Kanban status | Display |
|---|---|
| `todo` | ⏳ |
| `ready` | ⏳ |
| `in-progress` | 🔄 |
| `done` | ✅ |
| `blocked` | 🚫 |
| `failed` | ❌ |

**Transition detection:** Diff current poll results against previous poll.
Only report status changes — don't re-report tasks that haven't moved.

**Polling interval for Kanban:** Adaptive — 30s for the first 2 minutes (user
is watching), then 120s thereafter. Kanban tasks have a 60s dispatcher poll
delay, so polling faster than 30s is wasted.

**Dashboard cron demotion:** The 2-minute dashboard cron becomes a fallback
safety net for session compaction / gateway restart. The orchestrator's active
polling loop is the primary status mechanism. The cron should switch to
conditional reporting: only post when tasks are stuck (>15 min in
`in-progress`) or all done.

**Hybrid pattern (SDLC pipeline):**
- Read-only research phases (codebase scan, wiki search) → use `delegate_task`
  with full 3-phase protocol (richer inline status)
- Implementation/review phases that need worktree → use Kanban tasks with
  Kanban-aware polling variant
- Unified status display covers both systems in one poll format

See `wiki/concepts/sdlc-inline-status-collaboration.md` for the full advisor
panel recommendation (3/3 unanimous, Jun 2026).

### Subprocess-based pipeline status (watch_patterns approach)

When the pipeline runs as a subprocess (e.g., `sdlc.py` via `hermes chat -q`),
use `terminal(background=true, watch_patterns=[...])` to get inline status
without polling. The pipeline emits structured `[SDLC]` lines to stderr, and
each match triggers a notification to the controller.

**Pattern:**
```bash
terminal(
    command='python3 sdlc.py "Build X" --json 2>&1',
    background=True,
    notify_on_complete=True,
    watch_patterns=[
        r'\[SDLC\] phase_start:',
        r'\[SDLC\] phase_end:',
        r'\[SDLC\] pipeline_complete:',
        r'\[SDLC\] pipeline_failed:',
    ]
)
```

**Rate-limit awareness:** `watch_patterns` has a hard 15s cooldown between
notifications. After 3 consecutive dropped matches, it auto-promotes to
`notify_on_complete` behavior. For pipelines with 9+ phases running <15s each,
some phase notifications will be dropped. This is acceptable — the user sees
progress without polling overhead. For critical pipelines where every phase
must be reported, use the polling loop instead.

**Implementation reference:** The full plan (3-layer progress_callback chain:
`model_utils.dispatch_single` → `sdlc.py` phase functions → CLI `_stderr_callback`
+ `--quiet` flag) is at:
`/opt/data/skills/productivity/ask/references/sdlc-inline-status-plan.md`
(v2, reviewed by Kimi k2.7-code, pending DeepSeek review).

## Quick Reference

```
BEFORE dispatch:
  1. Show dispatch plan (table with subagents, goals, toolsets, est. time)
  2. State dispatch mode + polling interval
  3. Dispatch individually (default)

DURING execution:
  4. Start one background sleep timer (120s default); store its session_id
  5. When timer fires: report poll #, elapsed, per-subagent status
  6. When result arrives: kill the tracked timer, report immediately
  7. If subagents remain, start exactly one new timer; repeat until all done

AFTER completion:
  7b. Confirm the tracked poll timer is killed; if not, kill it by session_id
  8. Structured summary table (subagent, time, status, key result)
  9. Highlights (2-4 bullets synthesizing results)
  10. Next steps (specific actionable items)
  11. Verify any claimed side effects independently
```

## Pitfalls

### Stale poll timers after delegation result arrives

**The #2 complaint (after going silent).** Background `sleep N` poll timers are
fire-and-forget — if the controller starts a new timer on every poll cycle
without waiting for the previous one to complete, timers stack up. When they
all eventually fire, they produce noisy `[IMPORTANT: Background process ...
completed]` notifications.

**Fix:** Use **exactly one tracked poll timer** at a time. Store the
`session_id` from each `terminal(background=true)` call. Before starting a
new timer, kill the existing one via `process(action="kill", session_id=...)`.
When a subagent result arrives, kill the tracked timer, report the result,
then start one new timer only if other subagents are still running. Never
have more than one poll timer active simultaneously.

### Going silent during long subagent runs
The #1 complaint. A subagent taking 10+ minutes with no status update makes the
user think something is broken. The polling loop exists to prevent this. Never
skip it when a human is watching.

### Using batch mode when user is waiting
Batch mode blocks until ALL subagents finish — no intermediate results. If the
user is in chat, always dispatch individually so results stream in.

### Subagent running far past estimate (5x+) — HARD CUTOFF

When a subagent runs 5x+ the estimated time (e.g., estimated 5-8 min, running 25+ min), it's likely stuck or processing far more than expected. **This is a hard cutoff, not a guideline.**

1. **At 3x estimate** — note it in the poll: "Running longer than expected — may be processing more than anticipated"
2. **At 5x estimate — STOP. Do not start another poll timer.** Report your findings from your own parallel investigation immediately. The subagent may never return (silent failure, OOM, infinite loop). Do NOT keep polling — every additional poll wastes the user's time and erodes trust.
3. **If the subagent eventually returns** — incorporate its results into the completion summary. If it never returns, the session eventually times out and the subagent's work is discarded.

**Rationale:** Subagents have no timeout mechanism visible to the controller. A subagent that runs 30+ minutes on a 5-minute task is not coming back with useful results. The user's time is better spent on your findings than waiting for a dead process.

**Anti-pattern (DO NOT DO):** Polling 12+ times over 29 minutes for a 5-8 minute estimate. This is the exact behavior this pitfall exists to prevent. At 5x the estimate (~25 min for a 5-min task), you MUST cut over to your own findings. The user should never see Poll 8, 9, 10, 11, 12 for a single subagent.

### Subagents are bad at API-heavy tasks — don't dispatch them for model-dependent work

**The pattern:** You dispatch 4 subagents in parallel. All 4 time out at 15 minutes. Each made 15+ API calls (model inference, web fetches). The subagents were doing triage enrichment, session expiry, council cleanup — all tasks that require calling local models repeatedly.

**Why this happens:** Subagents have no parallelism within themselves. Each model API call is sequential and adds 0.5-3s of latency. A subagent that needs to test 5 different model configurations makes 5 sequential API calls = 2.5-15s just in model latency, plus tool call overhead. Multiply by the number of test cases and you hit the 15-minute timeout easily.

**Decision rule:**

| Task type | Use subagent? | Why |
|---|---|---|
| File ops (read, write, patch, search) | ✅ Yes | Fast, no API latency |
| Code review (read files, analyze) | ✅ Yes | One model call at the end |
| Research synthesis (web search, extract) | ✅ Yes | Web calls are fast |
| Multi-model testing (try 5 models) | ❌ No | Each model call adds latency |
| API-heavy iteration (test → fix → test) | ❌ No | Sequential API calls compound |
| Triage prompt tuning (classify → adjust → reclassify) | ❌ No | Each iteration is a model call |

**Recovery when subagents time out:**
1. Check for partial progress: `git diff`, `git status`, new files
2. Subagents often leave usable partial work even when they time out — check before declaring total failure
3. Do the remaining work directly in the controller session
4. Do NOT re-dispatch the same tasks — they'll time out again for the same reason

### Batch sizing: use byte budget, not item count

**The pattern:** You dispatch subagents with 14-24 skills each, thinking "that's a reasonable number of items." All subagents time out at 15 minutes because each skill is 2-8KB of markdown — 14 skills × 5KB average = 70KB of context to process, plus the task instructions, plus tool output. The subagent spends most of its time just reading and processing the skill content.

**Why this happens:** Skill files vary wildly in size. A 2KB skill (simple workflow) and an 8KB skill (rich reference) are both "one item" but the 8KB one costs 4× as much context. Counting items is a false economy.

**The rule:** Max ~50KB of skill content per subagent batch. This typically means 5-8 skills depending on their size. When in doubt, check skill sizes first:

```bash
# Check skill sizes before batching
wc -c /opt/data/skills/<category>/<skill-name>/SKILL.md
```

**Recovery when batches are too large:**
1. Split into smaller batches (5 skills max, ~50KB each)
2. Re-dispatch with the corrected batch sizes
3. The subagents will complete in 3-5 minutes instead of timing out at 15

### `process(action='poll')` does NOT track delegate_task subagents

**The `process` tool and `delegate_task` are completely separate tracking systems.** `process(action='poll')` / `process(action='list')` only sees processes started via `terminal(background=true)`. `delegate_task` subagents run in their own isolated sessions managed by the async delegation system — they will NEVER appear in the process list.

**Symptoms of this mistake:**
- `process(action='list')` returns empty when subagents are running
- `process(action='poll', session_id=...)` returns "Process not found"
- You conclude subagents are "lost" when they're actually running fine
- You re-dispatch the same work, creating duplicate subagents

**How to actually check delegation status:**
1. **Check agent.log for lifecycle events (FASTEST)** — `terminal(command="grep -i 'deleg_<id>\\|Dispatched async\\|ASYNC DELEGATION BATCH COMPLETE' /opt/data/logs/agent.log | tail -20")` shows dispatch, completion, and error events for the delegation batch. This is faster than session log scanning and works even when the subagent hasn't written session files yet. Also reveals whether the subagent is still making API calls (look for `agent.conversation_loop: API call #N` lines with the subagent's session ID).
2. **Check session logs** — `terminal(command="grep -l '<deleg_id>' /opt/data/sessions/*/session.json 2>/dev/null")` to find the subagent's session file
3. **Check git working tree** — if the subagent was asked to edit files, `git diff` shows its work. Also: `find <project_dir> -mmin -5 -type f` reveals files the subagent modified in the last 5 minutes.
4. **Wait for the result message** — delegate_task results re-enter the conversation as their own message when the subagent finishes. If the parent session undergoes context compaction before the result arrives, the message may be delivered but not visible in the compacted view.
5. **session_search for the delegation ID** — the subagent's result message contains the delegation batch ID

**Recovery when results don't arrive:**
1. Check `git status` / `git diff` for uncommitted changes — subagents that applied patches leave evidence
2. Check session logs for the subagent session: `grep -r "deleg_<id>" /opt/data/sessions/`
3. Read the diffs directly and assess what was changed
4. Commit the subagent's changes with a note that results were recovered from git, not delivered as a message
5. Do NOT re-dispatch the same work — check for evidence first

### Gateway restart kills background delegations (SILENT)

Background `delegate_task` subagents run inside the gateway process. If the gateway is restarted (e.g., `hermes gateway restart`, docker restart, config change), **all running subagents are killed silently**. The controller receives no notification — the subagent simply never returns.

**Detection:** If a subagent has been running >2x its estimate with no result, check whether a gateway restart occurred:
```bash
# Check gateway uptime
hermes gateway status 2>/dev/null | grep -i uptime
# Or check process start time
ps -o lstart= -p $(pgrep -f "hermes.*gateway") 2>/dev/null
```

**Recovery:** If the gateway was restarted after dispatch, the subagent is dead. Re-dispatch it — do not keep polling. Report to the user: "Gateway restart killed subagent N — re-dispatching now."

**Prevention:** When you know a gateway restart is about to happen (e.g., after a config change), warn the user that any running delegations will be lost. Finish or cancel them before the restart.

### Delegation config changes require gateway restart

Changes to `delegation.model` or `delegation.provider` in `config.yaml` are read at gateway startup and cached for the lifetime of the process. A live `hermes config set delegation.model <new-model>` writes the file but the running gateway continues using the old value. The change only takes effect after a gateway restart.

**Detection:** After changing delegation config, dispatch a test subagent with a trivial prompt (e.g., "respond with your model name"). If the subagent's result shows the old model, the config hasn't taken effect yet.

**Fix:** Restart the gateway (`hermes gateway restart` from outside the gateway, or `docker restart hermes`). After restart, re-verify with another test delegation.

### delegate_task cannot select different models per subagent

**This is a hard architectural limitation, not a config issue.** All subagents in a `delegate_task` call inherit the same `delegation.model` from config.yaml. There is no per-subagent model override — the `model` parameter in `delegate_task` is ignored. A "diverse panel" dispatched via `delegate_task` is an illusion: all seats run the same model.

**Symptoms:**
- You dispatch 3 subagents expecting deepseek, kimi, and glm — all 3 report the same model
- Per-subagent model overrides have no effect
- The "council" pattern silently collapses to a single-model echo chamber

**Solution:** Use the `advisors` skill instead. It dispatches parallel `hermes chat -q` subprocesses, each with `-m <model> --provider <provider>`, giving true model diversity. Each seat is a full Hermes agent with tools and skills. See `skill_view(name='advisors')` for the full process.

**When to use which:**
| Scenario | Use |
|---|---|
| Parallel work with same model (code review, research, file ops) | `delegate_task` |
| Multi-model consensus / diverse panel | `advisors` skill (`hermes chat -q` subprocesses) |
| Role-based development (planner→coder→debugger) | `dev` skill (wraps `prompt_model.py`) |
| Interactive model queries with aliases | `ask` skill (wraps `hermes chat -q`) |
| Both (parallel work + model diversity) | `advisors` for the panel, `delegate_task` for same-model subtasks |

### Over-reporting trivial progress
"Subagent 1 still running... Subagent 1 still running... Subagent 1 still
running" is noise. If nothing changed since the last poll, say so briefly:
"⏱️ Poll 4 — 8m elapsed | No changes. Subagent 1 still scanning wiki (est. 2
more min)."

### Forgetting the completion summary
When results stream in individually, it's tempting to just report each one and
move on. Always close with the structured completion summary — the user needs
the synthesized view of what the delegation accomplished.

### Reporting subagent claims as verified facts
Subagents self-report. "File written successfully" may be wrong. For any
external side effect (file write, HTTP POST, URL creation), verify
independently before reporting success in the completion summary.

### Subagents can make unsanctioned changes beyond review scope

**The pattern:** You dispatch a code reviewer subagent to review specific
changes. The subagent returns a review — but also made its own edits to files
outside the review scope. You commit without checking `git diff` and only
discover the unsanctioned changes later.

**Real example:** An alias-reviewer subagent was asked to review `model_utils.py`
alias consistency. It returned a clean review — but also changed the `debugger`
alias from `kimi-k2.7-code:cloud` to `qwen3-coder-next:q4_K_M` and added two
new aliases (`debugger-fallback`, `test-planner`) that didn't exist in the
alias registry. These changes were outside the review scope and broke the
debugger alias.

**Prevention — ALWAYS do this after a subagent code review:**
1. Run `git diff` to see ALL changes the subagent made
2. Compare the diff against the subagent's stated review scope
3. If the diff includes changes beyond scope, revert them immediately:
   `git checkout -- <file>` or `git restore <file>`
4. Only commit changes that match the review scope
5. If the subagent made useful changes beyond scope, evaluate them separately
   before committing — don't blindly accept them

**Why this matters:** Subagents are autonomous agents with full file write
access. They can "helpfully" fix things they notice, even when not asked.
This is usually harmless but can silently break configuration (aliases,
model names, API endpoints) that the subagent doesn't fully understand.