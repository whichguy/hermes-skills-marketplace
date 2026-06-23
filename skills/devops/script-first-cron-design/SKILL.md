---
name: script-first-cron-design
description: Use when creating, updating, auditing, or troubleshooting Hermes cron
  jobs so deterministic checks run as scripts and LLM tokens are reserved for synthesis
  or judgment.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - cron
    - automation
    - no-agent
    - scripts
    - cost-control
    - privacy
    created_by: agent
    related_skills:
    - hermes-agent
    - scheduled-research-briefs
    - google-workspace
    config:
    - key: script-first-cron-design.enabled
      description: Enable script-first-cron-design skill behavior
      default: true
      prompt: Enable script-first-cron-design skill?
    category: devops
platforms:
- linux
- macos
- windows
---


# Script-First Cron Design

## Overview

Use a script-first design for recurring Hermes cron jobs. The goal is to make the cheapest, safest component decide whether anything needs to be said.

Reference patterns:

- `references/drive-briefing-precheck.md` — Drive/document candidate prechecks for synthesis briefs that must avoid speculative metadata-only summaries.
- `references/container-auto-update-guards.md` — Docker/Watchtower + no-agent guard pattern for daily auto-update checks that need host-side mutation and container-side verification.
- `references/cron-local-time-formatting.md` — Local-time formatting pattern for scheduled briefs/alerts that must avoid raw UTC/ISO timestamps in user-facing Telegram updates.
- `references/cron-message-house-style.md` — Shared pretty-formatting house style (emoji headers, dividers, clickable hyperlinks, status icons) plus the subprocess-dependency false-alarm pitfall and LLM-review-of-script-output pattern.
- `references/memory-pressure-watchdog.md` — `no_agent` Python reads MEMORY.md + USER.md, classifies entries by offload destination (wiki/skill/keep), fires review only above 85% threshold. QMD-aware: checks if semantic search is live before recommending wiki offload (safe vs needs-verification). Documents approved visuals/wording to keep vs trim.
- `references/cron-house-style-formatter.md` — Shared "pretty" house style for ALL cron output via one shared formatter module, not per-script hand-formatting.
- `scripts/cron_style.py` — Reusable formatter module (copy into the deployment scripts dir; `import cron_style as cs`). Provides `header/section/bullet/kv/link/local_time/now_label/render` + 🟢🟡🔴⚪ icon vocabulary.
- `references/notification-output-hygiene.md` — user-facing message quality: killing boilerplate/disclaimer footers, preventing internal-instruction leaks, mailbox emojis, descriptive hyperlinks, and retry-before-alert.
- `references/precheck-breadcrumb-enrichment.md` — Token-efficient metadata signals (skip_hint, urgency, age, domain, flags, compact snippet) that let the LLM triage WITHOUT fetching full thread bodies. ~40-60% API call reduction. Includes detection patterns, agent fast-path rules, cross-pipeline sharing, and testing.
- `references/script-precheck-llm-review-pretty.md` — Convert no-agent watchdogs to script→LLM-review→pretty-delivery: covers the empty-stdout skip, the `[SILENT]` marker, and the dependency-crash-misread-as-auth-failure fix.
- `references/daily-update-hyperlinks.md` — Clickable Markdown link pattern for daily briefs, cron updates, and script-only alerts.
- `references/cron-model-selection.md` — Haiku vs Sonnet decision rule + full audit of Jim's crons (Jun 2026): pure formatters → Haiku, synthesis/drafting/judgment → Sonnet. Also covers how to flip `no_agent` via jobs.json.
- `references/fixed-schedule-event-alerts.md` — One every-minute no-agent job driving deterministic time-based pings from a hardcoded (date, time, payload) list; timezone-aware minute matching; the bare-filename script-path requirement.
- `references/drive-revision-change-watcher.md` — (UPDATED Jun 2026) Two cooperating no-agent jobs against a Google Drive file: cheap-first `revisions().list()` polling, cell-level xlsx diff engine, scope signal, urgency, actor-centric alert phrasing, session grouping, age label (`Xm/Xh/Xd ago`), Drive revision pruning pitfall + safe fallback, /tmp isolated state dir rule, uv-reexec guard, raw Drive calls via `google_api.py`, monkeypatch-now test path. Two cooperating jobs (snapshot-driven reminder + hourly change-watcher) against a Google Drive file: `revisions().list()` for cheap change detection + editor name + full revision trail, `revisions_since()` slicer for walking all edits since last check, `last_checked_at` stamped on every tick, 3-tier precheck-LLM architecture (script does all deterministic work, LLM is formatter-only, fires only when watched rows changed), the `no_agent`→precheck flip via `jobs.json` direct edit, added/removed/retimed diffing, self-silencing event window, the uv-reexec dependency guard, reusing `google_api.py` for raw Drive calls, and the monkeypatch-now firing-path test.
- `references/travel-ride-share-calendar-watchers.md` — Read-only watcher pattern for business trips, alcohol-context events, Uber/ride-share checks, and travel-time calendar verification.
- `references/hermes-security-review-checklist.md` — Non-secret Hermes security review checklist covering config hardening, cron/script risk review, dashboard exposure, and approval-gated remediation.

Default posture:

- Deterministic alert/no-alert checks should be `no_agent: true` and script-only.
- Briefs, ranking, prioritization, and natural-language synthesis should use a deterministic precheck script plus an LLM.
- A script-only job should stay silent when nothing actionable happened.
- A job that needs private account data should emit minimal metadata, not raw sensitive snippets.

This reduces token waste, lowers privacy exposure, and makes recurring automations easier to test.

## When to Use

Use this skill when:

- Creating a new cron automation.
- Updating an existing cron job that runs frequently.
- Auditing token usage or noisy scheduled jobs.
- Converting a watcher, alert, reminder, or transactional check to script-only mode.
- Designing Gmail, calendar, Drive, webhook, filesystem, status, or API polling jobs.

Do not use script-only mode when:

- The output requires judgment, synthesis, prioritization, or recommendations.
- The job is a research brief or executive digest.
- The user explicitly wants a narrative explanation each run.

For those cases, use precheck-plus-LLM instead.

## Decision Tree

1. Can a script decide whether there is an event?
   - Yes: use `no_agent: true`.
   - No: continue.
2. Can a script gather compact structured context before the LLM runs?
   - Yes: attach a script and keep `no_agent: false`.
   - No: keep LLM-only, but explain why.
3. Should non-events notify the user?
   - Usually no. In script-only mode, print nothing for non-events.
4. Does the job touch sensitive data?
   - Emit only minimal fields needed for action: source, account label, subject/title if acceptable, timestamp, and next action.
   - Avoid message bodies, snippets, credentials, raw attachments, and long copied text.

## Recommended Cron Shapes

### Deterministic watcher / alert

Use for calendar alerts, tax/CPA watch, health checks, disk thresholds, CI status checks, update guards, and other transactional automations.

```text
script: my_watchdog.py
no_agent: true
deliver: origin or target channel
```

Script contract:

- Exit code `0` with empty stdout: silent success.
- Exit code `0` with non-empty stdout: deliver stdout verbatim.
- Non-zero exit: scheduler sends an error alert.

### Synthesis brief

Use for morning briefs, research reports, model watchlists, and human-readable summaries.

```text
script: my_precheck.py
no_agent: false
enabled_toolsets: minimal required set
skills: relevant skills
```

Script contract:

- Emit compact JSON or Markdown context.
- Do not perform side effects.
- Let the LLM rank, explain, and recommend.

### Reviewed watcher (script precheck + LLM review + pretty delivery)

Use when the user wants every cron response (even simple watchdogs) to be
(a) evaluated for false alarms / actionable items and (b) consistently,
prettily formatted with clickable links. Convert the watchdog from
`no_agent: true` to a precheck-plus-LLM job: the script becomes a pure data
collector, and a shared review+style prompt makes the LLM evaluate then format.

```text
script: my_watchdog.py        # now a data collector, not the final message
no_agent: false
enabled_toolsets: [terminal, file]   # add skills only if a skill is attached
prompt: <job intro> + shared cron_review_prompt
```

Stays cheap because the scheduler skips the LLM entirely when the script emits
empty stdout (healthy/no-event ticks cost zero tokens). The LLM can suppress a
delivered-but-not-worth-it result by replying with exactly `[SILENT]`. Full
recipe, scheduler mechanics, and the conversion CLI in
`references/script-precheck-llm-review-pretty.md`.

#### Drive/document coverage in briefs

When a briefing includes Drive or document changes, the precheck should narrow the LLM's scope to recently changed or recently shared/recently modified shared files. Include account provenance, file ID/name/mime type/modified time/link, and explicit cutoffs in the script output. In the prompt, require the LLM to inspect candidate files when practical and summarize only changes/content it actually observed. If the file cannot be safely inspected, it should either be omitted or labeled as metadata-only; never infer substantive changes from a title or modified timestamp alone.

#### Read-only software/security watchlists

For watchlists that track public repos, plugin directories, model catalogs, or security tools, keep the script read-only and compact: fetch official API metadata plus a small number of recent commits/releases, and leave installation, enablement, imports, config changes, or dependency adoption out of the cron path. The cron prompt should explicitly say that monitoring approval is not installation approval, and that any install/enable/import action requires separate user approval and a risk review. This is especially important for plugin/security-tool discovery, where adding a tool can expand permission or execution surface.

#### Container/service auto-update guards

When the user wants a daily automation to keep a Dockerized service updated, split mutation from verification. Use a host-side updater such as Watchtower, systemd timer, or host cron for `docker pull`/container recreation because an app container usually cannot safely update itself without host Docker access. Pair that with a Hermes `no_agent: true` guard that checks version/digest state and stays silent when healthy. If mounting `/var/run/docker.sock` or adding Watchtower, ask for explicit approval first because the socket grants host-level Docker control. Prefer `--label-enable` plus per-service labels so only approved containers auto-update. See `references/container-auto-update-guards.md` for a compose snippet and guard checklist.

## Script Design Checklist

- [ ] Uses explicit account/source allowlists when handling personal data.
- [ ] Reads only the minimal required metadata.
- [ ] Prints nothing when nothing needs attention.
- [ ] Produces Telegram-readable text when `no_agent: true`.
- [ ] Produces compact JSON/Markdown context when used as an LLM precheck.
- [ ] For calendar/daily/event briefs, uses the user's explicit local timezone for day boundaries and user-facing times; scheduler UTC is internal-only.
- [ ] Converts raw ISO/UTC timestamps into friendly labels before delivery, e.g. `5:30 PM PDT` or `Tonight 5:30–7:30 PM PDT`.
- [ ] Has stable dedupe/state if repeated alerts are possible.
- [ ] Handles missing credentials/config by failing clearly.
- [ ] Avoids network writes, email sends, calendar edits, or config changes unless separately approved.
- [ ] Can be run locally with `python /opt/data/scripts/name.py` for verification.
- [ ] **Token-efficient breadcrumb docstring.** Include a ~10-15 line module docstring covering: cron schedule + silence conditions, output format, key design decisions (grouping, dedup, position logic), shared helper references (e.g. `L.role_label()` from `usaw_to_lib.py`), and a wiki cross-reference (`[[page-name]]`). This costs minimal tokens when loaded but saves a full file read when a future agent needs to recall how the script works.
- [ ] **Breadcrumb enrichment for precheck+LLM triage jobs.** When a precheck passes items to an LLM for triage (email, feeds, APIs), extract token-efficient signals from metadata-only fields so the LLM can SKIP obvious noise without fetching full content. Breadcrumbs: `skip_hint` (pre-classified skip reason from sender/snippet/subject patterns), `urgency` (deadline/reminder/payment/scheduling/action), `age` (compact `2h`/`1d`/`3d`), `domain` (sender domain), `flags` (IMPORTANT/STARRED), `snippet` (120-char compact). Teach the agent a fast-path in the prompt: `skip_hint` set → SKIP without fetching; `urgency` set → fetch first; `thread_state=awaiting_reply` → SKIP. Define functions in the primary precheck, import into siblings. See `references/precheck-breadcrumb-enrichment.md` for full implementation.
- [ ] Hyperlinks every referenced item: render `[descriptive text](url)` (Google Calendar event `htmlLink`, Gmail search URL, Drive `webViewLink`, ESPN scoreboard, etc.) instead of bare URLs or plain labels. This is a standing user preference for daily/cron updates.
- [ ] Uses an emoji-led house style for user-facing messages (emoji header + `━━━` divider, bold labels, 🟢🟡🔴⚪ status icons, italic privacy/source footer). See `references/cron-message-house-style.md`.
- [ ] A script-only watchdog that shells out to another interpreter (`subprocess.run(['python', ...])`) MUST use the same dependency environment its target needs — retry through `uv run --with <deps>` on `ModuleNotFoundError`/`No module named` before classifying the failure. Never let a missing-dependency crash be reported as an auth/credential/logic failure.
- [ ] **Verify hardcoded limits against actual system values.** When a script compares against a limit (memory char budget, file size threshold, API quota), confirm the constant matches the real system value — not a stale guess. The memory-pressure watchdog had `USER_LIMIT = 2400` when the actual budget was 4000, causing false 128% alerts for weeks. Check the memory tool's own output, config files, or API docs for the authoritative number.

## Audit Heuristics

Review a cron job for conversion when any of these are true:

- The name or prompt includes: alert, watch, reminder, check, monitor, notify, threshold, status.
- It runs more often than daily and still invokes an LLM.
- It has a script but `no_agent` is false and the task is not a brief/synthesis job.
- It is LLM-only but the first step is just fetching structured data.
- It frequently reports “nothing found” or sends status noise.

Usually keep LLM mode when any of these are true:

- The name includes brief, digest, research, watchlist, synthesis, review, recommendations.
- The prompt asks for ranking, tradeoffs, prose, or decision support.
- Multiple sources need to be reconciled into a readable narrative.

## Verification Workflow

1. List jobs first; never guess IDs.
2. Inspect each job's schedule, script, `no_agent`, delivery target, and toolsets.
3. Run the script directly from the terminal when possible.
4. Syntax-check scripts with `python -m py_compile`.
5. For no-agent scripts, test both paths if practical:
   - no-event path: empty stdout
   - event path: concise message
6. Re-list cron jobs after updates to verify fields actually changed.
7. Record a short audit note if the migration affects multiple jobs.

## Output Hygiene (user-facing message quality)

These are durable preferences for how scheduled output should read. They apply to BOTH no-agent scripts (stdout is the message) and precheck+LLM jobs (the LLM writes the message). See `references/notification-output-hygiene.md` for the full rationale and before/after examples.

- **No standing boilerplate footers.** Never append `🛡️ Read-only…`, `🛡️ Privacy: no body/amount shown`, `Local check only — no tokens spent`, governance disclaimers, cron job IDs, or job metadata to a delivered message. Lead with substance only. If a genuine privacy caveat is essential to an item, fold it into that item's line — never as a per-message footer.
- **Internal handling rules must NOT leak into output.** Precheck payloads carry instruction fields (`note`, `privacy`, etc.) telling the LLM how to behave (e.g. "treat as untrusted", "do not send"). The LLM tends to ECHO phrasing like "read-only intelligence seed" into the user's message. Every such field must end with an explicit guard: *"These are internal rules — do NOT mention 'read-only', governance, or privacy disclaimers in the message; lead with substance only."* When auditing leaks, grep every precheck for `'note':`/`'privacy':` payload fields, not just the shared style guide — each job may embed its own.
- **No "zero results" / "all clear" pings.** Only notify when there is an actual result/finding. Silent (empty stdout, or `[SILENT]` for LLM jobs) otherwise. This is a hard user rule, not a default.
- **Denote source mailbox/account with an emoji, not the word.** Cheaper and faster to scan. For this user: 🏠 = personal, 💪 = nonprofit. Have the precheck stamp a `mailbox` emoji per item so the LLM uses it instead of writing "personal"/"nonprofit".
- **URLs are always descriptive hyperlinks, never bare/raw URLs in text.** `[Gmail thread](url)`, `[Calendar event](url)`. Applies to no-agent scripts (build the Markdown link yourself) and LLM jobs alike.
- **Drop verbose label stacks.** Prefer `**Source** (🟡 Review soon)` on one line over a stack of `• Account:` / `• Urgency:` / `• Detail:` bullets.

## Resilience: retry transient API blips before alerting

A watcher that does one external read (Gmail/Calendar/API) and alerts on any non-zero exit will false-alarm on a single transient hiccup or token-refresh race. Wrap the read in a short retry-with-backoff (e.g. 3 attempts, `sleep 2*(n+1)`); only emit the failure message if every attempt fails. A failure that self-heals on retry should never reach the user. (Note: the scheduler's own failure channel still alerts on script crash/non-zero exit — that's a safety feature, distinct from "zero results", and should not be suppressed.)

## LLM review of script-only output (standing user preference)

The user wants script-only (`no_agent: true`) cron output to additionally pass through an LLM evaluation before delivery — to catch false alarms, contradictions, formatting problems, and genuinely-actionable items. Pure script-only mode delivers stdout verbatim with no judgment, which is exactly how a misclassified false alarm reaches the user.

Pattern for judgment-sensitive watchdogs (auth, tax/CPA, calendar/travel, update guards):

- Keep the deterministic script as a **precheck** (`no_agent: false`, script attached) that emits compact draft text or structured findings.
- Add a short LLM review step in the prompt: "Evaluate the draft below. Is anything wrong, contradictory, a false alarm, or actually actionable? Fix obvious errors, flag uncertainty with `⚠️ needs attention:`, then deliver in the house style with clickable links. Stay silent if there is genuinely nothing to report."
- Keep cheap/high-frequency, purely-mechanical watchdogs (disk threshold, heartbeat) as pure `no_agent` to control token cost — confirm scope with the user.

## Common Pitfalls

### Seen-state dedup pattern for triage crons

When a precheck script fetches a feed (email, API, RSS) and passes items to an LLM for triage, use a **two-file state pattern** to avoid re-processing:

```
$HERMES_HOME/<job>_seen.json       ← written by PRECHECK; all fetched IDs
$HERMES_HOME/<job>_handoff.json    ← written by PRECHECK; IDs passed to LLM (diagnostic)
$HERMES_HOME/<job>_seen_new.json   ← written by LLM after processing; merged next run
```

**Why two files?**
- Precheck marks ALL fetched items seen immediately (not just signal items) — prevents noise from re-appearing on every tick
- LLM writes confirmed-processed IDs separately so merge only happens after real processing
- If LLM fails mid-run, the handoff file shows what was in-flight; seen.json already excludes those IDs from next fetch

**Pruning:** cap the seen list (e.g. `MAX_SEEN = 2000`), drop oldest entries. Without pruning the file grows forever.

**Idempotency test:** run the precheck twice in a row. Second run must produce empty stdout.

## Memory pressure watchdog (pattern example)

A clean application of script-first design: `no_agent` Python reads memory files,
classifies entries by offload destination, fires a review report only above threshold.
Zero tokens on most runs. See `references/memory-pressure-watchdog.md` for full detail,
thresholds, classification heuristics, and sample output.

1. Converting a synthesis job to `no_agent: true` just to save tokens. This creates brittle reports and loses judgment. Use a precheck script instead.
2. Printing “all clear” from a frequent watchdog. In no-agent cron, non-empty stdout is delivered. Stay silent on non-events.
3. Letting scripts dump raw private snippets. Script output becomes the user-facing message in no-agent mode.
4. Forgetting that failed scripts alert the user. Use clear exceptions for real failures, but avoid treating expected no-data states as errors.
5. Creating duplicate cron jobs instead of updating the existing one. Always list first and update by ID.
6. Over-broad toolsets on LLM cron jobs. Restrict to the minimum needed tools.
7. **Wrong script directory.** The `script:` field resolves relative to the real cron scripts dir (here `/opt/data/scripts/`), NOT `~/.hermes/scripts/`. A script saved in the wrong folder yields `Script not found` at fire time even though local runs work. Save to and verify in the actual scripts dir, then run the job once to confirm `last_status: ok`.
8. **Subprocess-dependency false alarm.** A `no_agent` watchdog that runs `subprocess.run(['python', 'tool.py', '--check'])` will crash with `ModuleNotFoundError` if the bare interpreter lacks the tool's deps — and a naive classifier maps that crash to a domain error (e.g. an auth guard reporting `invalid_grant`/`re-auth needed` when credentials are actually fine). Delivered verbatim, this is a scary, wrong red alert. Fix: build the subprocess command with the same `uv run --with <deps>` fallback the real tool uses, retry on missing-module signals, and only classify a genuine non-dependency failure. When the job is LLM-reviewed, the review layer is a second defense — instruct it to treat dependency/transient errors as likely glitches, not confirmed problems.
9. **Bare-URL / unstyled output.** Script-only messages that print raw URLs or plain labels miss the standing user preference for clickable `[text](url)` links and the emoji house style. Apply the shared style (see `references/cron-message-house-style.md`) to every user-facing cron message, not just LLM briefs.
10. **Hand-formatting each cron script independently** when the user wants a consistent "pretty" look. They drift instantly and are painful to retune. Build ONE shared formatter module (`scripts/cron_style.py`) that every script-only job imports, and embed the same house-style rules as a prompt block for LLM briefs. Render a dry-run sample and get aesthetic approval ONCE before wiring all scripts. See `references/cron-house-style-formatter.md`.
11. **Stale verbatim-delivery instructions after a mode flip.** After flipping a job from `no_agent` to LLM mode, strip leftover "deliver stdout verbatim / do not use an LLM / empty stdout means no update" lines from the prompt — they contradict the new review step.
12. **Boilerplate/disclaimer leak into delivered messages** — see Output Hygiene above. The single most common style complaint; fix at two layers (shared style guide AND each job's embedded payload notes).
13. **`cronjob action=update` cannot flip `no_agent`.** The cron update API does not expose a `no_agent` toggle — updating via `cronjob` leaves `no_agent: true` unchanged even after setting a prompt. To flip a job from script-only to precheck-LLM mode, edit `/opt/data/cron/jobs.json` directly: the list uses key `"id"` (not `"job_id"` as returned by the API). Set `no_agent: false`, write back, then verify with `cronjob action=list`.
14. **Testing with live state dirs corrupts the baseline.** When running a precheck script manually to test behavior, ALWAYS override the state dir with a `/tmp/` path (`USAW_STATE_DIR=/tmp/test_run python myscript.py`). Running the script against the live state dir — even once — advances the `revisionId` / `last_seen` anchor, which can cause the next real cron tick to treat historical data as "new" and flood the user with stale alerts. One session produced this exact incident: `rm -f last_revision.json` on the live dir caused all 36 historic assignments to re-surface as new changes.
15. **Editing a shared prompt/style file expecting existing jobs to pick it up.** Hermes cron jobs **freeze their full prompt at creation time** — the scheduler does NOT re-read shared style-guide/prompt files (e.g. `cron_review_prompt.md`) at runtime. Editing that file changes nothing for jobs already created. Tone/format/voice changes to existing jobs must be written into each job's prompt directly via `cronjob action=update`. Re-list after updating to confirm the field actually changed.
16. **Undefined variables after bulk path patching.** When replacing hardcoded paths with env-var patterns, a variable renamed in one place (e.g. `wiki_path` to `root`) may still be referenced elsewhere in the same script. `py_compile` catches syntax errors but NOT `NameError` on undefined variables. Always read the full script logic flow after patching, not just the lines that changed.
17. **Broken string replacements from `execute_code` bulk patches.** When using `execute_code` (or any automated `str.replace`) to patch `Path('/opt/data/cron/state/X.json')` → `HERMES_HOME / "cron/state/X.json"`, the replacement of `Path('/opt/data/cron/state/` with `HERMES_HOME / "cron/state/` leaves a dangling `X.json')` that becomes `"X.json')` — an unclosed string literal. The script compiles but the value is wrong, or it fails with `SyntaxError: unterminated string literal`. **Fix:** always use exact full-line replacements in automated patches, not substring replacements. Verify every modified file with `py_compile` AND a test run (`python3 script.py --dry-run`). The pattern `STATE_PATH = HERMES_HOME / "cron/state/"X.json')` is the telltale sign of a botched substring replacement.
18. **Session DB column names differ from expectations.** When writing a session-to-wiki precheck that queries the Hermes `state.db`, the `sessions` table uses `started_at` (REAL epoch float), NOT `created_at` (which doesn't exist). Always check the schema with `PRAGMA table_info(sessions)` before writing queries. Also: `tool_call_count` and `message_count` are INTEGER columns useful for filtering "real work" sessions.
19. **Stripping visual elements or restyling language the user likes under token-efficiency guise.** When auditing cron output for token efficiency, do NOT remove progress bars (`[██████░░░░]`), status icons (🔴🟡🟢), or emoji section headers — this user explicitly likes them for at-a-glance scanning. Do NOT rename or shorten approved labels either ("Wiki offload candidates" → "Wiki offload", "Keep as-is" → "Keep", "• Entry N:" → "N.") — the user said "No I like the old language a bit better" when wording was trimmed. The guiding question "is this the most token-efficient way to express this?" applies to *boilerplate governance footers and genuinely redundant content*, not to visual formatting or wording the user has approved. When in doubt about whether a visual element or label is load-bearing, keep it. The memory-pressure-watchdog session (Jun 2026) produced two rounds of this correction: first bars/icons were removed ("No I like the progress bars and status and emojis"), then label wording was shortened ("No I like the old language a bit better").

## Model selection: Haiku vs Sonnet for LLM cron jobs

When a LLM cron job's model is unset or defaulting to Sonnet, evaluate against this framework:

**Use Haiku when:**
- The LLM role is pure formatting — receives structured JSON from a precheck script and renders to a fixed template (e.g. USAW TO change alerts, upcoming-meetings note, eod-wrap bullets)
- The job runs frequently (every 15–60m) and the precheck already did all reasoning
- Output is templated/deterministic — same structure every time, just different values

**Keep Sonnet when:**
- Multi-source synthesis: reconciling calendar + email + context into one coherent view
- Judgment calls: email draft writing, prioritization, recommendations
- Research or watchlist analysis requiring nuanced reading
- Privacy-sensitive graph inference (personal-context-review)
- Weekly/planning digests where prose quality is the deliverable

**Rule of thumb:** if the script already classified the data and the LLM only needs to render it, Haiku is sufficient. If the LLM needs to decide what matters, Sonnet.

**How to flip model:** `cronjob action=update job_id=<id> model={"model": "claude-haiku-4-5-20251001", "provider": "anthropic"}` — the update API supports model changes cleanly. Verify with `cronjob action=list`.

## LLM alert phrasing: actor → action → affected person

For cron alerts about schedule changes, assignments, or any event where a human made a change to another person's slot, phrase every line as:

> **`<actor> did <action> to <affected person>`**

- `changed_by added 🟦 Person as Role · context`
- `changed_by removed 🟪 Person from Role · context`
- `changed_by replaced 🟦 Person with Replacement in Role · context`
- `changed_by moved 🟪 Person into Role, replacing OldPerson · context`

Use "system" when `changed_by` is "unknown". Strip credential tags from names ("Les Simonton (IWF 1)" → "Les Simonton"). This phrasing is clearer than person-centric ("James Wiese was removed by…") because it puts the actor first — who is responsible — then what they did, then who it affected.

## Model selection for LLM cron jobs (Haiku vs Sonnet)

When a precheck script does all the deterministic work and the LLM is purely a
formatter, **Haiku is appropriate and costs ~20× less**. When the LLM must
synthesize, rank, draft, or make judgment calls, keep Sonnet.

| ✅ Use Haiku | ❌ Keep Sonnet |
|---|---|
| Pure formatter — receives structured JSON, renders to a fixed template | Multi-source synthesis (calendar + email + priorities → morning brief) |
| High-frequency job (every 15–25m) where LLM fires rarely | Email draft writing — nuanced tone, context reading |
| Short output: 5–10 structured bullets from structured input | Weekly planning digests, research briefs |
| Precheck gates nearly all ticks silent (LLM fires <10% of ticks) | Privacy-sensitive graph inference (relationship/context review) |

**Test:** ask "could a junior copy-editor do this from the JSON alone, with no domain knowledge?" If yes → Haiku. If no → Sonnet.

High-frequency formatter jobs are the biggest cost lever: a job running every 25m
that fires 10% of ticks still runs ~60×/day. Haiku on that job saves ~$0.50/day
compounded over weeks.

## Script enrichment signals to precompute (save LLM tokens)

For any change-alert job, the script should pre-compute everything deterministic
so the LLM receives ready-to-display values, not raw data requiring math:

| Signal | How to compute | Format |
|---|---|---|
| **Age of change** | `(now - revision.modifiedTime).total_seconds()` | `"42m ago"`, `"6h ago"`, `"2d ago"` |
| **Session urgency** | `(session_start_dt - now).total_seconds() / 3600` | `{icon, label, hours_until}` |
| **Scope** | `watched_changes / total_role_changes * 100` | `"targeted"` or `"broad reshuffle"` |
| **Size delta** | `new_file.stat().st_size - old_file.stat().st_size` | `"+41,817 bytes"` |

These four signals convert raw API data into immediately human-readable context
that makes the LLM's formatting job trivial. The LLM should use them verbatim
(they are pre-computed, not to be recalculated or second-guessed).

## Sibling precheck state isolation pitfall

When two cron precheck scripts cover overlapping territory (e.g. `inbox_triage_precheck.py` every 30m and `followup_sweep_precheck.py` daily, both scanning the same inbox), they can surface the same threads to the agent on the same day — causing duplicate processing, duplicate drafts, or contradictory alerts.

**Pattern:** each sibling has its own seen-state file, so neither knows what the other already handled.

**Required safeguards for sibling prechecks:**

1. **Shared draft-exclusion check.** If one sibling creates Gmail drafts, ALL siblings that surface threads must check `in:drafts` and exclude threads with pending drafts. The `inbox_triage_precheck.py` already does this; `followup_sweep_precheck.py` did NOT (as of Jun 2026), risking duplicate drafts. Port the `draft_thread_ids()` pattern to every sibling that surfaces threads for drafting.
2. **Cross-reference recently-surfaced state.** Maintain a shared lightweight "recently surfaced" file (e.g. `cron/state/recently_surfaced.json` with threadId → timestamp, 12-hour TTL) that all siblings read before surfacing. If threadId was surfaced by any sibling in the last N hours, skip it.
3. **Thread state pre-classification.** Before surfacing, check who sent the last message in the thread. If Jim sent last → `awaiting_reply` (no action needed). If other party sent last → `needs_action`. If a draft exists → `drafted`. This saves the agent an API call and prevents surfacing threads that don't need action.

**Idempotency test for siblings:** run both prechecks in sequence (triage then sweep) on the same inbox. The sweep must NOT re-surface any thread the triage already handled.

## Multi-script cron systems: shared-library pattern

When 2+ cron scripts cover related territory (e.g. a reminder + a change-watcher
+ an alert engine all reading the same Google Sheet), extract shared logic into
a single library module rather than duplicating it across scripts.

**Pattern (proven in USAW TO deployment, 4 scripts + 1 shared lib):**

```
scripts/
├── my_lib.py          # shared library: constants, sheet parsing, API helpers
├── my_reminder.py     # imports my_lib as L; uses L.parse_assignments(), L.role_label()
├── my_watcher.py      # imports my_lib as L; uses L.diff_xlsx_for_watched(), L.drive_revisions()
└── my_alerts.py       # imports my_lib as L; uses L.plat_emoji(), L.now_mt()
```

**What goes in the shared library:**
- Constants (file IDs, sheet tab names, watched names, role columns, emoji maps)
- Sheet parsing logic (the authoritative row→assignment dict function)
- External API helpers (Drive revisions, downloads, retries)
- Formatting helpers used by all consumers (platform emoji, role labels with position)
- Position-in-block computation (counting rows within platform blocks, skipping dividers)
- Cell-level diff engine (for change detection between revisions)
- State file paths and snapshot load/save helpers
- Event window check (dates when the scripts should be active/silent)

**Consumer scripts import as `import my_lib as L`** and call `L.function()`.
This prevents drift: when the sheet structure changes, you fix one parsing function,
not three copies.

**Docstring contract:** Each consumer script's docstring should name the shared
library and list which helpers it uses. Each shared library's docstring should
list its consumers. This makes it easy to assess blast radius when changing a
shared function.

**Code review checklist for multi-script systems:**
1. Do all consumers use the shared helpers consistently? (grep for `L.` calls)
2. Does the shared library handle `None` inputs safely? (precheck scripts often receive null from API responses — see the `cron_trace_diagnostic.py` bugs where `classify_error(None)` and `get_failure_id(job_id, None, ...)` crashed)
3. Are state files (dedup, snapshot, revision tracking) scoped per-consumer to avoid cross-talk?
4. Is the event window check in the shared library so all consumers go silent together?
5. Are divider/header rows handled in the shared parser, not re-implemented per consumer?

## QMD index maintenance cron

When QMD semantic search is active on a wiki/knowledge base that other crons
(hourg/ingest, session-to-wiki, email-to-wiki) continuously add pages to, the
vector embeddings go stale unless refreshed. BM25 keyword search stays current
via `qmd update` on ingest ticks, but `qmd embed` (vector generation) is a
separate manual step.

**Pattern:** a daily `no_agent` cron that runs `qmd update` then `qmd embed`
silently. Only emits output on failure so the user knows semantic search is
stale. Costs zero tokens on the healthy path.

```text
script: qmd_refresh.py
no_agent: true
schedule: 0 4 * * *
deliver: telegram
```

Script contract: exit 0 silent on success; exit 0 with stdout on failure
(non-fatal — don't trigger the scheduler's error channel for a stale index,
just tell the user). See `references/memory-pressure-watchdog.md` for the
script and the QMD-aware watchdog that depends on it.

## Recommended Next Step

For active systems, schedule a weekly no-agent cron audit that reads cron metadata, classifies jobs, and reports only configuration-level token-waste candidates. It should not read private message bodies or mutate jobs.
