# Script-first transactional cron pattern

Session-derived pattern for personal-context automations where the user needs alerts to work reliably while minimizing token use, noise, and privacy exposure.

## When to use

Use this pattern for deterministic monitoring jobs such as:

- calendar/travel/logistics alerts
- tax/CPA/source-domain watchers
- appointment reminders
- simple mailbox metadata monitors
- threshold checks where a script can decide whether to alert

Do **not** force this pattern onto jobs whose value is synthesis, ranking, or judgment, such as a morning brief or research/watchlist digest. Those should use a deterministic precheck script plus an LLM prompt.

## Preferred cron modes

### Transactional event checks

Use `script` + `no_agent: true`.

Behavior:

- Script prints nothing when there is no actionable event.
- Empty stdout means the job is silent; the user receives no message.
- Non-empty stdout is the exact user-facing alert.
- Non-zero exit produces a scheduler error alert, so broken checks do not fail silently.

### Synthesis briefs

Use a deterministic precheck script with `no_agent: false`.

Behavior:

- Script gathers compact structured context.
- LLM performs synthesis and prioritization.
- Prompt still says no external side effects, no recursive cron edits, and no memory writes.

## Script output rules

Transactional scripts should emit a Telegram-ready short alert only when needed:

```text
## 🟡 Calendar alert

**What:** Appointment may need action
**When:** 2026-06-12 09:00
**Why:** one concise reason

**Protected:** no calendar/email changes were made.
```

For sensitive monitors, output only minimal approved metadata:

- source class or approved sender/domain
- action category
- urgency
- account alias/provenance when multiple accounts are in scope

Omit:

- raw snippets/bodies
- amounts
- account numbers
- confirmation numbers
- attachment contents
- sensitive notice text

## Verification checklist

Before reporting success:

1. List cron jobs and update by real job ID; never guess IDs.
2. Confirm `script` path and `no_agent` value after update.
3. Run syntax checks for every new/changed script.
4. Exercise at least one dry/safe path for each script.
5. Confirm silent behavior for non-event cases where practical.
6. Confirm multi-account routing/account provenance for Google jobs.
7. Confirm no Gmail/Calendar/Drive mutations occurred.
8. Document the migration or verification result in the local workspace if the change spans multiple jobs.

## Pitfalls

- A cron job with `last_status: ok` only proves it ran; it does not prove it checked the right account or alert conditions.
- Do not convert synthesis briefs to `no_agent: true` just to save tokens; that removes the value of the brief.
- Do not manually run delivery-producing jobs unless the user requested a run-now check.
- Do not create duplicate jobs when an existing watcher can be refined.
