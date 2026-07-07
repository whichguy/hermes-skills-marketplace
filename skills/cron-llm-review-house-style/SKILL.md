---
name: cron-llm-review-house-style
description: Convert script-only Hermes cron jobs into script→LLM-review→pretty-delivery
  pipelines so every scheduled message is evaluated for false alarms/actionable items
  and formatted in a consistent emoji+hyperlink house style. Use when a user wants
  prettier cron output, LLM evaluation of cron responses, or to stop false-alarm/all-clear
  noise.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - cron
    - formatting
    - llm-review
    - telegram
    - house-style
    - false-alarm
    created_by: agent
    related_skills:
    - script-first-cron-design
    - messaging-platform-formatting
    config:
    - key: cron-llm-review-house-style.enabled
      description: Enable cron-llm-review-house-style skill behavior
      default: true
      prompt: Enable cron-llm-review-house-style skill?
    category: devops
platforms:
- linux
- macos
- windows
---


# Cron LLM-Review + House Style

## Overview

Pattern for upgrading Hermes cron jobs from raw script-only delivery to a
**script (precheck) → LLM review → pretty delivery** pipeline. The LLM both
**evaluates** the script output (is anything actionable / wrong / a false alarm?)
and **formats** it in a consistent house style with emojis and clickable links.

This is the inverse tradeoff of pure `script-first-cron-design`: you spend tokens
to gain judgment + presentation. Use it when the user explicitly wants prettier
output AND/OR LLM evaluation of every response. Combine the two skills: keep the
deterministic script as the data collector, add the LLM as reviewer/formatter.

## When to Use

- User asks to "fancy up" / prettify cron job responses.
- User wants the LLM to evaluate every cron response for errors/actionable items.
- A script-only watchdog produced a false alarm that got delivered verbatim.
- You want consistent emoji + hyperlink formatting across all scheduled messages.

Do NOT use for jobs where the user wants zero token cost and trusts the raw
script output — keep those `no_agent: true`.

## Key Mechanics (verified against Hermes source)

1. **`no_agent: false` + a `script`** = the script runs first as a precheck and
   its stdout is injected into the LLM prompt under `## Script Output`. The LLM's
   final response is what gets delivered. (`hermes cron edit <id> --agent` flips
   off no-agent mode; `--no-agent` flips it back on.)
2. **Silent suppression**: if the LLM final response is EXACTLY `[SILENT]`,
   delivery is suppressed but output is still saved to `cron/output/<id>/` for
   audit. Sentinel is `SILENT_MARKER = "[SILENT]"` in `cron/scheduler.py`.
3. **Zero-cost quiet ticks**: if the precheck script prints NOTHING (empty
   stdout), the scheduler skips the LLM entirely — so frequent watchers
   (every 15m/2h) only cost tokens when the script actually emits data. Design
   scripts to stay silent on non-events.
4. **Toolsets**: restrict via `enabled_toolsets` to the minimum
   (`terminal`, `file`, optionally `skills`) to keep cost/permissions low.

## Conversion Steps

1. List jobs, never guess IDs: `hermes cron list` or the `cronjob` tool.
2. For each script-only job to convert:
   - `hermes cron edit <id> --agent --prompt "<job intro>\n\n<shared review prompt>"`
   - Set minimal toolsets via the `cronjob` update action `enabled_toolsets`.
3. **Strip contradictory old instructions** like "deliver the script stdout
   verbatim and do not use an LLM" / "Empty stdout means no update" — they fight
   the new review step. (Regex them out of the prompt.)
4. For jobs that were ALREADY LLM-driven, just append the shared review prompt
   so they share the same evaluation+formatting standard.
5. Keep the one-off/transient jobs (e.g. a single-fire reminder) as-is unless
   asked.

## Channel-Aware Formatting (CRITICAL — Telegram ≠ Slack)

Cron jobs deliver to different channels. The formatting rules differ by channel.
**Always check the job's `deliver` field** before writing or updating its prompt.

### Telegram formatting

- Emoji-led bold title + `━━━━━━━━━━━━━━━` divider (renders as a clean line on Telegram)
- Short emoji sections; bold labels; compact `•` bullets
- **Hyperlink every referenced item using Markdown links**: `[descriptive text](url)` — never bare URLs. The Hermes adapter converts these to Telegram MarkdownV2 format automatically.
- **Bold** uses `**text**` (adapter converts to MarkdownV2 `*text*`)
- Status icons 🟢🟡🔴⚪
- Pacific time friendly labels (never raw UTC/ISO)
- **No Markdown tables** — Telegram cannot render them. Use bullet groups instead.
- Keep paragraphs short; Telegram is read on mobile

### Slack formatting

- **NO `━━━` dividers** — these render as literal dashes on Slack. Use:
  - `─────────────────────────` (box-drawing characters) for horizontal separators, OR
  - A blank line + bold header to separate sections
- **Markdown tables are OK** — Slack renders them correctly. Use tables for structured data (watchlists, standings, model comparisons, recommendations). Keep tables compact: 3-5 columns, 5-8 rows max. Hyperlink text inside table cells.
- **Bold** for section headers: `**Section Title**`
- **Bullet groups** for per-item summaries, not prose blocks
- **Hyperlink all referenced items**: `[descriptive text](url)` format
- Keep it concise — Slack messages should be scannable, not long prose blocks
- Target 400-600 words for weekly briefings; 2-3 lines per item for daily digests

**Note:** The `cron-output-standards` skill is the authoritative source for channel-aware formatting. This section mirrors it for convenience; if they differ, `cron-output-standards` wins.

### Channel-agnostic rules (both platforms)

- **Hyperlink rule is non-negotiable**: every referenced package, tool, resource, thread, wiki page, or external reference must be a clickable `[descriptive text](url)` Markdown link. Never paste bare URLs. The Hermes adapter converts Markdown links to the platform-native format.
- **SILENT rule**: reply EXACTLY `[SILENT]` when nothing is actionable/worth showing
- **Evaluate before formatting**: flag false alarms, tooling glitches, wrong-timezone timestamps, broken links, duplicates. Never relay a likely glitch as a confirmed problem.

### Embedding channel rules in prompts

When writing or updating a cron job prompt, embed the channel-specific rules directly:

**For Telegram-delivered jobs:**
```
## Output — Telegram house style (REQUIRED)
- Emoji-led bold title + `━━━━━━━━━━━━━━━` divider
- Short emoji sections; bold labels; compact `•` bullets
- NEVER use Markdown tables — use bullet groups
- Hyperlink every referenced item: `[descriptive text](url)` — never bare URLs
- Bold uses `**text**`
```

**For Slack-delivered jobs:**
```
## Output formatting — Slack-aware (REQUIRED)
- Markdown tables are OK for structured data — keep them compact (3-5 columns, 5-8 rows max)
- NO `━━━` dividers — use blank line + bold header to separate sections
- Bold section headers: `**Section Title**`
- Hyperlink all referenced items: `[descriptive text](url)`
- Keep it concise — scannable, not long prose blocks
```

**For `deliver: origin` jobs** (auto-detected channel): check which platform the origin chat is on. In a Slack workspace, use Slack rules. On Telegram, use Telegram rules.

## Shared Review Prompt → cron-output-standards Skill

Instead of inlining the review/format prompt into every job, create a
**`cron-output-standards` skill** (`devops/cron-output-standards`) and attach
it to each converted job via `--add-skill cron-output-standards`. Hermes
auto-injects skill content into cron job prompts at runtime, so the
formatting rules live in one place and every job stays in sync.

The skill must instruct the LLM to:

- **Evaluate**: flag anything actionable; detect false alarms / tooling glitches
  (e.g. `ModuleNotFoundError` misreported as an auth failure, pre-tournament
  zeros that look like a data glitch, wrong-timezone timestamps, broken links,
  duplicates). Never relay a likely glitch as a confirmed problem — suppress it
  or label it clearly with the fix.
- **Format** (house style): follow the channel-aware rules above based on the
  job's delivery target. Telegram: emoji-led bold title + `━━━━━━━━━━━━━━━`
  divider, short emoji sections, bold labels, compact `•` bullets, no tables.
  Slack: no `━━━` dividers (use box-drawing `───` or blank lines), bold headers,
  bullet groups, tables OK for structured data. Both: **hyperlink every referenced
  item** with descriptive link text; status icons 🟢🟡🔴⚪; Pacific time friendly
  labels (never raw UTC/ISO).
- **SILENT rule**: reply EXACTLY `[SILENT]` when nothing is actionable/worth
  showing (suppresses delivery, no all-clear noise).
- **English-only**: the skill also carries the "all output must be in English"
  directive so individual job prompts don't need to repeat it.

This pattern cut total cron prompt size by 48% (120K → 62K chars) by eliminating
the 4,887-char house style block that was inlined in 11 jobs, plus the 130-char
English-only prefix in 13 jobs.

## Shared Style Helpers

Optionally back the scripts with a `cron_style.py` module exposing `header`,
`section`, `bullet`, `kv`, `link`, `local_time`, `now_label`, `render` so the raw
script output is already close to house style and the LLM mostly reviews/links.

## Verification (always do this)

1. Run a job WITH data (e.g. a sports/schedule job): `cronjob run <id>` then
   `hermes cron tick`, and read `cron/output/<id>/<newest>.md` — confirm the
   `## Response` section is pretty + links work + false-alarm caveats appear.
2. Run a HEALTHY watchdog (e.g. auth guard) the same way — confirm the output
   file is empty / `[SILENT]` and nothing was delivered.
3. Re-list jobs to confirm `no_agent`, `enabled_toolsets`, and prompt changed.

## Pitfalls

1. Leaving the old "do not use an LLM / deliver verbatim" line in the prompt — it
   contradicts the review step and confuses the model. Strip it.
2. Forgetting that empty script stdout skips the LLM — good for cost, but means
   the LLM can't "speak up" when the script SHOULD have produced output but
   didn't. For health checks, make the script emit a terse line on real failure,
   nothing on success.
3. Over-broad toolsets — cron LLM jobs only need `terminal`/`file`/`skills`.
4. A script that crashes on a missing dependency can masquerade as a domain
   error (the google-auth-guard `invalid_grant` false alarm). Give Google
   scripts a `uv run --with google-api-python-client --with google-auth-oauthlib
   --with google-auth-httplib2` fallback and only classify a real auth error when
   the dependency actually loaded.
5. Cost on frequent watchers — acceptable only because empty-stdout ticks skip
   the LLM. If a watcher emits output every tick, reconsider before converting.
6. **Bulk conversion misses jobs with inline house style but no `cron-output-standards` skill.** When converting a batch of jobs from inline house style to the shared skill, the initial pass may miss jobs whose prompts contain house-style instructions but weren't flagged because they use different phrasing (e.g. "Produce a Telegram-friendly summary using the house style" vs the full divider/emoji block). After the bulk conversion, always audit ALL remaining agent jobs for residual inline formatting instructions — grep for "house style", "Telegram-friendly", "emoji headers", "bold labels", "status icons", "clickable links", and `━━━`. The Node.js dependency watchdog, Python dependency watchdog, and self-healing cron watchdog were all missed in the initial 11-job conversion because their inline house style used different wording. Fix: add `cron-output-standards` skill and strip the inline formatting block from each missed job.

7. **Skill collision causes "⚠️ Skill(s) not found and skipped" in every cron delivery.** When a skill attached to a cron job exists in BOTH the local skills dir (`/opt/data/skills/`) AND an `external_dirs` entry, `skill_view()` returns "Ambiguous skill name" and the cron scheduler prepends a warning to every delivered message. This is a silent degradation — the job still runs, but every message starts with a noisy warning.

   **Root cause (discovered Jul 2026):** The `skills.external_dirs` config entry pointed to `/opt/data/hermes-agent/skills/` (the upstream git clone for development). Hermes already syncs bundled skills from the installed package (`/opt/hermes/skills/`) → the user skills dir (`/opt/data/skills/`) via the `.bundled_manifest` mechanism. Adding the hermes-agent git clone as an external_dir created duplicates for all 68 bundled skills that were already synced. The config change was introduced between June 28 and July 3, 2026 (visible in git history of `config.yaml`).

   **Fix (simplest):** Remove `/opt/data/hermes-agent/skills` from `skills.external_dirs` in `config.yaml`. The bundled skills are already synced to `/opt/data/skills/` — the external_dir is redundant and creates ambiguity. Keep only the marketplace path (`/opt/data/hermes-skills-marketplace/skills`) if it doesn't duplicate locally-installed skills.

   **Belt-and-suspenders:** Rename `hermes-agent/skills/` → `hermes-agent/_skills/` so it can never be accidentally re-added to external_dirs. The `_` prefix keeps it out of the skill search path even if someone re-adds the parent directory.

   **Workaround (if you can't change config):** Use category-prefixed names — `productivity/google-workspace` instead of bare `google-workspace`. The qualified name resolves unambiguously because `skill_view()` searches `category/name` subdirectories directly.

   **Verification:** force-run a single low-risk job, check `cron/output/<id>/<newest>.md` — confirm no "Skill(s) not found" warning and all attached skills appear in the `## Prompt` section. Full recipe in `references/skill-collision-fix.md`.
