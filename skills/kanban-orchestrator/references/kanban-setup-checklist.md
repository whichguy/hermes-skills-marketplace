# Kanban Setup Checklist

> Concrete setup steps discovered during the 2026-06-26 Kanban integration
> project. The orchestrator skill covers *using* Kanban; this reference covers
> the one-time *setup* before Kanban is usable.

## Prerequisites

- Hermes Agent installed and running
- Gateway accessible (for dispatcher)
- At least 2 profiles (orchestrator + at least one worker)

## Step 1 — Create Specialist Profiles

```bash
# From host (Docker):
docker exec -it hermes /opt/hermes/bin/hermes profile create worker
docker exec -it hermes /opt/hermes/bin/hermes profile create reviewer

# Or from inside the container:
hermes profile create worker
hermes profile create reviewer
```

Each profile gets its own `SOUL.md`, `skills/`, `cron/`, and `memories/`.
Use `--clone default` to copy skills from the default profile.

Verify: `hermes profile list`

## Step 2 — Set Profile Models

```bash
hermes -p worker model set kimi-k2.7-code:cloud
hermes -p reviewer model set deepseek-v4-pro:cloud
```

Worker should be fast and code-capable. Reviewer should be a different model
for genuine cognitive diversity (maker-checker).

## Step 3 — Configure Kanban in config.yaml

```yaml
kanban:
  orchestrator_profile: default       # profile that creates/assigns tasks
  default_assignee: worker            # fallback when no assignee specified
  max_in_progress: 3                  # caps total concurrent tasks
  max_in_progress_per_profile: 2      # prevents single-profile saturation
  failure_limit: 5                    # auto-block after N consecutive failures
  dispatch_in_gateway: true           # dispatcher runs inside gateway process
  auto_decompose: true                # kill switch — flip to false to halt all
  dispatch_interval_seconds: 60       # how often dispatcher checks for ready tasks
```

Key config rationale:
- `max_in_progress: 3` — prevents Ollama saturation (local models share GPU)
- `max_in_progress_per_profile: 2` — prevents one profile from hogging all slots
- `failure_limit: 5` — was 2 by default, too aggressive for real work
- `auto_decompose: true` — emergency kill switch; flip to `false` to halt all dispatch

## Step 4 — Initialize the Board

```bash
hermes kanban init
```

Creates `/opt/data/kanban.db` (SQLite). The command auto-discovers profiles
on disk and lists them as valid assignees.

Verify: `hermes kanban list` (should show "no matching tasks")

## Step 5 — Restart Gateway

The gateway hosts the embedded dispatcher. Without a running gateway, tasks
stay in `ready` forever.

```bash
# Docker:
docker restart hermes

# Or s6:
s6-svc -r /run/service/hermes-gateway
```

**⚠️ Warning:** Gateway restart kills all running background delegations
(subagents, council panel members). Wait for active delegations to complete
before restarting, or be prepared to re-dispatch.

## Step 6 — Create Project AGENTS.md Files

Each project directory under `/opt/data/projects/<name>/` should have an
`AGENTS.md` that Kanban workers auto-load as context. Include:

- Project purpose and architecture
- Key file paths
- Coding standards and conventions
- Test commands
- Current state and known issues

Example structure:
```markdown
# Project Name

## Architecture
Brief description of what this project is and how it's structured.

## Key Files
- `/path/to/main.py` — description
- `/path/to/tests/` — test suite

## Coding Standards
- Convention 1
- Convention 2

## Testing
- Run: `pytest tests/`

## Current State
What's done, what's in progress, known issues.
```

## Step 7 — Smoke Test

Before putting real work on the board, verify the pipeline:

1. **Gateway pre-flight:** `hermes kanban list` shows board is accessible
2. **Worker task:** Create a simple task, assign to worker, verify it completes
3. **Reviewer task:** Create a review task, verify reviewer picks it up
4. **Block flow:** Block a task, verify it stops, unblock, verify it resumes
5. **Kill switch:** Flip `auto_decompose: false`, verify dispatch stops

## Post-Setup

The execution plan for the full Kanban integration project lives at:
`/opt/data/projects/kanban-integration/execution-plan.md`

It covers Phase 3.5 (smoke tests), Phase 4a (manual trigger), Phase 4b
(auto-detect), and Phase 5 (twice-daily review cron).
