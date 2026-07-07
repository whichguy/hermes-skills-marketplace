---
name: open-threads
description: |
  Scan recent Hermes conversations for threads that paused with something pending.
  Lets the user ask "what's open?" to see dangling/active threads, resume a thread
  with a "previously on..." digest, or dismiss threads they're done with.
  Use when the user says: "what's open", "resume", "what was I working on",
  "dismiss [topic]", "close [topic]", or similar.
---

# Open Threads

Scan recent conversations for threads that paused with an unfulfilled commitment,
and help the user jump back in or dismiss them.

## Trigger Phrases

- "what's open?" / "what's open" / "what was I working on?"
- "resume [topic]" / "resume [session_id]"
- "summarize [topic]" / "summarize [session_id]" — lighter than resume: generates a refresher summary without jumping back in
- "dismiss [topic]" / "close [topic]" / "done with [topic]"
- "reopen [topic]"

## Workflow

### Step 1: Run the scanner

```bash
python3 -B ${HERMES_HOME}/scripts/open-threads-scan.py
```

This queries the session DB and outputs JSON with:
- `active[]`: sessions interrupted mid-action (🟢)
- `dangling[]`: sessions with proposed actions you never confirmed (🟡)
- `ambiguous[]`: sessions needing LLM classification (assistant last spoke, no clear signal)
- `completed_count`: number of resolved sessions (not listed individually)

### Step 2: Classify ambiguous sessions

For each session in `ambiguous[]`, read its `bookend_end` (last 3 messages) and
classify as OPEN or CLOSED:

**OPEN** if the last assistant message:
- Proposes a specific next action ("want me to...", "shall I...", "let me check...")
- Asks a question the user hasn't answered
- Raises an issue or finding the user hasn't acknowledged

**CLOSED** if the last assistant message:
- Provides a complete answer with no follow-up expected
- Uses resolution language ("done", "complete", "that's it")
- Is a factual statement with no call to action

Move OPEN items to `dangling`, CLOSED items to `completed_count`.

### Step 3: Format output with next best action

Present active and dangling sessions grouped by status. For each session show:
- Title (bold)
- One-line description of what's pending (from `reason` + `last_content`)
- **Next action** — extracted from `next_action` field (the specific thing Hermes was
  about to do or proposed doing). This is the key addition — it tells Jim *what to do*
  not just *what's open*.
- Age (how long ago the last message was)
- Message count
- **📎 View thread** — hyperlink if `deep_link` is present (Slack deep link to original thread)
- SUGGESTION buttons: **Resume** (`resume [session_id]`) and **Dismiss** (`dismiss [session_id]`)
- If `next_action` is present, add a third SUGGESTION button with the action as the
  `next` field so Jim can one-click execute it: `resume [session_id] and [next_action]`

Format for Slack with rich markdown. Example:

```
⏰ Open Threads (3 needing attention)

🟢 Active — interrupted mid-action

**Gateway Shutdown and Session Restoration** · 0.2h ago · 156 msgs
Agent was mid-execution when session closed.
→ Next: Verify the suggestion-stripper hook loads on gateway restart
📎 [View thread](https://slack.com/archives/...) 

🟡 Dangling — proposed action not confirmed

**Hermes Parallel Agent Execution** · 22h ago · 52 msgs
Proposed setting timezone to America/Los_Angeles. Never confirmed.
→ Next: Set timezone to America/Los_Angeles
📎 [View thread](https://slack.com/archives/...)

━━━━━━━━━━━━━━━━━━━━━━━━━━
19 other sessions this week are complete ✅

Say "resume [topic]" to jump back in, or "dismiss [topic]" to close a thread.
```

**Next action extraction rules:**
- If `next_action` field is populated in scanner output, use it directly (prefixed with →)
- If `next_action` is None, infer from `last_content` and `reason`:
  - For SUGGESTION markers: extract the `next` field from the SUGGESTION JSON
  - For "let me X" / "I'll X": strip the prefix → "X"
  - For incomplete/compression: "Continue: [last action being attempted]"
  - For stale dangling: suggest "Revisit or dismiss — this is [age]h old"
- Keep next actions to one line, max 80 chars. Actionable, not descriptive.

### Step 3a: Emit SUGGESTION button for most urgent next action

After formatting the thread list, emit ONE SUGGESTION marker at the end of the
response for the most urgent actionable next step. Pick the thread that is:
1. Most recent (lowest age_hours)
2. Has a populated `next_action` field
3. The action is something Hermes can execute (can_do: true)

Format:
```
SUGGESTION:{"next": "resume [session_id] and [next_action]", "reason": "[why this is the most urgent]", "can_do": true}
```

If no thread has an executable next action, emit a SUGGESTION with can_do: false
suggesting the user pick a thread to resume or dismiss.

### Step 3b: Per-thread action labels

Each thread in the output shows three text commands the user can type:
- `summarize [topic]` — get a refresher summary (default, lightest touch)
- `resume [topic]` — jump back in with full context loaded
- `dismiss [topic]` — close the thread

Only the MOST URGENT action gets a clickable SUGGESTION button at the end.
The rest are text commands. This matches the SUGGESTION framework's one-marker-per-response design.

If no active or dangling sessions: respond with a brief confirmation.

### Step 4: Handle summarize

When the user says "summarize [topic]" or clicks a Summarize button:

1. Match the topic to a session_id (by title fuzzy match, or direct ID)
2. Load session context via `session_search(session_id=old_id)` — gets bookend_start + bookend_end
3. Also load a middle window via `session_search(session_id=old_id, around_message_id=X)` if more context needed
4. Generate a refresher summary using GLM-5.2:

```
📋 Summary: [session title]
   ([N] messages · [age]h ago · [View original thread](deep_link) if available)

━━━ What you discussed ━━━
[2-3 sentence summary of the topic and arc]

━━━ Key actions taken ━━━
- [action 1]
- [action 2]
- [action 3]

━━━ Where it stopped ━━━
[Last meaningful exchange, abbreviated]

━━━ What's left ━━━
- [pending item 1] (if any)
- [pending item 2] (if any)

Say "resume [topic]" to jump back in, or "dismiss [topic]" to close this thread.
```

5. This is NOT a resume — the current session context is unchanged. The user
   gets a refresher and can decide whether to resume, dismiss, or do nothing.

### Step 5: Handle resume

When the user says "resume [topic]" or clicks a Resume button:

1. Match the topic to a session_id (by title fuzzy match, or direct ID if provided)
2. Load the session's `bookend_start` and `bookend_end` from the scanner output
   (or re-run scanner if not cached)
3. Generate a "Previously on..." digest using GLM-5.2:

```
📎 Resuming: [session title]
   (Loaded N messages of context · [View original thread](deep_link) if available)

━━━ You were trying to ━━━
[1-2 sentence summary of the goal, from bookend_start]

━━━ What happened ━━━
[1-2 sentence arc summary, inferred from title + message count + bookends]

━━━ Where it paused ━━━
[Last meaningful exchange, abbreviated from bookend_end]

━━━ Pick up ━━━
[Specific next action if identifiable, or "What would you like to do?"]
```

4. Also suggest: `Type /resume [title] for full session restoration` (gateway command
   that re-points the current session at the old session, loading full transcript)

5. Keep the old session_id in context for lazy-loading. If the user asks a follow-up
   that needs more history, use `session_search(session_id=old_id, around_message_id=X)`
   to pull additional context.

### Step 6: Handle dismiss

When the user says "dismiss [topic]" or clicks a Dismiss button:

1. Match topic to session_id
2. Write to dismissal DB:

```bash
python3 -B -c "
import sqlite3, time
conn = sqlite3.connect('${HERMES_HOME}/open-threads.db')
conn.execute('''CREATE TABLE IF NOT EXISTS dismissed_sessions
    (session_id TEXT PRIMARY KEY, topic TEXT, dismissed_at REAL, expires_at REAL)''')
conn.execute('INSERT OR REPLACE INTO dismissed_sessions VALUES (?,?,?,?)',
    ('SESSION_ID', 'TOPIC', time.time(), time.time() + 7*86400))
conn.commit(); conn.close()
"
```

3. Confirm: "👍 Marked '[title]' as resolved. Won't surface it again. (Say 'reopen [topic]' if you change your mind.)"

### Step 7: Handle reopen

When the user says "reopen [topic]":

1. Match topic to session_id
2. Remove from dismissal DB:

```bash
python3 -B -c "
import sqlite3
conn = sqlite3.connect('${HERMES_HOME}/open-threads.db')
conn.execute('DELETE FROM dismissed_sessions WHERE session_id=?', ('SESSION_ID',))
conn.commit(); conn.close()
"
```

3. Confirm: "👍 Reopened '[title]'. It'll show up in future scans."

## Platform-Specific Notes

- **Slack**: Deep links (`slack.com/archives/{channel}/{thread_ts}?team={team_id}`)
  open the original thread. The `deep_link` field in scanner output contains this.
- **Telegram**: No deep links available. Show Resume/Dismiss as text suggestions.
- **WhatsApp**: No deep links or buttons. Pure text: "Say 'resume [topic]' to continue."
- **TUI**: `/resume [title]` works directly. Deep links not clickable.

## Configuration

- Recency window: 72 hours (configurable in scanner script)
- Dismissal auto-expiry: 7 days
- Min messages to classify: 5 (quick Q&A is auto-completed)
- Scanner script: `${HERMES_HOME}/scripts/open-threads-scan.py`
- Dismissal DB: `${HERMES_HOME}/open-threads.db`
- Session DB: `${HERMES_HOME}/state.db`
- Session routing: `${HERMES_HOME}/sessions/sessions.json`

## How Deep Links Are Constructed

Slack deep links (`https://slack.com/archives/{channel_id}/{thread_ts}?team={team_id}`)
are built from session origin data. The routing chain:

1. **`sessions.json`** (`${HERMES_HOME}/sessions/sessions.json`) maps session keys to
   active session entries. Each entry has an `origin` dict with `chat_id` (Slack
   channel ID) and `thread_id` (Slack `thread_ts` — the parent message timestamp).
2. **Session key format** for Slack DMs: `agent:main:slack:dm:{chat_id}:{thread_id}`
   — the `thread_id` segment IS the Slack `thread_ts`.
3. **Reset/replaced sessions** may not be in `sessions.json`. The scanner walks
   `parent_session_id` chains (both up to parents and down to children) to find
   a related session that IS in `sessions.json`, then uses its origin (same thread).
4. **Some sessions have no origin anywhere** in their chain (fully pruned). In that
   case `deep_link` is null — show Resume/Dismiss without the View Thread link.
5. **`platform_message_id` column is always empty** in the Hermes session DB —
   the Slack adapter doesn't persist Slack message timestamps there. Deep links
   can ONLY be constructed from `sessions.json` origin data, not from the DB directly.
6. **Team ID** is hardcoded as `YOUR_SLACK_TEAM_ID` in the scanner (configurable via
   `SLACK_TEAM_ID` env var).

See `references/session-db-internals.md` for full schema and routing details.

## Native `/resume` Command

The gateway has a built-in `/resume` slash command that switches the current
session to point at an old session — loading the full transcript as native history.

- `/resume` — lists recent titled sessions (numbered)
- `/resume [title]` — fuzzy match by title
- `/resume [session_id]` — direct ID lookup
- `/resume 3` — resume session #3 from the list

Internally calls `SessionStore.switch_session(session_key, target_session_id)`
which re-points the session key at the old session ID, evicts the cached agent,
and reopens the old session in the DB. The next message rebuilds with full context.

The open-threads skill's resume flow is **agent-level** (loads context via
`session_search` into the current conversation, generates a digest). For
**gateway-level** full session restoration, suggest the user type `/resume [title]`.

## Abandon Threshold

Sessions with pending action language but older than **48 hours** are classified
as `completed` (likely abandoned). Only sessions <48h with pending actions are
surfaced as `dangling`. This prevents surfacing old threads the user has moved on from.

## Morning Briefing Cron

A cron job (`YOUR_CRON_JOB_ID`) runs daily at 8am and delivers the open-threads briefing
to the user's home channel (Slack DM by default).

- **Script**: `${HERMES_HOME}/scripts/open-threads-scan.py` (runs first, output injected as context)
- **Cron `script` field**: `open-threads-scan.py` — bare filename only. The cron runner resolves it under the scripts directory. A full command like `python3 -B ${HERMES_HOME}/scripts/open-threads-scan.py` will fail because the runner treats the entire string as a filename, producing `Script not found: ${HERMES_HOME}/scripts/python3 -B ${HERMES_HOME}/scripts/open-threads-scan.py`. See `script-first-cron-design` Pitfall #7 for both failure variants.
- **LLM**: GLM-5.2 (classifies ambiguous sessions + formats briefing)
- **Delivery**: `origin` (Slack DM), `attach_to_session: true` (replies continue in context)
- **Silent**: if zero active/dangling sessions, output "SILENT" (no message sent)
- **Skills**: loads `open-threads` skill for formatting rules

### Cron prompt structure
The cron prompt instructs the LLM to:
1. Read the scanner JSON output (injected as context from the script)
2. Classify ambiguous sessions as OPEN or CLOSED
3. If zero open threads → output "SILENT"
4. If open threads exist → format the briefing with deep links + next actions + SUGGESTION buttons

## Chain Collapse

Multiple sessions can belong to the same conversation thread (via resets, compressions,
and `/new` within a thread). The scanner collapses these by walking `parent_session_id`
chains to find the root session, grouping by root, and keeping only the **latest** session.
This prevents showing 3 "Fix WhatsApp Bot Pairing Code #1/#2/#3" entries when they're
all the same thread. The `collapsed_count` field in scanner output shows how many were
collapsed. See `references/session-db-internals.md` for the full chain-walking logic.

## Next Best Action Extraction

Each surfaced thread includes a `next_action` field — the specific thing Hermes was about
to do or proposed doing. This tells Jim *what to do*, not just *what's open*.

- **SUGGESTION markers**: extract the `next` field from the SUGGESTION JSON
- **Pending action phrases**: "Let me check the git state" → "check the git state"
- **Incomplete/compression**: last non-empty assistant content (truncated to 150 chars)
- **Stale dangling (>24h)**: "Revisit or dismiss — this is [age]h old"
- **None available**: infer from `last_content` and `reason` in the LLM step

The LLM step (skill or cron) cleans up the raw extraction into a readable action phrase
prefixed with `→ **Next:**` in the formatted output.

## Flow Validation (2026-06-27)

The full flow was validated from scanner → agent → SUGGESTION marker → Block Kit button:

### Working paths ✅
1. **Interactive sessions** (gateway running): `GatewayStreamConsumer._send_or_edit` is patched
   by the suggestion-stripper hook. SUGGESTION markers are stripped during streaming and
   rendered as Block Kit buttons. Verified in debug logs.
2. **Cron delivery via live adapter** (gateway running): `adapter.send` is patched on the
   instance. SUGGESTION markers are extracted and buttons are sent as separate messages.

### Fixed issues 🔧
1. **Cron prompt told agent to emit per-thread SUGGESTION markers** — only ONE SUGGESTION
   per response is supported (the regex extracts only the last one at end-of-string).
   Fixed: removed per-thread SUGGESTION instruction, kept single end-of-response marker
   for the most urgent actionable thread.
2. **Standalone Slack sender didn't strip SUGGESTION** — when cron delivery falls back
   to the standalone path (event loop not running, adapter unavailable), the
   `standalone_sender_fn` bypassed the hook. Fixed: wrapped `standalone_sender_fn` in
   `_patch_platform_registry()` to strip SUGGESTION and send Block Kit buttons.

### Known limitations ⚠️
1. **Hook not loaded → no stripping**: If the gateway is completely down, the hook
   doesn't load at all. The standalone sender patch only works when the hook IS loaded
   (i.e., when the gateway process is running, even if the event loop is stuck).
2. **Multiple SUGGESTION markers**: Only the LAST marker at end-of-string is extracted.
   Any earlier markers in the text are stripped as partial markers (no button rendered).
3. **SOUL.md conflict**: SOUL.md says "Never include SUGGESTION in cron sessions" but
   the open-threads cron intentionally emits one for the most urgent action. This is
   acceptable because the hook strips it and renders a button — the user never sees
   raw JSON. If the hook fails, the raw text is still visible (degraded but functional).

## Pitfalls

- **`finish_reason: tool_calls` is NOT a true interruption signal**: The gateway
  kills the agent process after every response. `tool_calls` just means the agent
  was mid-tool-call when the process exited. This happens on most sessions.
  The scanner classifies `tool_calls + empty content` as `completed` (normal shutdown).
  Only `finish_reason: incomplete` (response was cut off) is treated as active.
- **Resolution language must be checked BEFORE SUGGESTION markers**: A session that
  says "Everything is done. ✅ All Done — Here's Your Status" but has a trailing
  `SUGGESTION:{...}` marker is completed, not dangling. The scanner checks resolution
  patterns first.
- **Chain collapse is needed to avoid noise**: Without it, the same WhatsApp pairing
  saga shows up as 3-4 separate active sessions (all from the same thread, linked via
  `parent_session_id`). The scanner walks chains and keeps only the latest.
- **Empty bookend_end messages**: Some sessions have tool-call-only messages as the
  last entries (empty content). Use the last non-empty message for classification.
- **Session not in sessions.json**: Old sessions that were reset may not have origin
  data. The scanner walks parent/child chains to find a related session with origin
  info, but some chains are fully gone. In that case, `deep_link` is null.
- **`end_reason: agent_close` is the normal shutdown** — every session gets this
  when the gateway kills the agent between messages. Only `compression` and
  `session_reset` are true disruption signals.
- **`platform_message_id` is always NULL** in the session DB — the Slack adapter
  doesn't persist message timestamps there. Deep links can ONLY be constructed
  from `sessions.json` origin data, not from the DB directly.