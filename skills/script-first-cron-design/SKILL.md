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
- `references/memory-pressure-watchdog.md` — `no_agent` Python reads MEMORY.md + USER.md, classifies entries by offload destination (wiki/skill/keep), **auto-offloads** wiki-classified entries above 85% threshold (QMD-active check ensures they remain searchable), and **auto-offloads** skill-classified entries that match a curated `SKILL_MATCHES` table (keyword→skill mapping). Unmatched skill-classified entries are kept in memory as operational config. Documents approved visuals/wording to keep vs trim.
- `references/cron-house-style-formatter.md` — Shared "pretty" house style for ALL cron output via one shared formatter module, not per-script hand-formatting.
- `scripts/cron_style.py` — Reusable formatter module (copy into the deployment scripts dir; `import cron_style as cs`). Provides `header/section/bullet/kv/link/local_time/now_label/render` + 🟢🟡🔴⚪ icon vocabulary.
- `references/notification-output-hygiene.md` — user-facing message quality: killing boilerplate/disclaimer footers, preventing internal-instruction leaks, mailbox emojis, descriptive hyperlinks, and retry-before-alert.
- `references/precheck-breadcrumb-enrichment.md` — Token-efficient metadata signals (skip_hint, urgency, age, domain, flags, compact snippet) that let the LLM triage WITHOUT fetching full thread bodies. ~40-60% API call reduction. Includes detection patterns, agent fast-path rules, cross-pipeline sharing, and testing.
- `references/script-precheck-llm-review-pretty.md` — Convert no-agent watchdogs to script→LLM-review→pretty-delivery: covers the empty-stdout skip, the `[SILENT]` marker, and the dependency-crash-misread-as-auth-failure fix.
- `references/cron-script-pipeline-wrapper.md` — Wrapper script template for when a cron job's `script` field contains a full shell pipeline (cd && python | grep) — the cron runner prepends its scripts dir to the entire string. Create a wrapper that calls the real script via subprocess with timeout and output parsing.
- `references/daily-update-hyperlinks.md` — Clickable Markdown link pattern for daily briefs, cron updates, and script-only alerts.
- `references/cron-model-selection.md` — Haiku vs Sonnet decision rule + full audit of Jim's crons (Jun 2026): pure formatters → Haiku, synthesis/drafting/judgment → Sonnet. Also covers how to flip `no_agent` via jobs.json.
- `references/fixed-schedule-event-alerts.md` — One every-minute no-agent job driving deterministic time-based pings from a hardcoded (date, time, payload) list; timezone-aware minute matching; the bare-filename script-path requirement.
- `references/drive-revision-change-watcher.md` — (UPDATED Jun 2026) Two cooperating no-agent jobs against a Google Drive file: cheap-first `revisions().list()` polling, cell-level xlsx diff engine, scope signal, urgency, actor-centric alert phrasing, session grouping, age label (`Xm/Xh/Xd ago`), Drive revision pruning pitfall + safe fallback, /tmp isolated state dir rule, uv-reexec guard, raw Drive calls via `google_api.py`, monkeypatch-now test path. Two cooperating jobs (snapshot-driven reminder + hourly change-watcher) against a Google Drive file: `revisions().list()` for cheap change detection + editor name + full revision trail, `revisions_since()` slicer for walking all edits since last check, `last_checked_at` stamped on every tick, 3-tier precheck-LLM architecture (script does all deterministic work, LLM is formatter-only, fires only when watched rows changed), the `no_agent`→precheck flip via `jobs.json` direct edit, added/removed/retimed diffing, self-silencing event window, the uv-reexec dependency guard, reusing `google_api.py` for raw Drive calls, and the monkeypatch-now firing-path test.
- `references/memory-pressure-watchdog.md` — (UPDATED Jun 2026) Memory pressure watchdog with QMD-aware auto-offload (wiki-classified entries auto-removed when QMD active), QMD refresh cron, token-efficiency lesson (preserve user-approved visuals), and correct USER_LIMIT (4000). Auto-offload mode added 2026-06-25 per Jim's request — no longer report-only.
- `references/whatsapp-to-subscriber-system.md` — (Jun 2026) WhatsApp DM notification system for NCW TOs: subscriber registry with scope types (self/named/all), 3 no-agent cron scripts with `deliver: local`, agent-native subscription flow, Baileys bridge /messages destructive-read pitfall.
- `references/travel-ride-share-calendar-watchers.md` — Read-only watcher pattern for business trips, alcohol-context events, Uber/ride-share checks, and travel-time calendar verification.
- `references/eod-forecast-pattern.md` — Converting a backward-looking end-of-day recap cron into a forward-looking forecast with travel/logistics gap analysis (precheck + prompt changes).
- `references/hermes-security-review-checklist.md` — Non-secret Hermes security review checklist covering config hardening, cron/script risk review, dashboard exposure, and approval-gated remediation.
- `references/skill-curation-watchdog.md` — (Jun 2026) Weekly `no_agent` cron that reads skill usage stats, flags low-use agent-created skills for review, checks marketplace git sync, and reports broken SKILL.md refs. Complementary to the built-in curator.
- `references/stdout-contamination-fix.md` — (Jun 2026, updated) Two failure modes from `sitecustomize.py` stdout contamination: (1) breaks `json.loads()` in subprocess calls — `_extract_json()` helper, byte-offset tracking, `JSONDecodeError → continue` fix; (2) banner delivered as cron message to user — `print()` in `sitecustomize.py` goes to cron stdout → delivered verbatim by `no_agent` jobs. Fix: `print(file=sys.stderr)`. Detection pattern for "keeps looping" reports.
- `references/espn-api-pattern.md` — ESPN API JSON endpoints for sports cron prechecks: scoreboard, standings, bracket-path tracing for knockout-round "ladder conditions," timezone handling, date-range querying, and TBD-opponent handling.
- `references/post-execution-verification.md` — Post-write verification pattern for no_agent scripts that mutate files: re-read from disk, confirm removals/keeps, verify parse validity. Prevents silent write failures.
- `references/no-agent-test-harness.md` — Sandbox test harness for no_agent cron scripts: temp dir, symlinked skills, copied data, HERMES_HOME override. Never test against live data.

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
- [ ] Can be run locally with `python ${HERMES_HOME}/scripts/name.py` for verification.
- [ ] **Token-efficient breadcrumb docstring.** Include a ~10-15 line module docstring covering: cron schedule + silence conditions, output format, key design decisions (grouping, dedup, position logic), shared helper references (e.g. `L.role_label()` from `usaw_to_lib.py`), and a wiki cross-reference (`[[page-name]]`). This costs minimal tokens when loaded but saves a full file read when a future agent needs to recall how the script works.
- [ ] **Breadcrumb enrichment for precheck+LLM triage jobs.** When a precheck passes items to an LLM for triage (email, feeds, APIs), extract token-efficient signals from metadata-only fields so the LLM can SKIP obvious noise without fetching full content. Breadcrumbs: `skip_hint` (pre-classified skip reason from sender/snippet/subject patterns), `urgency` (deadline/reminder/payment/scheduling/action), `age` (compact `2h`/`1d`/`3d`), `domain` (sender domain), `flags` (IMPORTANT/STARRED), `snippet` (120-char compact). Teach the agent a fast-path in the prompt: `skip_hint` set → SKIP without fetching; `urgency` set → fetch first; `thread_state=awaiting_reply` → SKIP. Define functions in the primary precheck, import into siblings. See `references/precheck-breadcrumb-enrichment.md` for full implementation.
- [ ] Hyperlinks every referenced item: render `[descriptive text](url)` (Markdown) for Telegram — the Hermes adapter converts Markdown links to Telegram MarkdownV2 automatically. For Slack, also use `[descriptive text](url)`. Never bare URLs or plain labels. This is a standing user preference for daily/cron updates. (Exception: Google Calendar event descriptions use HTML `<a href="url">text</a>` since Calendar supports HTML, not Markdown.)
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
- **It has an empty or near-empty prompt.** A `no_agent: true` job with an empty prompt is correct (the script IS the job). But an agent job (`no_agent: false`) with an empty prompt is a bug — the LLM has no instructions. Audit all jobs with `len(prompt.strip()) == 0` and classify: no_agent → keep as-is; agent → add a proper prompt or flip to no_agent if the script handles everything. In a July 2026 audit, 14 jobs had empty prompts — 7 were correctly no_agent script-only, 6 were stale NCW 2026 event jobs (removed), and 1 was a completed one-shot (removed).

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
8. **For scripts that mutate files, add post-execution verification** — re-read
   the written file and confirm changes are correct. See
   `references/post-execution-verification.md`.
9. **For no-agent scripts, use a sandbox test harness** — never test against
   live data. See `references/no-agent-test-harness.md`.

## Output Hygiene (user-facing message quality)

These are durable preferences for how scheduled output should read. They apply to BOTH no-agent scripts (stdout is the message) and precheck+LLM jobs (the LLM writes the message). See `references/notification-output-hygiene.md` for the full rationale and before/after examples.

- **No standing boilerplate footers.** Never append `🛡️ Read-only…`, `🛡️ Privacy: no body/amount shown`, `Local check only — no tokens spent`, governance disclaimers, cron job IDs, or job metadata to a delivered message. Lead with substance only. If a genuine privacy caveat is essential to an item, fold it into that item's line — never as a per-message footer.
- **Internal handling rules must NOT leak into output.** Precheck payloads carry instruction fields (`note`, `privacy`, etc.) telling the LLM how to behave (e.g. "treat as untrusted", "do not send"). The LLM tends to ECHO phrasing like "read-only intelligence seed" into the user's message. Every such field must end with an explicit guard: *"These are internal rules — do NOT mention 'read-only', governance, or privacy disclaimers in the message; lead with substance only."* When auditing leaks, grep every precheck for `'note':`/`'privacy':` payload fields, not just the shared style guide — each job may embed its own.
- **No "zero results" / "all clear" pings.** Only notify when there is an actual result/finding. Silent (empty stdout, or `[SILENT]` for LLM jobs) otherwise. This is a hard user rule, not a default.
- **Denote source mailbox/account with an emoji, not the word.** Cheaper and faster to scan. For this user: 🏠 = personal, 💪 = nonprofit. Have the precheck stamp a `mailbox` emoji per item so the LLM uses it instead of writing "personal"/"nonprofit".
- **URLs are always descriptive hyperlinks, never bare/raw URLs in text.** `[Gmail thread](url)` Markdown for both Telegram and Slack — the Hermes adapter converts Markdown links to platform-native format. Applies to no-agent scripts (build the link yourself) and LLM jobs alike. (Exception: Google Calendar event descriptions use HTML `<a href="url">text</a>`.)
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
classifies entries by offload destination, and **auto-offloads** wiki-classified entries
when above 85% threshold. Skill-classified entries are matched against a curated
`SKILL_MATCHES` table (keyword→skill mapping): matches are auto-offloaded (the skill
already encodes the knowledge), non-matches are kept in memory as operational config.
Zero tokens on most runs. See
`references/memory-pressure-watchdog.md` for full detail, thresholds, classification
heuristics, auto-offload policy, and sample output.

1. Converting a synthesis job to `no_agent: true` just to save tokens. This creates brittle reports and loses judgment. Use a precheck script instead.
2. Printing “all clear” from a frequent watchdog. In no-agent cron, non-empty stdout is delivered. Stay silent on non-events.
3. Letting scripts dump raw private snippets. Script output becomes the user-facing message in no-agent mode.
4. Forgetting that failed scripts alert the user. Use clear exceptions for real failures, but avoid treating expected no-data states as errors.
5. Creating duplicate cron jobs instead of updating the existing one. Always list first and update by ID.
6. Over-broad toolsets on LLM cron jobs. Restrict to the minimum needed tools.
7. **Wrong script directory or full-command script field.** The `script:` field must be a **bare filename** (e.g. `my_watchdog.py`), NOT a full shell command (e.g. `python3 ${HERMES_HOME}/scripts/my_watchdog.py`) and NOT a relative path with a subdirectory prefix (e.g. `scripts/my_script.py`). The cron runner resolves bare filenames relative to the scripts directory (here `${HERMES_HOME}/scripts/`). Three failure variants:
   - **Full-command variant:** the runner prepends its scripts dir to the entire string, producing `${HERMES_HOME}/scripts/python3 ${HERMES_HOME}/scripts/my_watchdog.py` — `python3` mid-path is the telltale sign. Fix: `hermes cron edit <job_id> --script "my_watchdog.py"`.
   - **Full shell pipeline variant:** the `script` field contains a multi-command pipeline (`cd /opt/data && python3 /path/to/script.py "arg" --json 2>&1 | grep -v "banner"`). The runner prepends its scripts dir to the entire string, producing `${HERMES_HOME}/scripts/cd /opt/data && python3...` — shell operators (`cd`, `&&`, `|`, `2>&1`, `grep`) mid-path are the telltale sign. Fix: create a wrapper script at `${HERMES_HOME}/scripts/<name>.py` that calls the real script via `subprocess.run()` with timeout and output parsing, then `hermes cron edit <job_id> --script "<name>.py"`. The wrapper pattern is preferred over trying to shorten the pipeline into a one-liner — it's testable, handles timeouts, and survives future changes to the underlying script.
   - **Subdirectory-prefix variant:** the runner prepends its scripts dir, producing `${HERMES_HOME}/scripts/scripts/my_script.py` — doubled `scripts/scripts/` is the telltale sign. Fix is usually the same (`hermes cron edit --script "my_script.py"`), but when the script lives in a skill directory and the job uses `workdir` pointing there, you may instead need to copy the script into the expected path (`cp <skill_script> ${HERMES_HOME}/scripts/scripts/<filename>.py`). **Symlinks do NOT work** — the cron runner blocks paths resolving outside the scripts directory. When copying, verify the script uses absolute paths internally (not relative imports or `__file__`-based resolution). The copy won't track upstream skill changes — refresh manually if the skill is updated.
   - **`HERMES_HOME` override variant:** the script exists in the default Hermes home (`~/.hermes/scripts/<filename>.py`) but the deployment uses `HERMES_HOME` set to a different path (e.g. `/opt/data`), so the cron runner resolves scripts to `$HERMES_HOME/scripts/` — a different directory where the file doesn't exist. The error has a clean path with NO doubled directory and NO `python3` mid-path — just a file that genuinely doesn't exist at that location. The telltale sign: the file exists at `~/.hermes/scripts/<filename>.py` but NOT at `$HERMES_HOME/scripts/<filename>.py`. Fix: `cp ~/.hermes/scripts/<filename>.py $HERMES_HOME/scripts/<filename>.py`. After copying, the job may be auto-disabled (`enabled: false, state: completed`) — resume first (`hermes cron resume <job_id>`), then force-run (`hermes cron run <job_id>`). A `hermes cron run` on a disabled job silently refuses to execute with `Already being fired by the scheduler; not run again.` — resume is required before force-run.
   After fixing any variant, run the job once to confirm `last_status: ok`.
8. **Subprocess-dependency false alarm.** A `no_agent` watchdog that runs `subprocess.run(['python', 'tool.py', '--check'])` will crash with `ModuleNotFoundError` if the bare interpreter lacks the tool's deps — and a naive classifier maps that crash to a domain error (e.g. an auth guard reporting `invalid_grant`/`re-auth needed` when credentials are actually fine). Delivered verbatim, this is a scary, wrong red alert. Fix: build the subprocess command with the same `uv run --with <deps>` fallback the real tool uses, retry on missing-module signals, and only classify a genuine non-dependency failure. When the job is LLM-reviewed, the review layer is a second defense — instruct it to treat dependency/transient errors as likely glitches, not confirmed problems.
9. **Bare-URL / unstyled output.** Script-only messages that print raw URLs or plain labels miss the standing user preference for clickable `[text](url)` links and the emoji house style. Apply the shared style (see `references/cron-message-house-style.md`) to every user-facing cron message, not just LLM briefs.
9b. **Channel-unaware formatting in script-only jobs.** Script-only (`no_agent: true`) jobs deliver stdout verbatim — the script IS the message. If the script uses Telegram-style `━━━` dividers but delivers to Slack, the user sees literal dashes. If it omits hyperlinks, the user gets bare URLs. **Every script-only job must know its delivery channel** and format accordingly:
   - **Telegram**: `━━━` dividers, emoji headers, `•` bullets, `[text](url)` hyperlinks
   - **Slack**: box-drawing `───` dividers or blank lines + bold headers, `•` bullets, `[text](url)` hyperlinks, no `━━━`
   - **Both**: hyperlink every referenced item (docs, tools, re-connect URLs), add a docs footer with `📖 [Hermes docs](url)`
   - **Detection**: grep script output for `━━━` — if found and the job delivers to Slack, the script needs a Slack-aware patch. Also check for bare URLs (no `[text](url)` wrapping).
   - **Verification**: after patching, `python3 -m py_compile` the script, then check the diff for channel-appropriate dividers and hyperlinks.
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
20. **Library function sets output field from search parameter, not actual data.** When a function like `parse_assignments(names=[""])` uses the search term as the `person` field value, calling it with an empty/wildcard parameter silently produces `person=""` for every record. Downstream filtering (`if a["person"] == subscriber_name`) then matches nothing — scripts appear to work (no errors) but never produce output. Always add an "all-mode" (`names=None` or `["*"]`) that sets the field from the actual cell value, not the query string. Test with real data: verify `person` contains real names, not empty strings. This was found in a senior engineer review of the WhatsApp subscriber system (Jun 2026) — briefing and reminder scripts were silently broken.
21. **Senior engineer review before deploying multi-script systems.** When building 3+ scripts that share a library, delegate a review to a fresh subagent before going live. The reviewer should read all scripts + the shared lib + existing infrastructure, and check for: (a) functions that produce empty fields from wildcard parameters, (b) missing domain logic (e.g. `consolidate_changes()` not called), (c) silent failure paths (DM send returns False but caller doesn't check), (d) non-atomic state writes (crash mid-write corrupts JSON), (e) shared file races between sibling crons. This review found 2 critical + 5 moderate bugs in the WhatsApp subscriber system that would have caused silent failures in production.
22. **Hermes cron runner script timeout — configurable, default 120s.** The cron runner kills any script that exceeds its wall-clock timeout. The default is 120s, but it is **configurable** via (a) `cron.script_timeout_seconds` in config.yaml (`hermes config set cron.script_timeout_seconds 300`), (b) `HERMES_CRON_SCRIPT_TIMEOUT` env var, or (c) a module-level `_SCRIPT_TIMEOUT` monkeypatch. Priority: module > env > config > default. A `no_agent` script that uses `subprocess.run(cmd, timeout=N)` internally must ensure the sum of all internal subprocess timeouts fits under the configured cron timeout (leaving margin for Python startup + overhead). If a script genuinely needs more time (e.g. `qmd embed` for a large wiki), bump `cron.script_timeout_seconds` rather than truncating the subprocess timeout — most scripts finish in seconds so raising the global limit is safe. Also add `subprocess.TimeoutExpired` exception handling so internal timeouts degrade gracefully instead of crashing. Verify with `py_compile` + local run + `hermes cron run <job_id>`. The `qmd_refresh.py` script was updated to use `timeout=230` for `qmd embed` with `cron.script_timeout_seconds=300` — giving embeddings plenty of room while keeping 70s margin.
23. **Wrapper subprocess timeout must exceed the underlying tool's own timeouts.** When a `no_agent` wrapper script calls an underlying tool via `subprocess.run(cmd, timeout=N)`, the wrapper's timeout must be strictly greater than the sum of the underlying tool's internal HTTP/API timeouts plus any retry paths. Example: `triage_warmup.py` called `triage.py` with `timeout=15`, but `triage.py`'s internal Ollama HTTP timeout was 30s (plus a possible 30s retry path). Cold-start model reloads — exactly what warmup exists to handle — were being killed at 15s before the model could finish loading. **Fix:** read the underlying tool's source to find its internal timeouts, then set the wrapper timeout to at least (internal_timeout + retry_timeout + 30s margin). For triage, the fix was `timeout=90` (30s HTTP + 30s retry + 30s margin). Also consider: if the underlying tool's model is hung (loads but never responds), even a generous timeout won't help — the wrapper should also handle `TimeoutExpired` gracefully and report the specific failure rather than a generic "timeout" message.
24. **Stdout contamination from `sitecustomize.py` breaks JSON parsing in subprocess calls.** A `sitecustomize.py` module (e.g. slack-enhancements, profiling tools, coverage instrumentation) can print a banner to **stdout** on every Python invocation. When a precheck script calls `subprocess.run(['python', 'google_api.py', ...])` and then does `json.loads(r.stdout)`, the banner text before the JSON causes a `JSONDecodeError`. This is especially insidious because: (a) the banner `[slack-enhancements] sitecustomize loaded...` starts with `[` — the same character as a JSON array — so naive "find the first `[`" extraction grabs the banner, not the JSON; (b) a bare `except Exception: break` in the retry loop catches the `JSONDecodeError` and **breaks** before the `uv run --with <deps>` fallback attempt is tried, so the script reports `command_failed: JSONDecodeError` instead of either succeeding or reporting the real `ModuleNotFoundError`; (c) it affects ALL sibling precheck scripts simultaneously, making it look like a systemic Google auth failure when credentials are actually fine. **Fix:** add an `_extract_json(stdout)` helper that tracks byte offsets through lines and finds the first line whose `.strip()` is exactly `[` or `{` (the JSON start), with a fallback that finds `{` anywhere (banners never contain `{`). Catch `json.JSONDecodeError` separately with `continue` (not `break`) so the uv fallback is still tried. See `references/stdout-contamination-fix.md` for the full implementation, debugging path, and sibling-spread pattern.
### Cron output file accumulation from high-frequency no_agent jobs

`no_agent` cron jobs save every run's stdout to `cron/output/<job_id>/` as
timestamped `.md` files. A job running `* * * * *` (every minute) generates
~1,440 files/day. Over weeks this reaches tens of thousands of files and
hundreds of MB — all containing identical banner text if a contamination issue
was active.

**Mitigation:**
- After fixing contamination on a high-frequency job, delete its accumulated
  output files: `find cron/output/<job_id>/ -name "*.md" -delete`
- For ongoing hygiene, periodically prune output dirs to the latest N files
  (e.g. keep 5): `ls -t cron/output/<job_id>/ | tail -n +6 | xargs -I {} rm
  cron/output/<job_id>/{}`
- Consider adding a weekly tidy-up cron that prunes all cron output dirs to
  their latest 10 files. The existing `hygiene_guard.py` is a good home for this.
- When auditing cron jobs, always check `du -sh cron/output/<job_id>/` and
  file counts — a large number signals either a contamination issue or a
  high-frequency job that should be paused after its event window ends.

### Post-event cron cleanup

When a time-bounded event cron (sports tournament, conference, travel) ends,
pause the job — don't leave it running silently every minute/day. An
every-minute job that produces empty stdout still writes a 4KB output file
per run (~5.7MB/day of empty files) and clutters `cron/output/`.

**Pattern:** after the event, `cronjob action='pause'` the job. Keep the job
definition (not `remove`) so it can be re-enabled or cloned for the next event
with updated schedule data.

24. **`sitecustomize.py` stdout banner delivered as cron message to user.** The same `sitecustomize.py` banner that breaks JSON parsing has a **second, more severe failure mode**: `no_agent` cron scripts deliver stdout verbatim to Telegram/Slack. If `sitecustomize.py` prints to stdout (not stderr), every cron job that invokes Python sends the banner text as a user message. High-frequency jobs are catastrophic — an every-minute NCW alerts job sent **12,624 duplicate banner messages** over ~9 days. 14 cron jobs were simultaneously affected. **Fix:** always use `print(..., file=sys.stderr)` in `sitecustomize.py` — cron's `no_agent` delivery path only reads stdout, so stderr banners are invisible to the user. **Detection:** when a user reports "keeps looping" or repetitive messages, check `cron/output/*/` for repeated banner lines and look for every-minute schedules. **Cleanup:** delete contaminated output files after fix — they contain only banner text, no real alerts. See `references/stdout-contamination-fix.md` → "Second failure mode" section for full detail.
25. **Batch model flip: update all LLM-driven cron jobs in one parallel turn.** When the user says "change each cron job to use the fast model," don't update one at a time. List all jobs, classify them (formatting → local fast, reasoning → keep cloud), then fire all `cronjob action=update` calls in parallel. The `cronjob` tool supports concurrent calls — all 17 updates in this session completed in a single turn. Pattern: (a) `cronjob action=list` to get the full landscape, (b) classify each job against the model-selection framework in `references/cron-model-selection.md`, (c) fire all updates in one batch, (d) spot-check 2-3 jobs to verify. Also add the `ask` skill to every LLM-driven job so they can delegate sub-tasks to other models if needed. The `ask` skill's alias registry includes `fast`/`qwen`/`local` → `qwen3.6:35b-a3b`. **Pitfall:** don't change model AND prompt simultaneously on recently-debugged jobs (e.g. eod-forecast) — keep them on their current model until the new prompt stabilizes, then flip the model in a separate pass.
26. **"Flag but don't act" anti-pattern in watchdog scripts.** A watchdog that classifies entries and flags some as "candidates for action" but never acts on them is a dead-end — the user sees the same flagged items every run with no resolution. The memory-pressure watchdog had this exact bug: skill-classified entries were flagged as "skill creation candidates" but the script never created skills, and the `no_agent=True` cron had no LLM to follow up. **Fix:** either (a) auto-act on the classification (e.g. auto-offload entries that match existing skills via a curated keyword→skill table), or (b) convert to `no_agent=False` with an LLM that can actually create the skills. The auto-act path is preferred — it's deterministic, testable, and costs zero tokens. The key design insight: entries that don't match any existing skill are NOT "skill candidates" — they're operational config (cron job IDs, bug fix history, user-specific workflow preferences) that rightfully belong in memory. Don't flag them as needing action.

27. **`hermes --accept-hooks` must go BEFORE the subcommand, not after.** `hermes cron edit <id> --script "foo.py" --accept-hooks` fails with `unrecognized arguments: --accept-hooks`. The correct form is `hermes --accept-hooks cron edit <id> --script "foo.py"`. This applies to ALL Hermes subcommands (`cron`, `config`, `kanban`, etc.) — global flags always precede the subcommand. The error is easy to miss because the Bitwarden warning banner prints before the usage error, making it look like a credential issue. This was encountered during a self-healing cron repair session (Jul 2026) where the trace diagnostic's fix instructions used the wrong flag order.

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

**GLM language quirk:** GLM models (`glm-5.2:cloud`) default to Chinese output. Any cron job using GLM MUST have `CRITICAL: ALL output MUST be in English...` as the first line of its prompt. See `model-fallback-config` skill pitfall #10 for the full directive and audit pattern.

**How to flip model:** `cronjob action=update job_id=<id> model={"model": "claude-haiku-4-5-20251001", "provider": "anthropic"}` — the update API supports model changes cleanly. Verify with `cronjob action=list`.

## LLM alert phrasing: actor → action → affected person

For cron alerts about schedule changes, assignments, or any event where a human made a change to another person's slot, phrase every line as:

> **`<actor> did <action> to <affected person>`**

- `changed_by added 🟦 Person as Role · context`
- `changed_by removed 🟪 Person from Role · context`
- `changed_by replaced 🟦 Person with Replacement in Role · context`
- `changed_by moved 🟪 Person into Role, replacing OldPerson · context`

Use "system" when `changed_by` is "unknown". Strip credential tags from names ("Les Simonton (IWF 1)" → "Les Simonton"). This phrasing is clearer than person-centric ("The User was removed by…") because it puts the actor first — who is responsible — then what they did, then who it affected.

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

## Precheck patterns for research/audit crons

### Errored-job detail gathering

When a precheck script reports cron health, don't just count errors — list the
errored jobs with their names, scripts, schedules, and last-run timestamps.
This gives the agent the exact context it needs to investigate without spending
tokens discovering which jobs are broken.

```python
def get_cron_status() -> tuple[str, list[dict]]:
    jobs_json = HERMES_HOME / "cron" / "jobs.json"
    data = json.loads(jobs_json.read_text())
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    enabled = [j for j in jobs if j.get("enabled", True)]
    errored = [j for j in enabled if j.get("last_status") == "error"]
    summary = f"{len(enabled)} enabled, {len(errored)} errored, {sum(1 for j in enabled if j.get('no_agent', False))} no-agent"
    details = [{"name": j.get("name"), "script": j.get("script"),
                "schedule": j.get("schedule", {}).get("display", j.get("schedule", "?")) if isinstance(j.get("schedule"), dict) else j.get("schedule", "?"),
                "last_run": j.get("last_run_at")} for j in errored]
    return summary, details
```

**Pitfall:** `schedule` field in `jobs.json` can be a dict (`{"kind": "cron",
"expr": "..."}`) or a string — handle both before formatting.

### Proposal tracker for recurring research crons

When a cron job presents proposals/recommendations that the user may act on
across multiple weeks, maintain a `cron/state/research_proposals_seen.json`
state file to prevent re-proposing the same thing:

```python
PROPOSAL_TRACKER = HERMES_HOME / "cron/state/research_proposals_seen.json"

def load_proposal_tracker() -> list[dict]:
    if PROPOSAL_TRACKER.exists():
        return json.loads(PROPOSAL_TRACKER.read_text())
    return []

def format_proposal_history(proposals: list[dict]) -> str:
    if not proposals:
        return "None (first run or no prior proposals)"
    return "\n".join(f"  - [{p.get('date')}] {p.get('title')} → {p.get('disposition')}"
                     for p in proposals)
```

The precheck passes prior proposals to the agent with the instruction: "Do NOT
re-propose items listed above unless circumstances have materially changed."
The agent appends new proposals to the tracker file after delivering the briefing.

**Schema:** `[{"title": "...", "date": "YYYY-MM-DD", "disposition": "presented|implemented|skipped|deferred"}]`

### Change signature for delta detection

Track a composite signature of watched paths (file sizes + mtimes) to detect
what changed since the last cron run. This lets the agent focus on deltas rather
than re-researching everything from scratch:

```python
def dir_checksum(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(path)}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]
```

Compare the current signature against the last-run signature stored in state.
Pass `Changed: YES/no` to the agent so it knows whether to focus on what's new.

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

## Token-efficiency passes: preserve user-approved visuals

When compressing memory entries or cron output for token efficiency, the guiding
question is "is this the most token-efficient manner to express this?" — BUT
token efficiency applies to *information density*, not *aesthetics the user
explicitly likes*. A user who approved progress bars, emoji section headers,
and specific phrasing ("Wiki offload candidates", "Keep as-is") wants those
kept. Strip boilerplate footers and redundant labels, not visual identity.

Concrete example: the memory-pressure watchdog was "optimized" by removing
progress bars and renaming sections to shorter labels. User corrected twice:
"No I like the progress bars and status and emojis" and "No I like the old
language a bit better." The fix was keeping all visuals and only applying
real bug fixes (correct USER_LIMIT, bar clamp at 100%).

## Auto-offload vs report-only: user preference for autonomous action

When the user says "I want this to be automatic, not asking for permission,"
convert watchdog scripts from report-only to auto-action mode. The
memory-pressure watchdog was converted on 2026-06-25 from report-only (which
required Jim to review candidates before removal) to auto-offload (which
removes wiki-classified entries from MEMORY.md directly when QMD is active).
The user's exact words: "I want this to be automatic, not asking for permission
to make changes."

**Key safety constraint:** auto-offload only wiki-classified entries (lookup
knowledge — version numbers, binary paths, config details). Do NOT auto-offload
skill-classified entries (procedures requiring agent judgment to create) or
keep-classified entries (identity/preference). See
`references/memory-pressure-watchdog.md` for the full auto-offload policy.

**General principle:** when a user explicitly requests autonomous action for a
specific watchdog, honor it — but build in safety guards (classification
heuristics, threshold checks, QMD-active verification) so the auto-action is
safe. The user wants trust with guardrails, not unconditional automation.

## DM-delivery cron pattern (deliver: local)

When a no-agent script's primary output is sending WhatsApp DMs (or any
direct message) as a side effect — not printing to stdout — set
`deliver: local` on the cron job. The script sends DMs via the bridge API
directly; stdout is empty so the scheduler delivers nothing. This prevents
double-delivery (DM + cron stdout going to the origin channel).

Pattern:
```text
script: to_subscriber_changes.py
no_agent: true
deliver: local
```

Script contract:
- Exit 0 with empty stdout: DMs sent (or no DMs needed). Scheduler delivers nothing.
- Non-zero exit: scheduler sends error alert (as usual).
- DM sending uses `send_dm_safe()` with retry + backoff for bridge hiccups.
- Add 1s sleep between DMs when looping multiple subscribers (rate limit guard).

## Baileys bridge /messages is destructive — do NOT poll from scripts

The Baileys bridge (`localhost:3000`) exposes `GET /messages` which **drains**
the message queue (JavaScript `splice(0, queue.length)` — destructive read).
The Hermes gateway adapter polls this endpoint continuously to receive incoming
WhatsApp messages. Any script that also calls `GET /messages` creates a race
condition: whoever polls first wins, the other gets nothing.

This means: **scripts cannot poll for incoming WhatsApp messages** without
stealing them from the gateway. For subscription/interaction flows that need
to read incoming messages, use either:
- **Agent-native**: the agent receives messages via the gateway normally and
  handles the conversation with prompt-level privacy guards (recommended for
  small-scale subscription flows).
- **Dedicated profile**: a separate Hermes profile with its own WhatsApp number
  and bridge instance (full isolation, needs 2nd number).

Never: a cron script that `curl localhost:3000/messages` — it will silently
swallow messages meant for the agent.

## QMD embedding refresh cron

When QMD semantic search is active on a wiki collection, vector embeddings go
stale as pages are added/changed by ingest crons. Add a daily `no_agent` cron
that runs `qmd update` (re-index changed files) + `qmd embed` (refresh vector
embeddings) silently. Only emits output on failure. Keeps the memory-pressure
watchdog's "searchable via QMD" claim accurate. See
`references/memory-pressure-watchdog.md` for the full pattern.

## Config inspection: check credential files before reporting missing

When enabling an MCP server or integration that requires OAuth credentials, **always
inspect existing credential files first** before telling the user something is missing.
Hermes stores OAuth client credentials in multiple locations:

- `.env` — env-var-based credentials (`GDRIVE_MCP_CLIENT_ID_*`, `SLACK_BOT_TOKEN`, etc.)
- `google/accounts/<alias>/client_secret.json` — Google OAuth client credentials
- `google/accounts/<alias>/token.json` — Google OAuth tokens
- `auth.json` — Hermes auth provider tokens
- `config.yaml` — inline config with `${VAR}` references to `.env`

**Pattern:** before reporting "credentials not set, you need to create them":
1. `grep -i <EXPECTED_VAR> .env` — check env vars
2. `ls google/accounts/*/client_secret*.json` — check Google credential files
3. `grep -i <keyword> config.yaml` — check inline config
4. Extract from existing files with Python if found

**User correction (Jun 2026):** "When asking me to change config, always first inspect
that the expected values are missing or misconfigured first." The agent reported Google
Drive MCP credentials were missing from `.env` and told the user to create them in GCP
Console — but the OAuth client already existed in
`google/accounts/personal/client_secret.json` (shared client for both personal + nonprofit).
The fix was extracting the existing client_id/secret and adding to `.env` — 2 minutes,
not 10 minutes of GCP Console work.

**General rule:** credential files may already exist from a prior related integration
setup. Google OAuth clients are shared across multiple Google APIs (Drive, Gmail,
Calendar, Sheets) — the same `client_secret.json` can provide credentials for multiple MCP
servers. Always check before telling the user to create new credentials.

## Recommended Next Step

For active systems, schedule a weekly no-agent cron audit that reads cron metadata, classifies jobs, and reports only configuration-level token-waste candidates. It should not read private message bodies or mutate jobs.

## Skills Hub skill structure (for publishing cron-based skills)

When a cron-based system evolves from deployment-specific scripts into a reusable
Skills Hub skill, follow the optional-skills conventions (researched from
`here-now`, `honcho`, `solana`, `blackbox` in `optional-skills/`):

### Frontmatter additions for Hub skills

```yaml
prerequisites:
  pip: [pyyaml, openpyxl]        # declare Python deps
  commands: [curl]               # declare CLI deps
metadata:
  hermes:
    requires_toolsets: [terminal] # conditional activation
    config:                       # declarative config keys
    - key: my_skill.setting
      description: "What this controls"
      default: "value"
      prompt: "Setup question for the user"
```

### Setup script pattern (`scripts/setup.py`)

Agent-mediated, non-interactive (same pattern as `google-workspace/scripts/setup.py`):
- `--check` → are deps + config ready? Exit 0/1
- `--init` → create config.yaml from template (agent fills values)
- `--install-deps` → install pip prerequisites
- `--create-crons` → create no_agent cron jobs
- `--test-dm <phone>` → verify bridge connectivity

### Config separation principle

- **Skill dir** (version-controlled): `SKILL.md`, `scripts/`, `references/`, `templates/`
- **State dir** (deployment-specific): `config.yaml`, `subscriptions.json`, state files
- Scripts read config via env var (`MY_SKILL_CONFIG=path/to/config.yaml`)
- No hardcoded deployment values (sheet IDs, phone numbers, bridge URLs) in scripts
- `templates/config.example.yaml` documents all keys for new deployments

### Self-containment rule

A Hub skill must not import modules outside its own `scripts/` directory. If the
skill needs a sheet parser, ship one. Don't depend on user-local scripts like
`usaw_to_lib.py` — they won't exist on other deployments.

### Layered architecture for testability

When a skill has multiple concerns (drive polling, sheet parsing, subscriptions,
notifications), separate them into layers with clean interfaces:

- Each layer has a single responsibility
- Leaf layers (no imports from other layers) are pure and independently testable
- Cron orchestrators are thin wiring — no business logic
- Dependency graph flows one direction (no circular deps)

See `references/whatsapp-to-subscriber-system.md` for a 5-layer example
(Drive → Sheet → Subscriptions → Management → Notification).
