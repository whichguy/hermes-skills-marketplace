---
name: session-wiki-capture
description: 'Cron job that reviews Hermes conversation history and captures durable knowledge into the wiki. Handles triage (SKIP/NOTE/PAGE), Slack-session cleanup, and post-capture lint.'
version: 1.0.0
author: Hermes Agent
license: MIT
platforms:
- linux
- macos
metadata:
  hermes:
    tags:
    - wiki
    - cron
    - session-capture
    - knowledge-base
    category: note-taking
    related_skills:
    - llm-wiki
    - script-first-cron-design
---

# Session-to-Wiki Capture

Cron job that reviews Hermes conversation history and captures durable knowledge
into the wiki. This is the third ingest pipeline (alongside URL queue and email),
closing the gap where valuable conversation knowledge — config changes, debugging
insights, architecture decisions — was lost because no mechanism captured it.

## When This Skill Activates

Use this skill when:
- Setting up or troubleshooting the session-to-wiki capture cron job
- Running a manual session-to-wiki capture (user asks "capture recent sessions")
- The capture cron fails or produces unexpected results
- You need to understand the session DB schema, precheck script, or triage logic

## Architecture

```
session_wiki_precheck.py  (precheck script)
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
chat. Sessions with 4+ tool calls involved real work — debugging, config changes,
file operations — that's worth reviewing for wiki-worthy knowledge.

## Cron Job Configuration

```yaml
name: Session-to-wiki capture
schedule: 0 7 * * *    # daily at 7AM UTC
model: glm-5.2:cloud   # GLM-5.2 — requires judgment to decide what's wiki-worthy
script: session_wiki_precheck.py
skills: [note-taking/session-wiki-capture, research/llm-wiki]
enabled_toolsets: [terminal, file, session_search, skills]
deliver: origin
```

**Why GLM-5.2, not Haiku?** The LLM must read session content and make judgment
calls: is this a one-off chat (SKIP), a fact to add to an existing page (NOTE),
or a new entity/concept worth its own page (PAGE)? That's synthesis, not formatting.
Originally designed for Sonnet; switched to GLM-5.2 as part of the full migration
off Anthropic. Triage quality has been adequate (17 runs, 3 pages created, 15+
pages updated). Monitor and switch back if triage quality degrades.
The original design used Sonnet for judgment quality. As of 2026-07, GLM-5.2:cloud
is the active model and producing adequate results. If triage quality degrades
(missed pages, wrong SKIP decisions), switch back to Sonnet for a trial period.

**Skills config:** The `skills` array MUST include `note-taking/session-wiki-capture`
(not `ask`). The `ask` skill is a model-dispatch library — loading it here wastes
~107KB of context per run. This is a common copy-paste error from other cron jobs
(morning-brief, followup-sweep) that legitimately use `ask` for model dispatch.
Double-check the skills array when creating or updating this cron job.

**`enabled_toolsets`:** Restrict to `[terminal, file, session_search, skills]`.
The agent doesn't need web, browser, delegation, or other toolsets — they add
unnecessary token overhead. `session_search` is critical (without it the agent
can't read session content).

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

## Triage Decision Guide

- **SKIP** — casual chat, throwaway coding exercises, QA/analysis artifacts
  (test gap analyses, design review verification reports), sessions already
  captured in existing wiki pages
- **NOTE** — new fact to add to an existing page (bug fix detail, config change,
  new person/contact for an existing entity)
- **PAGE** — new entity, concept, or comparison that doesn't fit under any
  existing page

**Prefer updating existing pages over creating new ones.** When session content
extends an existing topic, enrich the existing page. Only create a new page when
the session introduces a genuinely new entity, concept, or comparison.

## Post-Capture Cleanup (CRITICAL — Slack Sessions)

Slack sessions (source=`slack`) can create wiki pages via `write_file` or
`mcp__wiki__write_file` that **bypass the standard ingest workflow**. These
pages often lack YAML frontmatter, aren't added to `index.md`, and may contain
broken wikilinks.

After any session-to-wiki capture run that processes Slack sessions, **always**
run this cleanup:

### Step 1: Run the lint script

```bash
python3 /opt/data/scripts/wiki_lint.py
```

This surfaces: missing frontmatter, broken wikilinks, orphan pages, index
completeness issues.

### Step 2: Add frontmatter to Slack-created pages

```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: concept | entity | comparison
tags: [from SCHEMA.md taxonomy]
sources: []
---
```

### Step 3: Fix broken wikilinks

Common stale references from Slack sessions:
- `[[updated-execution-plan]]` → `[[multi-model-dev-pipeline-design]]`
- Any link that doesn't resolve to an existing page slug

### Step 4: Add new pages to index.md

Under the correct section (Entities, Concepts, Comparisons), alphabetically.

### Step 5: Verify index count

The header's "Curated pages: N" must match the actual `- [[` wikilink count.
Use `grep -c '^- \[\[' /opt/data/wiki/index.md` to get the actual count.

### Step 6: Verify qmd index

```bash
qmd collection list
```

The wiki collection auto-updates when files change. Verify "Updated: Ns ago"
is recent. If it hasn't updated within a minute, force a full reindex:
`qmd collection remove wiki && qmd collection add wiki wiki/`

This cleanup is cheap (~2min) and prevents the wiki from silently degrading
every time a Slack session contributes content.

## Pitfalls

- **Two-tier state model (fetched/triaged)** — the precheck uses a two-tier
  state model to prevent silent data loss on LLM crash:
  - `fetched`: sessions emitted by precheck (safe to skip re-querying DB)
  - `triaged`: sessions the LLM has confirmed processing via merge file
  - On LLM crash: sessions stay in `fetched` only → re-emitted next run
  - Merge file: `$HERMES_HOME/cron/state/session_wiki_seen_new.json` — the LLM
    writes processed session IDs here after each run. The precheck merges this
    into `triaged` on the next run.
  - Legacy `{"seen": [...]}` format auto-migrates (treats all as both fetched + triaged)
  - This is the same pattern proven in the email-wiki-ingest pipeline.
- **`message_count > 10` filter (cli/subagent only)** — the precheck SQL query
  requires `message_count > 10` **only for `cli` and `subagent` sources**.
  User-facing sessions (`slack`, `telegram`, `whatsapp`, `email`) are always
  included when `tool_call_count > 3` — short but dense conversations (e.g. a
  4-message Telegram exchange with 3 tool calls) are often wiki-worthy. The
  message_count filter targets ephemeral subagent worker sessions (typically
  5-8 messages: read spec, write file, verify) while preserving substantive
  user conversations. Don't remove this without measuring the SKIP rate impact.
- **Don't capture every session** — the `tool_call_count > 3` + `message_count > 10`
  filters are essential. Without them, the precheck emits 20+ sessions per day
  and the LLM burns tokens reviewing casual chats and ephemeral workers.
- **Don't use `created_at`** — the column doesn't exist. Use `started_at` (REAL).
- **Don't forget `session_search` in toolsets** — without it the LLM can't
  read session content and the job is useless.
- **Dedup is critical** — without session_id dedup, the same sessions appear
  every day until the LLM processes them.
- **Seen-state file format** — `cron/state/session_wiki_seen.json` now uses
  two-tier format:
  ```json
  {"fetched": ["id1", "id2", ...], "triaged": ["id1", "id2", ...]}
  ```
  Legacy `{"seen": [...]}` format auto-migrates on first load (all IDs treated
  as both fetched + triaged). The merge file `session_wiki_seen_new.json` is
  written by the LLM after processing and merged into `triaged` on next run.
  Prune to max 2000 per tier (keep newest).
- **State-save-before-triage: silent data loss bug** — the precheck script
  marks sessions as `seen` BEFORE the LLM processes them. If the LLM crashes
  or the cron run fails, those sessions are permanently excluded from future
  runs. The 48h lookback does NOT mitigate this — once a session ID is in
  `seen`, it's filtered out on every subsequent run regardless of age. Fix:
  apply the two-tier state model (`fetched` / `triaged`) from the
  email-wiki-ingest pipeline. Precheck adds to `fetched` only; LLM confirms
  processing by writing to a merge file; precheck merges into `triaged` on
  next run. Sessions in `fetched` but not `triaged` get re-emitted. Legacy
  `{"seen": [...]}` format auto-migrates on first load (treat all as both
  fetched + triaged).
- **Subagent sessions ARE included** — `source NOT IN ('cron', 'scheduler')`
  allows `subagent` source, which is correct — subagents often do focused work
  worth capturing.
- **High SKIP rate is expected (~80-90%)** — most flagged sessions are subagent
  workers doing ephemeral implementation work. This is normal and acceptable
  given the low absolute volume (max 10 sessions/day). If token cost becomes a
  concern, add `AND message_count > 10` to the SQL query to filter out short
  worker sessions (read spec, write file, done — typically 5-8 messages). Do
  NOT blanket-exclude `source = 'subagent'` or `source = 'cli'` — both can
  produce wiki-worthy content.
- **Wrong skill loaded: `ask` instead of `session-wiki-capture`** — a common
  copy-paste error from other cron jobs (morning-brief, followup-sweep) that
  legitimately use `ask` for model dispatch. Loading `ask` here wastes ~107KB
  of context per run and the agent never sees the session-wiki-capture skill's
  critical guidance (post-capture cleanup, Slack-session handling, log.md edit
  corruption warnings). Always verify the cron job's `skills` array includes
  `note-taking/session-wiki-capture` and does NOT include `ask`.
- **Plan files are the source of truth for subagent sessions** — when
  multiple subagent sessions all execute the same implementation plan, read
  the plan file directly rather than reconstructing from session transcripts.
- **QA/analysis artifacts are SKIP candidates** — test gap analyses, design
  review verification reports, and other one-time QA artifacts should be
  skipped. They're valuable in the moment but become stale quickly.
- **Slack sessions create pages outside the normal workflow** — always run
  the post-capture cleanup after processing Slack sessions. See "Post-Capture
  Cleanup" section above.
- **Index page count drifts** — after adding pages to the index, always
  verify the header count matches. The count in the header is manually
  maintained and easy to forget to update.
- **Re-index qmd after capture** — the wiki collection auto-updates when
  files change (verify with `qmd collection list` — look for "Updated: Ns
  ago"). After writing/editing wiki pages, run `qmd update` to refresh the
  BM25 keyword index (fast, ~1s). Then run `qmd embed` in the background
  to refresh vector embeddings (slower, ~30s for 5 new hashes). Both
  commands exist and are the standard reindex workflow. If the collection
  hasn't auto-updated within a minute, fall back to
  `qmd collection remove wiki && qmd collection add wiki wiki/` to force
  a full reindex.
- **Large session_search results go to temp files** — when a session has
  many messages (100+), `session_search` may persist the result to
  `/tmp/hermes-results/call_<id>.txt` instead of returning it inline. The
  tool output will show a preview and the file path. Use `read_file` with
  `offset` and `limit` to read specific sections. For very large sessions
  (200+ messages), read the first 50 lines first to understand the topic
  before deciding whether to read the full transcript.
- **log.md edit corruption when inserting between entries** — when using
  `mcp_wiki_edit_file` to insert a new log entry between two existing
  entries, the `oldText`/`newText` replacement can leave orphaned text
  from the prior entry if the match boundary isn't precise. Always verify
  the result with `read_text_file` on the affected lines. If orphaned text
  appears, use the `patch` tool (not `mcp_wiki_edit_file`) for the fix —
  it has better fuzzy matching. When constructing the `oldText` for a
  log.md insertion, include the full header line of the next entry (e.g.
  `## [2026-06-29] update | ...`) as the boundary marker to prevent the
  replacement from eating into adjacent entries.
- **`mcp__wiki__edit_file` exact-match failures** — when an edit
  returns "Could not find exact match", the file's actual text differs
  from what you provided. Common causes: `**bold**` markers, backtick
  formatting, trailing whitespace, or smart quotes. Recovery: use
  `search_files` with `pattern` to find the exact line, then copy it
  verbatim into `oldText`. Do NOT guess — every character must match.
  This is especially common when editing pages that were created by
  Slack sessions (which may have different formatting conventions).
  The `edits` parameter requires `[{"oldText": "...", "newText": "..."}]`,
  not a bare string. Passing a string produces a JSON validation error
  (`expected object, received string`). Wrap every edit in an array, even
  single-edit calls.
- **`session_search` scroll fails on wrong message_id** — when
  `around_message_id` isn't in the target session, the call returns
  `{"error": "around_message_id N not in session_id ..."}`. Recover by
  trying a different message ID from the discovery results (e.g. the
  `match_message_id` or an adjacent ID). The `messages_before`/
  `messages_after` counts from discovery tell you how close you are to
  the session boundary.
- **Post-capture cleanup: edit-only runs still benefit from lint** — the
  full cleanup (frontmatter, wikilinks, index, qmd) is most critical when
  NEW pages are created via `write_file`. When only editing existing pages
  (which already have proper frontmatter), a lighter pass — at minimum
  running `python3 /opt/data/scripts/wiki_lint.py` — catches any stale
  wikilinks or index drift introduced by the edits. Don't skip it entirely.
- **Tool choice: `patch` for non-wiki files, `mcp__wiki__edit_file` for wiki files** —
  the `patch` tool works on any file in the filesystem and has fuzzy matching
  (9 strategies). Use it for files outside the wiki directory (e.g.
  `post-response-suggestion-block-plan.md` in the root). The `mcp__wiki__edit_file`
  tool only works within the wiki MCP server's allowed directories and requires
  exact text matches. When editing wiki pages, prefer `mcp__wiki__edit_file` for
  its structured diff output; fall back to `patch` if exact-match failures persist.
- **`read_file` with offset/limit triggers `patch` partial-read warning** — when
  you read a file with `offset`/`limit` (partial view) and then use `patch` on it,
  `patch` warns: "was last read with offset/limit pagination (partial view). Re-read
  the whole file before overwriting it." This is a soft warning — the edit still
  succeeds — but it means you're operating on incomplete context. For small files
  (<300 lines), always read the full file before patching. For large files, read
  the full file once to understand structure, then use offset/limit for targeted
  reads of specific sections you plan to edit.

## Related

- `llm-wiki` skill — the wiki architecture, ingest workflow, and lint procedures.
  **Note:** this skill may not be installed. If the cron job lists it in `skills:`
  and it's missing at runtime, the agent will see a warning — proceed without it;
  the `session-wiki-capture` skill is self-contained and covers the full workflow.
- `script-first-cron-design` skill — cron job design patterns
- `references/session-to-wiki-capture.md` in the `llm-wiki` skill — original
  reference document (bundled, may be slightly older than this skill)
