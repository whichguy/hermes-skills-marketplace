# WhatsApp Schedule Subscriber Notification System

**Established:** 2026-06-23 session · **Status:** v1 scripts built + cron jobs active; v4 Skills Hub plan with 5-layer architecture in design

## Evolution

1. **v1 (deployed):** 3 no-agent cron scripts + shared lib, hardcoded to Jim's deployment
2. **v2:** Plan for public skill with config separation
3. **v3:** Skills Hub conventions added (prerequisites, setup.py, self-contained)
4. **v4 (current plan):** 5-layer architecture with ABAC access control. Plan at `.hermes/plans/2026-06-23_abac-subscription-system.md`

## v1 — What's deployed now

Three no-agent cron scripts read the Google Sheet via `usaw_to_lib.py`, filter
to each subscriber's scope, and DM them via the Baileys bridge REST API.

```
subscribers.json  ←  agent edits (subscription conversation)
       ↓
to_subscriber_changes.py    (every 15min)  → DM per subscriber with their changes
to_subscriber_briefing.py   (daily 6AM MT) → DM per subscriber with today+tomorrow
to_subscriber_reminder.py   (every 15min)  → DM 15min before earliest duty
       ↓
Baileys bridge localhost:3000/send {"chatId":"<phone>@c.us","message":"<text>"}
```

All three crons: `no_agent: true`, `deliver: local` (DMs are the output, not stdout).

### Subscriber registry

File: `/opt/data/cron_state/usaw_to/subscribers.json`

Scope types:
- `{"type":"self"}` — only changes/assignments matching subscriber's name
- `{"type":"named","names":["Name1","Name2"]}` — specific people
- `{"type":"all"}` — everything (same as WhatsApp group)

Name matching: case-insensitive, strips parenthetical cert tags (`(NAT)`, `(IWF 1)`).

### Subscription flow (agent-native)

1. TO messages the bot (must be on WhatsApp allowlist — added manually)
2. Agent recognizes non-Jim sender → enters subscription mode
3. Asks: "What name(s) should I monitor? Reply with your name, specific people, or 'all'"
4. TO replies → agent matches against sheet via `to_subscriber_lib.verify_name_on_sheet()`
5. Agent updates `subscribers.json`, sends confirmation DM
6. "stop" → unsubscribe, "status" → current subscription info

**Privacy guards:** agent handles ONLY subscribe/unsubscribe/status for non-Jim
senders. Never shares personal data, calendar, email, or memory contents.

### v1 files

| File | Purpose |
|------|---------|
| `scripts/to_subscriber_lib.py` | Subscriber registry, DM sending, name matching, scope filtering |
| `scripts/to_subscriber_changes.py` | Personalized change alert DMs (every 15min) |
| `scripts/to_subscriber_briefing.py` | Daily assignment briefing DMs (6 AM MT) |
| `scripts/to_subscriber_reminder.py` | 15-min pre-duty reminder DMs (every 15min) |
| `cron_state/usaw_to/subscribers.json` | Subscriber registry |
| `cron_state/usaw_to/subscriber_last_revision.json` | Change detection state (separate from existing watcher) |
| `cron_state/usaw_to/subscriber_reminders_sent.json` | Reminder dedup state |

### v1 cron jobs

| Job | Schedule | Script |
|-----|----------|--------|
| TO Subscriber Change Alerts | `*/15 * * * *` | `to_subscriber_changes.py` |
| TO Subscriber Daily Briefing | `0 12 * * *` (6 AM MT) | `to_subscriber_briefing.py` |
| TO Subscriber Pre-Duty Reminder | `*/15 * * * *` | `to_subscriber_reminder.py` |

## v4 — Skills Hub plan (5-layer architecture)

**Plan file:** `/opt/data/.hermes/plans/2026-06-23_abac-subscription-system.md`

Restructures v1 into a self-contained Skills Hub skill with 5 separable layers:

| Layer | Modules | Responsibility |
|-------|---------|---------------|
| L1: Drive | `drive_watcher.py` | Google Drive revision polling + download |
| L2: Sheet | `sheet_parser.py`, `sheet_differ.py`, `change_consolidator.py` | Parse sheet, diff revisions, consolidate changes |
| L3: Subscriptions | `subscriber_lib.py`, `abac.py` | Registry, scope filtering, ABAC policy engine |
| L4: Management | `approval.py`, `manager_ops.py` | Approval workflow, manager admin, audit trail |
| L5: Notification | `dm_sender.py`, `formatter.py` | WhatsApp bridge client, message templates |

**Key properties:**
- Layers 1-3 are pure leaf modules (zero cross-dependencies)
- Layer 4 imports only Layer 5
- Cron orchestrators are thin wiring (no business logic)
- Config in `config.yaml` (state dir) — no hardcoded deployment values
- Self-contained `sheet_parser.py` — no dependency on `usaw_to_lib.py`
- `setup.py` for first-run init (same pattern as google-workspace skill)
- ABAC: self-service subscribe, manager approval for actions affecting others

### ABAC model (attribute-based access control)

| Action | Who | Rule |
|--------|-----|------|
| Subscribe/change scope/unsubscribe (self) | Any number | `subject.phone == target.phone` → ALLOW |
| Same actions for another person | Anyone | → DENY_REQUEST_APPROVAL (managers notified) |
| Approve/reject requests | Managers only | `subject.is_manager` |
| List subscribers, add/remove manager | Managers only | `subject.is_manager` (can't remove self or last manager) |
| Broadcast to all | Manager | → needs 2nd manager approval |

State: `subscriptions.json` (subscribers + managers), `approval_queue.json`, `approval_log.json`

## Senior engineer review findings (v1 → fixed)

These bugs were found in a delegated senior engineer review and fixed in v1 scripts:

1. **`parse_assignments(names=[""])` returns `person=""`** — all-mode (names=None) added to return real person names. Critical: briefing/reminder scripts would never match without this fix.
2. **Missing `consolidate_changes()`** — subscriber change script didn't merge remove+add into "moved" lines. Fixed by importing from existing watcher.
3. **Silent DM loss on bridge failure** — `send_dm_or_queue()` + `failed_dms.json` retry queue added.
4. **Non-atomic state writes** — `_atomic_write()` (temp + rename) pattern added.
5. **Race on shared xlsx snapshot** — separate `subscriber_snapshot.xlsx` path (not shared with existing watcher).
6. **Verify subscriber names match sheet** — sheet uses "The User (NAT)", seed data was correct.

**Reusable lesson:** When a library function sets a field from a search parameter (not the actual data), calling it with an empty/wildcard parameter silently produces empty field values. Always verify that "get all" mode returns real data, not the query string.

## Critical pitfall: Baileys bridge /messages is destructive

The bridge's `GET /messages` endpoint uses JavaScript `splice()` — it drains the
queue. The Hermes gateway polls this continuously. A script polling `/messages`
would race with the gateway and steal messages. This is why subscription is
agent-native (gateway delivers messages to agent) not script-based (script polls
bridge). See SKILL.md "Baileys bridge /messages is destructive" section.

## Key design decisions (v1, carried into v4)

- **Separate state files** from existing watcher/reminder — no coupling
- **`deliver: local`** on all cron jobs — DMs are the delivery, not stdout
- **`send_dm_safe()`** with 3x retry + backoff for bridge hiccups
- **1s sleep between DMs** when looping subscribers (rate limit guard)
- **Event window guard** on all scripts (silent outside event dates)
- **Allowlist stays restricted** — TOs added manually as they request
- **Config separated from scripts** (v4) — `config.yaml` in state dir, no hardcoded values
- **ABAC for access control** (v4) — self-service subscribe, manager approval for cross-user actions

## Related

- `references/memory-pressure-watchdog.md` — QMD-aware memory watchdog
- Existing: `usaw_to_lib.py`, `usaw_to_reminder.py`, `usaw_to_change_watch.py`
- Wiki: `[[ncw-2026-to-logistics]]`
- Plan: `/opt/data/.hermes/plans/2026-06-23_abac-subscription-system.md`