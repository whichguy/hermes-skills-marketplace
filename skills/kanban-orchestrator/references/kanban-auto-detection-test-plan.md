# Kanban Auto-Detection Test Plan

Validates that the default profile automatically routes multi-step work to the kanban board after SOUL.md injection.

## Prerequisites

- `$HERMES_HOME/SOUL.md` contains the Kanban Routing block (see orchestrator SKILL.md)
- At least 2 profiles exist (e.g., `default` + `worker`)
- `kanban.dispatch_in_gateway: true` in config.yaml
- Board initialized: `hermes kanban init`

## Phase 1 — Baseline (Before SOUL.md Injection)

Run these prompts in fresh sessions and observe whether kanban tasks are created:

| # | Prompt | Expected | Actual |
|---|---|---|---|
| 1a | "Build a Python CLI tool for tracking gym workouts" | Decompose → kanban tasks | |
| 1b | "Fix the bug in approval-engine and add a test" | Single-lane code task → worker + reviewer | |
| 1c | "Research the best GLM-5.2 alternatives and write a comparison doc" | Research → synthesis → drafting (3-profile fan-out) | |
| 1d | "What's 2+2?" | No kanban tasks created | |

## Phase 2 — After SOUL.md Injection

Re-run the same prompts. Compare routing rates.

## Phase 3 — Prompt Pattern Testing

| Pattern | Example | Expected |
|---|---|---|
| Explicit "use kanban" | "Use kanban to build a REST API" | Always triggers |
| Multi-step implicit | "Research X, then implement Y, then review" | Should trigger decomposition |
| Vague multi-step | "Build an app" | May or may not trigger |
| "In the background" | "Run a background research project on X" | Should trigger kanban (not delegate) |
| "Across sessions" | "Set up a project that persists across sessions" | Should trigger kanban |

## Phase 4 — Dispatcher Validation

1. Create test task: `hermes kanban create "smoke test: write hello world" --assignee worker`
2. Verify dispatcher picks it up within 60s: `hermes kanban show <id>`
3. Verify worker completes: status → `done` with summary
4. Verify notification: gateway pings on completion
5. Test block flow: create review task, block it, verify dashboard shows it
6. Test parent-child: T1 (research) + T2 (implement, parent=T1) — T2 stays `todo` until T1 done

## Phase 5 — Auto-Trigger Cron (Optional)

```bash
hermes cron create \
  --schedule "every 4h" \
  --prompt "Check hermes kanban list for any tasks in running/blocked/ready states. Summarize active work in 3 lines. If nothing is active, stay silent." \
  --model "glm-5.2:cloud" \
  --name "kanban-status-check"
```

Note: GLM model defaults to Chinese output — prompt must include "respond in English only".

## Key Findings (2026-06-27)

- Default profile has zero kanban awareness without SOUL.md injection
- Kanban toolset is gated to worker processes — default profile must use CLI (`hermes kanban create`)
- Skills are discoverable but agent must scan and recognize relevance each turn
- SOUL.md injection is the highest-leverage change — puts routing rules in the stable prompt tier
