# Session DB Internals for Open Threads

## Schema (state.db)

### sessions table
| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | Format: `YYYYMMDD_HHMMSS_<8hex>` |
| `source` | TEXT | `slack`, `telegram`, `whatsapp`, `tui`, `cron`, `tool` |
| `user_id` | TEXT | Platform user ID |
| `model` | TEXT | Model used (e.g. `glm-5.2:cloud`) |
| `parent_session_id` | TEXT | Links compression/reset chains |
| `started_at` | REAL | Unix timestamp |
| `ended_at` | REAL | Null if still active |
| `end_reason` | TEXT | `agent_close` (normal), `compression`, `session_reset`, `session_reset` |
| `message_count` | INTEGER | Total messages in session |
| `title` | TEXT | Auto-generated title (may be NULL/untitled) |
| `archived` | INTEGER | 0/1 |

### messages table
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | TEXT | FK to sessions.id |
| `role` | TEXT | `user`, `assistant`, `tool`, `session_meta` |
| `content` | TEXT | Message text (NULL for tool-only messages) |
| `finish_reason` | TEXT | `stop`, `incomplete`, `tool_calls`, `length` |
| `timestamp` | REAL | Unix timestamp |
| `platform_message_id` | TEXT | **Always NULL** — Slack adapter doesn't persist message ts here |
| `active` | INTEGER | 1 = active, 0 = compacted/superseded |
| `compacted` | INTEGER | 1 = content was compacted into a summary |

### Key: `platform_message_id` is always empty
The Slack adapter does not write `thread_ts` or `channel_id` to the messages table.
This means deep links CANNOT be constructed from the session DB alone.

## Session Routing (sessions.json)

Location: `/opt/data/sessions/sessions.json`

This is the **gateway routing index** — maps session keys to active session entries.
Only contains **currently routed** sessions (~50 entries). Old sessions that were
reset/replaced are removed from this file.

### Session key format (Slack DMs)
```
agent:main:slack:dm:{chat_id}:{thread_id}
```
- `chat_id` = Slack channel ID (e.g. `YOUR_SLACK_CHANNEL_ID` for DMs)
- `thread_id` = Slack `thread_ts` (parent message timestamp, e.g. `YOUR_PHONE_NUMBER.932019`)

### Entry structure
```json
{
  "session_key": "agent:main:slack:dm:YOUR_SLACK_CHANNEL_ID:YOUR_PHONE_NUMBER.932019",
  "session_id": "20260624_104648_cc88e587",
  "origin": {
    "platform": "slack",
    "chat_id": "YOUR_SLACK_CHANNEL_ID",
    "chat_name": "YOUR_SLACK_CHANNEL_ID",
    "chat_type": "dm",
    "user_id": "U01HNQF9CFQ",
    "user_name": "The User",
    "thread_id": "YOUR_PHONE_NUMBER.932019"
  }
}
```

## Deep Link Construction

Slack deep link format:
```
https://slack.com/archives/{channel_id}/{thread_ts}?team={team_id}
```

### Resolution chain
1. Direct lookup: session_id → sessions.json → origin → deep link
2. If not in sessions.json: walk `parent_session_id` chain (up to parents, down to children)
   to find a related session that IS in sessions.json — use its origin (same Slack thread)
3. If entire chain is pruned: `deep_link` = null (show Resume/Dismiss without View Thread)

### Team ID
Hardcoded in scanner as `YOUR_SLACK_TEAM_ID`. Configurable via `SLACK_TEAM_ID` env var.

## Chain Collapse

Multiple sessions can share the same Slack thread (via resets/compressions). The scanner
collapses these by walking `parent_session_id` chains to find the root, grouping by root,
and keeping only the **latest** session (most recent `started_at`). This prevents showing
3 "Fix WhatsApp Bot Pairing Code #1/#2/#3" entries for the same thread.

### Chain walking logic
```python
# Walk up parent chain to find root
current = session_id
while current:
    parent = SELECT parent_session_id FROM sessions WHERE id = current
    if parent in recent_session_ids:
        root = parent
        current = parent
    else:
        break
```

## Classification Signals

### finish_reason values
| Value | Meaning | Classification impact |
|-------|---------|----------------------|
| `stop` | Normal completion | Check content for resolution/pending language |
| `incomplete` | Response was cut off | **Active** — genuine interruption |
| `tool_calls` | Agent was mid-tool-call when killed | **NOT a signal** — happens on every gateway shutdown |
| `length` | Hit token limit | Treat as ambiguous (may need continuation) |

### end_reason values
| Value | Meaning | Classification impact |
|-------|---------|----------------------|
| `agent_close` | Normal gateway shutdown | Not a signal — happens on every session |
| `compression` | Context was compacted | **Active** — session was disrupted |
| `session_reset` | Session was reset (4am daily or /new) | **Active** — session was disrupted |
| `session_switch` | /resume was used | Not a signal (intentional switch) |

### Resolution language patterns
```
✅, all done, done, complete, here's the summary, shipped,
ready when you are, good to go, you're all set, that's it,
finished, verified pass, everything is done, here's what i found,
here's the full picture, no config change, you're already getting it,
no evidence of, nothing was lost, all checks pass
```

### Pending action patterns
```
want me to, shall i, should i, i'll now, i'll go ahead, i'll start,
let me check, let me verify, let me run, let me test, let me build,
let me create, let me set up, let me configure, let me update, let me fix,
next i need to, i'm about to, i can do, i can set, i can run, i can check,
say "resume, say "dismiss, say "run, say "set, say "continue
```

## next_action Extraction

The scanner extracts a `next_action` string from the last assistant message:

1. **SUGGESTION markers**: regex `"next"\s*:\s*"([^"]+)"` from the SUGGESTION JSON
2. **Pending action phrases**: extract the sentence containing the match (e.g. "Let me check the git state" → "check the git state")
3. **Incomplete/compression**: use the last non-empty assistant content (truncated to 150 chars)
4. **Stale dangling (>24h)**: "Revisit or dismiss — this is [age]h old"

The LLM step (skill or cron) cleans up the raw extraction into a readable action phrase.

## Dismissal Store

Database: `/opt/data/open-threads.db`
```sql
CREATE TABLE dismissed_sessions (
  session_id TEXT PRIMARY KEY,
  topic TEXT,
  dismissed_at REAL,
  expires_at REAL  -- dismissed_at + 7 days
);
```

The scanner excludes dismissed sessions from results. Dismissals auto-expire after 7 days.