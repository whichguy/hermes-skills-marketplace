# Kanban Dashboard Pattern — Script-Only Cron Monitoring

> Added 2026-06-27 from live SDLC chain monitoring session.

## Problem

The default `hermes kanban list` output is a thin table — task IDs, status, title. For monitoring a multi-phase SDLC chain, the user wants a rich dashboard showing:
- The original goal (from the root task)
- Pipeline stages with status icons, assignees, skills, timestamps
- Completed tasks with their key results/summaries
- Pending/active tasks with contextual insights (blocked by parent, actively processing)
- Progress bar
- Delta detection (what changed since last check)

Using an LLM-driven cron job for this is wasteful — it burns tokens on formatting that a deterministic script can do.

## Solution: `no_agent=true` script-only cron

A Python script that:
1. Calls `hermes kanban list --json` to get all tasks
2. Calls `hermes kanban show <id> --json` for each task to get body, summary, comments
3. Parses the JSON, builds the enriched dashboard
4. Saves state to `.dashboard-state/prev-status.json` for delta detection
5. Prints the formatted dashboard to stdout

The cron job is configured with `no_agent=true` and `script=kanban-dashboard.py` — the scheduler runs the script and delivers stdout verbatim. Zero tokens, deterministic, fast.

## Script Requirements

- Must live in `~/.hermes/scripts/` (cron `script` field only accepts filenames relative to this directory)
- Must handle Bitwarden warning prefix in CLI output: use `output.find("{")` to strip non-JSON text before `json.loads()`
- Must use `subprocess.run()` not shell pipes (Bitwarden prefix breaks `--json | python3`)
- State file goes in the project directory, not `/tmp` (survives container restarts)

## Dashboard Sections

### Slack-Optimized Format (preferred — no separator lines)

**CRITICAL:** Do NOT use `━` or `─` separator lines in Slack output. They render as ugly dense text blocks. Slack mrkdwn does not support horizontal rules. Use blank lines, bold headers, and blockquotes for visual separation instead.

```
📋 *Kanban SDLC Pipeline Dashboard*

🎯 *Original Goal*
> <root task body excerpt>

🔗 *Pipeline Stages*

✅ *Stage 1: Research* → <title>
`<task_id>` · assignee: <name> · skills: <list>
⏱️ completed: <timestamp>

🔵 *Stage 2: Implement* → <title>
`<task_id>` · assignee: <name> · skills: <list>
⏱️ started: <timestamp>
_Actively processing..._

⬜ *Stage 3: Review* → <title>
`<task_id>` · assignee: <name> · skills: <list>
⏸️ Blocked by parent task(s): <ids>
_Auto-promotes when parent completes._

✅ *Completed* (N)
• <Phase> `task_id` — 📦 <summary excerpt>

⏳ *Pending & Active* (N)
• 🔵 <Phase> `task_id` — <title> — _<contextual insight>_
• ⬜ <Phase> `task_id` — <title> — _Blocked by parent_

📊 *Progress:* N/M complete `▓░░`
🔄 N task(s) actively processing...
```

When all tasks complete:
```
🎉 *Pipeline Complete!*
📦 *Full Deliverables:*
• <Phase 1>: <summary>
• <Phase 2>: <summary>
```

### Slack mrkdwn Best Practices

| Do | Don't |
|---|---|
| `*bold headers*` with blank line separation | `━━━` separator lines (ugly in Slack) |
| `> blockquotes` for goals and summaries | Pipe tables (not rendered in Slack) |
| `` `code` `` for task IDs and metadata | Dense text blocks without spacing |
| `_italic_` for contextual insights | `# Headers` (rendered as `*bold*`, no hierarchy) |
| Emoji as visual markers (✅🔵⬜) | More than 2 consecutive bold lines |
| Blank lines between sections | Indented lists (render as literal text) |

### Block Kit — Direct API Approach (Working — 2026-06-27)

Slack's Block Kit API supports rich layouts: `header` blocks, `section` with `fields` (two-column), `divider`, `context` (gray metadata), and `rich_text` (lists, code blocks, colored text). The Hermes gateway's Slack adapter sends messages as `{"text": formatted, "mrkdwn": True}` — no `blocks` field in the main delivery path.

**The workaround:** The dashboard script reads `SLACK_BOT_TOKEN` from `/opt/data/.env` and posts Block Kit JSON directly to `chat.postMessage` via `urllib`. This bypasses the gateway entirely for Block Kit delivery while the cron job's `no_agent` path delivers a short text confirmation.

**Key advantages:**
- Thread replies work via `thread_ts` (webhooks don't support this)
- No Slack admin setup needed (uses existing bot token)
- No gateway code changes required
- Falls back to plain text if the API call fails

**Cron integration pattern:**
```python
# Script posts Block Kit directly, then prints short confirmation
if SLACK_TOKEN:
    # ... post blocks to chat.postMessage ...
    print(f"Block Kit posted ✅ ({done_count}/{total_count} complete)")
else:
    # Fall back to text-only delivery via cron's no_agent path
    print(fallback_text)
```

The cron job is configured with `no_agent=true` and `script=kanban-dashboard.py`. The scheduler runs the script and delivers stdout verbatim. The Block Kit message arrives separately via the direct API call — the user sees the rich card plus a tiny text confirmation.

See `slack-block-kit-enhancement` skill → `references/slack-rich-delivery-options.md` for full research and the direct API implementation pattern.

## Status Icons (v2 — shape-consistent, 2026-06-27)

| Status | Icon | Segment | Notes |
|--------|------|---------|-------|
| done | ✅ | 🟩 | Checkmark for final states |
| running | 🟦 | 🟦 | Blue square = actively processing |
| ready | 🟨 | 🟨 | Yellow square = ready for dispatch |
| todo | ⬜ | ⬜ | White square = queued |
| blocked | 🚫 | 🟥 | Prohibition sign = blocked |
| review | 🟪 | 🟪 | Purple square = under review |

**Design rationale (DeepSeek Pro review, 2026-06-27):** Shape-consistent squares (`🟩🟦🟨⬜🟥🟪`) reduce cognitive load vs mixed circles/checkmarks. `🚫` is a stronger visual metaphor for "blocked" than a red circle. The `SEGMENTS` dict (separate from `ICONS`) provides uniform-width emoji for the progress bar — each emoji is the same cell width in Slack, so the bar aligns cleanly across desktop and mobile.

## Delta Detection

The script saves `prev-status.json` after each run:
```json
{
  "t_ad26fb07": "done",
  "t_648df7c9": "running",
  "t_e95d5848": "todo"
}
```

On the next run, it compares current vs previous status. Changed tasks get a ⚡ marker:
```
⚡ Status changed: 🔵 running → ✅ done
```

## Cron Job Configuration

```bash
hermes cron create \
  --name "Kanban SDLC Dashboard Monitor" \
  --schedule "3m" \
  --repeat 30 \
  --script "kanban-dashboard.py" \
  --no-agent \
  --deliver "slack"
```

Key flags:
- `--no-agent` — skip LLM, run script only
- `--script` — filename relative to `~/.hermes/scripts/`
- `--deliver` — platform to deliver stdout to
- `--repeat` — finite repeat count (30 × 3min = 90min of monitoring)

## Pitfalls

- **Script path must be relative to `~/.hermes/scripts/`.** Absolute paths are rejected. Copy the script there first.
- **Bitwarden prefix breaks JSON parsing.** Always use `output.find("{")` before `json.loads()`.
- **`hermes cron list --json` doesn't output to stdout.** Use `hermes cron list` text output for verification.
- **State file location matters.** Don't use `/tmp` — it's wiped on container restart. Use the project directory.
- **Slack doesn't render markdown tables.** Use emoji, bold, and structured sections instead of pipe tables.

## Block Kit v2 Design (2026-06-27 — DeepSeek Pro Review)

After a DeepSeek Pro visual design review, the dashboard was redesigned with these principles:

### Applied Improvements

| # | Change | Impact | Rationale |
|---|---|---|---|
| 1 | `emoji: True` on all `plain_text` headers | LOW | Ensures consistent emoji rendering across Slack clients |
| 2 | Segmented emoji progress bar (`🟩🟦🟨⬜`) | HIGH | Uniform cell width, color carries meaning, no broken Unicode |
| 3 | **No duplicate sections** — each task shown once | HIGH | Removed separate Completed and Pending sections that repeated stages |
| 4 | **Single-column layout** (`section.text` + `context` footer) | HIGH | Reads naturally on both desktop and mobile; two-column `fields` stack awkwardly |
| 5 | Shape-consistent emoji set (`✅🟦🟨⬜🚫`) | MEDIUM | Consistent shapes reduce cognitive load; `🚫` stronger than red circle |
| 6 | **Reduced dividers** — only 2 major breaks | MEDIUM | Too many dividers create visual noise; headers already provide separation |
| 7 | Key results inline in stage block (blockquote) | HIGH | Instead of separate Completed section, summary appears under the stage |
| 8 | Insights inline in stage block | HIGH | Instead of separate Pending section, contextual notes appear under the stage |
| 9 | Skill icons (`🔍 spike` `🧪 tdd` `👀 code-review`) | LOW | Icons make skill types scannable |
| 10 | Context footer per stage (small gray metadata) | MEDIUM | `context` text is smaller and gray, visually separating metadata from content |

### New Layout (12 blocks, down from ~20+)

```
Header: 📋 Kanban SDLC Pipeline Dashboard
Context: 🔄 3 stages • Updated HH:MM UTC
Section: 🎯 Original Goal > blockquote
Section: 📊 Progress: N/M complete + segmented bar
Divider
Header: 🔗 Pipeline Stages
Section: {icon} *N. Stage* — detail
         ⏱️ timing line
         ⚡ delta line (if changed)
         📦 summary (if done) / 💡 insight (if running) / 🚫 blocked note
Context: `task_id` • 👤 `assignee` • skill icons
... (repeat per stage)
Divider
Section: Progress summary or 🎉 Hero completion card
```

### Design Recommendations Document

Full DeepSeek Pro review with 14 recommendations: `references/kanban-dashboard-design-recommendations.md` in the `kanban-orchestrator` skill.

## Block Kit v3 Enhancements (2026-06-27 — Live Debugging Session)

After a T3 crash incident (skill not found in reviewer profile), the dashboard was enhanced with per-stage diagnostics:

### New Per-Stage Indicators

| Indicator | What It Shows | Example |
|---|---|---|
| **Heartbeat count** | Worker liveness — counts `heartbeat` events in `kanban show` output | `💡 Being worked on by reviewer (1 run(s), 3 heartbeats)` |
| **Run count** | How many times the worker has been spawned (retries) | `(2 run(s), 5 heartbeats)` |
| **Crash detection** | Counts `crashed` events in show output | `⚠️ 3 crash(es) detected — check logs` |
| **Workspace path** | Where the worker is writing files | `📁 /opt/data/kanban/workspaces/t_fc87a0e2` |

### Implementation Details

- `show_raw` is stored on each enriched task dict during the enrichment loop
- Heartbeat/run/crash counts are extracted from the raw `kanban show` text output
- Workspace path is parsed from the `workspace: scratch @ /path` line
- All diagnostics appear inline in the stage's `section` block, not as separate sections
- Context footer now includes workspace path alongside task ID, assignee, and skills

### Crash Recovery Workflow

When the dashboard shows `⚠️ N crash(es) detected`:
1. Check `hermes kanban show <id>` for the crash reason
2. If skill not found: archive crashed task, create replacement with correct skills, link to parent
3. If model bias (pytest, etc.): reassign to different profile or edit task body
4. If unknown: check worker logs at the workspace path

### Pitfall: `body` can be `None`

The `kanban list --json` output may have `body: null` for tasks created without a body. Always use `t.get("body") or ""` not `t.get("body", "")` — the latter returns `None` when the key exists with a null value.
