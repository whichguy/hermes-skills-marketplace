# Session-to-Wiki Capture Pattern

Captures valuable conversation knowledge into the wiki — decisions, config
changes, debugging insights, and project updates that happen in chat sessions
but never make it into the wiki through URL or email ingest pipelines.

## When to Use

- User asks to "capture conversation history" or "save what we discussed"
- You're setting up a wiki and want conversation knowledge to compound
- A session produced significant work (config changes, debugging, architecture
  decisions) that would be valuable to look up later

## Architecture

```
session_wiki_precheck.py  (precheck script, scripts/)
  ↓ queries $HERMES_HOME/state.db sessions table
  ↓ filters: non-cron, 48h lookback, tool_call_count > 3, not archived
  ↓ dedupes by session_id against cron/state/session_wiki_seen.json
  ├── empty stdout → no sessions → LLM never fires (zero cost)
  └── session list with IDs, titles, tool counts
      → LLM uses session_search to read each session
      → triages: SKIP (casual) / NOTE (existing page) / PAGE (new page)
      → creates/updates wiki pages with frontmatter + wikilinks
      → updates index.md + log.md
```

## Session DB Schema (state.db)

```sql
-- Key columns in the sessions table:
id              TEXT    -- session ID (e.g. "20260622_041824_eeb4b5f8")
title           TEXT    -- human-readable title
source          TEXT    -- 'slack', 'telegram', 'whatsapp', 'cron', 'subagent'
started_at       REAL    -- epoch float (NOT created_at — that column doesn't exist)
model           TEXT    -- model used
tool_call_count INTEGER -- number of tool calls (proxy for "real work")
message_count   INTEGER -- total messages
archived        INTEGER -- 0 or 1
```

**Critical:** Use `started_at` (REAL epoch), not `created_at`. The sessions table
does NOT have a `created_at` column. Always check schema first:

```python
cols = conn.execute('PRAGMA table_info(sessions)').fetchall()
```

## Precheck Script Design

```python
import sqlite3
from datetime import datetime, timezone, timedelta

cutoff_epoch = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()

rows = conn.execute("""
    SELECT id, title, source, started_at, model, tool_call_count, message_count
    FROM sessions
    WHERE started_at > ?
      AND source NOT IN ('cron', 'scheduler')
      AND tool_call_count > 3
      AND archived = 0
    ORDER BY started_at DESC
    LIMIT 10
""", (cutoff_epoch,)).fetchall()
```

**Why `tool_call_count > 3`?** Sessions with 0-3 tool calls are usually casual
chat ("what model are you?", simple lookups). Sessions with 4+ tool calls
involved real work — debugging, config changes, file operations — that's worth
reviewing for wiki-worthy knowledge.

## Cron Job Configuration

```yaml
name: Session-to-wiki capture
schedule: 0 7 * * *    # daily at 7AM UTC
model: claude-sonnet-4-6  # Sonnet — requires judgment to decide what's wiki-worthy
script: session_wiki_precheck.py
skills: [llm-wiki]
enabled_toolsets: [terminal, file, session_search, skills]
deliver: origin
```

**Why Sonnet, not Haiku?** The LLM must read session content and make judgment
calls: is this a one-off chat (SKIP), a fact to add to an existing page (NOTE),
or a new entity/concept worth its own page (PAGE)? That's synthesis, not formatting.

## Cron Prompt Essentials

The prompt must instruct the LLM to:

1. **Orient first** — read SCHEMA.md and index.md before touching anything
2. **Use `session_search`** — the precheck gives session IDs; the LLM must
   search and read each session's content to find what's valuable
3. **Triage** — SKIP (casual chat, already documented), NOTE (add to existing
   page), PAGE (create new page)
4. **Focus on durable knowledge** — config changes + rationale, problems solved
   + how, new entities discovered, project updates, architecture decisions
5. **Follow standard ingest workflow** — check existing pages, frontmatter,
   wikilinks, index/log updates
6. **Reply `[SILENT]`** if nothing is worth capturing

## Pitfalls

- **Don't capture every session** — the `tool_call_count > 3` filter is
  essential. Without it, the precheck emits 20+ sessions per day and the LLM
  burns tokens reviewing casual chats.
- **Don't use `created_at`** — the column doesn't exist. Use `started_at` (REAL).
- **Don't forget `session_search` in toolsets** — without it the LLM can't
  read session content and the job is useless.
- **Dedup is critical** — without session_id dedup, the same sessions appear
  every day until the LLM processes them. The seen-state file prevents this.
- **Seen-state file format** — `cron/state/session_wiki_seen.json` is a dict
  with a `"seen"` key containing a list of session IDs, NOT a flat list:
  ```json
  {"seen": ["20260621_101623_7de2cdee", "20260622_041824_eeb4b5f8", ...]}
  ```
  When updating, read `data["seen"]`, append new IDs, prune to max 2000
  (keep newest), and write back the full dict. Calling `.append()` on the
  parsed dict directly raises `AttributeError` — always access the `"seen"` key.
- **Subagent sessions ARE included** — `source NOT IN ('cron', 'scheduler')`
  allows `subagent` source, which is correct — subagents often do focused work
  worth capturing.
- **Prefer updating existing pages over creating new ones** — when session
  content extends an existing topic (e.g., new implementation work on the
  approval engine), enrich the existing page rather than creating a new one.
  Only create a new page when the session introduces a genuinely new entity,
  concept, or comparison that doesn't fit under any existing page. This keeps
  the wiki from fragmenting into session-level artifacts.
- **QA/analysis artifacts are SKIP candidates** — sessions that produce test
  gap analyses, design review verification reports, or other one-time QA
  artifacts should be skipped. They're valuable in the moment but become stale
  quickly and don't represent durable knowledge. The design review itself may
  be wiki-worthy (as a concept page), but the verification that a plan was
  executed correctly is not.
- **Plan files are the source of truth for subagent sessions** — when
  multiple subagent sessions all execute the same implementation plan (e.g.,
  `2026-06-26_deepseek-review-fixes.md`), read the plan file directly rather
  than reconstructing from session transcripts. The plan tells you what was
  implemented; session_search gives you context and confirmation. This is
  faster and more accurate than reading every subagent transcript.