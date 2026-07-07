# Script → LLM-review → pretty-delivery cron pattern

When the user wants cron updates that are (a) evaluated for anything wrong /
actionable / false-alarm before delivery AND (b) consistently, prettily
formatted with clickable links, do NOT keep them as pure `no_agent: true`
script-only jobs. Pure script-only output is delivered verbatim with no LLM, so
nothing reviews it — that is exactly how a false alarm reaches the user.

Convert each such job to **precheck-plus-LLM** mode:

1. `no_agent: false` — the existing watchdog script becomes a *pre-run data
   collector*; its stdout is injected into the LLM prompt as `## Script Output`.
2. Attach a shared review+style prompt (see `cron_review_prompt.md` pattern
   below) telling the LLM to (i) evaluate the data and (ii) format it.
3. Set minimal toolsets (`terminal`, `file`, and `skills` only when a skill is
   attached). Avoid `web`/`browser` unless the job needs them.

## Why this stays cheap (the key scheduler mechanic)

`cron/scheduler.py` `_build_job_prompt`: if the attached script produces **empty
stdout**, the scheduler returns `None` and **skips the LLM call and delivery
entirely**. So a watchdog that prints nothing on healthy/no-event ticks costs
ZERO tokens — the LLM only runs when the script actually emitted something.
This is what makes "review every job" affordable even for a 15-minute watcher.

## The [SILENT] suppression marker

`cron/scheduler.py` defines `SILENT_MARKER = "[SILENT]"`. If an LLM cron job's
response *starts with* `[SILENT]`, delivery is suppressed (output still saved to
`/opt/data/cron/output/<job_id>/` for audit). This lets the LLM kill a
false alarm or an all-clear that the script emitted but that does not warrant
pinging the user. The cron runner also auto-injects a delivery/SILENT preamble,
but stating the rule explicitly in the prompt makes it reliable. Never combine
`[SILENT]` with content — it is the whole response or not used at all.

## Shared review+style prompt (the two jobs)

Keep one reusable prompt block (this repo: `${HERMES_HOME}/scripts/cron_review_prompt.md`)
appended to every job so the standard is identical everywhere:

- **Evaluate**: is anything actionable? Does anything look wrong, contradictory,
  stale, or like a false alarm / tooling glitch (e.g. an auth error that is
  really a missing dependency, a "0 results" that contradicts other fields, a
  wrong-timezone timestamp, a broken link, a duplicate already reported)? If a
  likely false alarm, either suppress with `[SILENT]` or present it *clearly
  labeled as a possible glitch with the fix* — never as a confirmed problem.
  Make any genuine action explicit near the top with a clickable link.
- **Format** (house style): emoji-led bold title + `━━━` divider; short
  emoji sections; bold labels; compact `•` bullets; hyperlink every referenced
  item with descriptive text `[Google Calendar event](url)` (never bare URLs);
  status icons 🟢🟡🔴⚪; Pacific time friendly labels, never raw UTC/ISO; no
  tables; preserve privacy/read-only footers.
- **SILENT rule** + **negative-result rule**: no "all clear" / "no items"
  messages for individual sources.

A small presentation helper module (`${HERMES_HOME}/scripts/cron_style.py`) gives
deterministic helpers (`header`, `section`, `kv`, `bullet`, `link`,
`local_time`, `now_label`, `render`) so script-side formatting and LLM-side
formatting share one vocabulary.

## Conversion mechanics (CLI)

- Flip to LLM mode and set the prompt in one shot:
  `hermes cron edit <id> --prompt "<job intro + shared review prompt>" --agent`
  (`--agent` clears `no_agent`; `--no-agent` re-enables it.)
- Set toolsets via the `cronjob` tool `action=update` with
  `enabled_toolsets=["terminal","file","skills"]`.
- After flipping, STRIP any leftover legacy instruction lines like
  "deliver the script stdout verbatim and do not use an LLM" / "Empty stdout
  means no update" — they directly contradict the new review step.
- Verify end-to-end: `cronjob action=run <id>` then `hermes cron tick`, and read
  the saved transcript at `/opt/data/cron/output/<job_id>/<timestamp>.md`. A
  healthy silent job writes a 0-byte/empty output file (nothing delivered); a
  data job shows the prettified `## Response`.

## Pitfall fixed this session: dependency crash misread as auth failure

`google_auth_guard.py` ran `python setup.py --account <alias> --check` with bare
`python`, which lacked the Google client libs, so it crashed with
`ModuleNotFoundError` — and the classifier misread that as
`invalid_grant — refresh token revoked`, sending a scary 🔴 false alarm.

Fix (the same `uv run` fallback the working scripts already used): retry the
command through `uv run --with google-api-python-client --with
google-auth-oauthlib --with google-auth-httplib2 ...` when the first attempt
shows `ModuleNotFoundError` / `No module named`, and only classify the *real*
auth output. Lesson: a watchdog that classifies error text MUST distinguish
tooling/dependency/network failures from genuine domain failures, or it will
cry wolf. The LLM-review layer is the second line of defense for exactly this.
