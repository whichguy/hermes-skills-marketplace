# Cron Local-Time Formatting Pattern

Use this when a scheduled job's user-facing output is hard to read, leaks UTC, or prints raw ISO timestamps.

## Problem

Hermes cron metadata such as `next_run_at` and `last_run_at` is commonly stored/displayed in UTC. That is fine for scheduler internals, but poor for user-facing summaries, daily briefs, calendar/travel alerts, and Telegram updates.

## Durable fix

Patch both layers when applicable:

1. **Deterministic script/precheck**
   - Import `ZoneInfo` from the standard library.
   - Define an explicit user-facing timezone, e.g. `ZoneInfo('America/Los_Angeles')`.
   - Use local midnight-to-midnight windows for “today” briefs instead of `now` to `now + 24h` in UTC.
   - Emit compact context fields such as:
     - `local_timezone`
     - `generated_at_local`
     - `local_date`
     - `calendar_window_local: {start, end, label}`
   - For script-only alerts, print friendly labels such as `Sat, Jun 13 at 5:30 PM PDT`, not raw `2026-06-13T17:30:00-07:00` or UTC.

2. **Cron prompt**
   - Add a hard formatting rule: use the user's local timezone; do not display UTC unless explicitly comparing source timestamps.
   - Require friendly Telegram-readable time labels: `5:30 PM PDT`, `Tonight 5:30–7:30 PM PDT`, `Tomorrow morning`.
   - Forbid raw JSON, raw ISO timestamps, and tables unless the user explicitly asks.

3. **Verification**
   - Syntax-check modified scripts with `python -m py_compile`.
   - Run the script directly and inspect the compact output for local timezone fields and friendly local event times.
   - Re-list the cron job after updating to verify the existing job was patched rather than duplicated.

## Example snippet

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('America/Los_Angeles')
now = datetime.now(timezone.utc)
local_now = now.astimezone(LOCAL_TZ)
local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
local_end = local_start + timedelta(days=1)

context = {
    'generated_at': now.isoformat(),
    'generated_at_local': local_now.strftime('%A, %B %-d, %Y at %-I:%M %p %Z'),
    'local_timezone': 'America/Los_Angeles',
    'calendar_window_local': {
        'start': local_start.isoformat(),
        'end': local_end.isoformat(),
        'label': f"Today ({local_now.strftime('%A, %B %-d')}) in Pacific time",
    },
}
```

## Pitfall

Do not only change the final LLM prompt if the precheck script still gathers the wrong window or emits raw UTC. The next run may continue to include confusing source context. Fix the precheck and the prompt together.