---
name: live-event-status-updates
description: Use when providing repeated live status updates for sports matches, public
  events, elections, awards, product launches, or other time-sensitive events where
  the user wants the current state, not a full explainer.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - live-updates
    - sports
    - events
    - status
    - telegram
    - current-info
    created_by: agent
    related_skills:
    - scheduled-research-briefs
    - messaging-platform-formatting
    config:
    - key: live-event-status-updates.enabled
      description: Enable live-event-status-updates skill behavior
      default: true
      prompt: Enable live-event-status-updates skill?
    category: research
platforms:
- linux
- macos
- windows
---


# Live Event Status Updates

## Overview

Use this skill when the user asks for a live or near-live status update on an unfolding event, especially when they ask short follow-ups like “update,” “new status?”, “any updates?”, or “where are we at?”

The user usually wants the latest state immediately, not background context. Lead with the live state, then only the delta since the last update.

## When to Use

Use for:

- live sports matches and tournaments
- election night results
- breaking public events
- awards shows or ceremonies
- product launches/keynotes
- market-moving public announcements
- recurring follow-up pings in the same event thread

Do not use for:

- full historical explainers
- long-form research briefs
- private monitoring automations
- non-current summaries where the user asked for analysis, not status

## Response Shape

For Telegram or chat updates, default to this order:

```markdown
## 🔴 Current status

As of: <timestamp + timezone>
Event: <event name>
Status: <clock/phase/state>

## Score / state

<one-line scoreboard or result>

## New since last check

- <only new goals/cards/lead changes/major events>

## Where we’re at

<2-4 short bullets about implications>
```

If there is no new major event, say that plainly:

```markdown
No new scoring/major event since the last check. Current state is still...
```

## Style Rules for Jim

- Put the current score/state in the first screen.
- Be concise; avoid re-explaining tournament format or background after the first summary.
- For repeated updates, emphasize “new since last check.”
- Use timestamps and source-grounded state.
- Use simple bullets, not dense paragraphs.
- Avoid gambling/odds details unless the user explicitly asks.
- If the event is live, avoid over-certainty until it is final.

## Daily schedule + standings cron updates

When the user asks for recurring World Cup/tournament updates focused on **schedule and standings**, prefer a deterministic script-only cron job over an LLM brief:

- `no_agent: true` so formatting stays stable and does not drift into raw UTC/JSON.
- Use read-only public sports APIs where possible.
- Convert all user-facing times into the user's local timezone.
- Include today's schedule, yesterday's finals, current group leaders/standings, and a one-line bottom line.
- Keep live goal/red-card/final-result alerts as a separate deduped job if requested later.

See `references/daily-world-cup-schedule-standings.md` for the ESPN FIFA World Cup schedule + standings pattern.

## Data-Gathering Workflow

1. Use a current source/API/tool before answering. Do not rely on memory for live facts.
2. Capture:
   - source timestamp or current UTC time
   - event status/phase/clock
   - score or leading state
   - completed/final flag
   - major event log if available
3. Compare against the prior assistant update in the conversation, if visible.
4. Report only new material plus the current state.
5. If the source is unavailable, say so and try one alternate source before giving up.

## Sports-Specific Notes

For soccer/football live matches, include:

- minute/status: e.g. `64’`, `90’+7`, halftime, full time
- scoreline with home/away/team names
- goals, red cards, key yellows if tactically relevant
- player names for major events
- whether the match is final before calling it a win

Avoid:

- long tactical essays during quick update loops
- repeating every old event on every update unless the user asks for a recap
- adding bookmaker odds by default

## References

- `references/espn-scoreboard-api.md` — compact recipe for using ESPN’s public scoreboard endpoint for live soccer/World Cup-style updates.

## Common Pitfalls

1. **Answering from stale context.** Live status requires a fresh lookup.
2. **Burying the score.** The user asked “where are we at?” — put score/state first.
3. **Replaying the whole event every time.** Only include full event history when useful; otherwise focus on the delta.
4. **Calling a match final too early.** Check `completed` or final status first.
5. **Letting raw API noise leak into the answer.** Summarize event details, omit odds/internal IDs unless needed.

## Verification Checklist

- [ ] Current lookup performed.
- [ ] Timestamp included.
- [ ] Current state/score is first.
- [ ] New events since last check are highlighted.
- [ ] Final/completed state is verified before declaring final result.
- [ ] Output is short enough for Telegram.
