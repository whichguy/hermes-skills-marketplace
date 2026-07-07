# Kanban Stuck-Task Watchdog

Operational monitoring pattern: a Python script that reads `kanban.db` directly, detects tasks stuck in `running` or `blocked` beyond configurable thresholds, and alerts via a `no_agent=true` cron job.

## Script: `kanban_stuck_watch.py`

Location: `~/scripts/kanban_stuck_watch.py` (or wherever the user keeps operational scripts).

### What it does

- Opens `kanban.db` (SQLite) directly — no CLI dependency, no agent loop
- Scans for tasks in `running` status with `updated_at` older than `--running-hours` (default: 24)
- Scans for tasks in `blocked` status with `updated_at` older than `--blocked-hours` (default: 48)
- Silent (empty stdout) when the board is healthy — follows the watchdog pattern
- On detection: prints task IDs, titles, assignees, hours stuck, and recovery hints (`hermes kanban reassign --reclaim` for running, `hermes kanban unblock` for blocked)

### Usage

```
python3 kanban_stuck_watch.py --db /opt/data/kanban.db --running-hours 24 --blocked-hours 48
```

### Cron deployment

```
hermes cron create \
  --name "Kanban stuck-task watchdog" \
  --schedule "0 * * * *" \
  --script kanban_stuck_watch.py \
  --no_agent
```

Key design decisions:
- `no_agent=true` — the script IS the job; no LLM needed for a threshold check
- `--script` not `--prompt` — the script produces the exact alert text
- Silent on healthy board — no delivery when stdout is empty (watchdog pattern)
- No `workdir` — the script reads `kanban.db` by absolute path, no project context needed

### Why not an agent-driven cron?

A threshold check ("is this timestamp older than 24h?") is deterministic. Running it through an LLM adds latency, cost, and failure modes for zero benefit. The script produces the exact alert format every time.

### Recovery hints in alert output

When stuck tasks are found, the output includes copy-paste recovery commands:

- **Stuck running:** `hermes kanban reassign <id> <new-profile> --reclaim`
- **Stuck blocked:** `hermes kanban unblock <id>` (after reviewing why it's blocked)

### Status names

The correct status for active tasks is `running` (not `in_progress`). Full status list: `archived, blocked, done, ready, review, running, scheduled, todo, triage`. Verified via `hermes kanban list --help`.
