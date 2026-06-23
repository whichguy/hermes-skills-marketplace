# Fixed-Schedule Event Alert Engine

Pattern for recurring, time-based pings driven by a known list of events
(a competition schedule, a release calendar, a set of appointment times).
Examples: "alert me 10 min before each weigh-in and right at each lift time"
across a multi-day meet.

## Shape: one every-minute no-agent job, not N jobs

Do **not** create one cron job per event slot (that produced ~20–40 jobs in
one session and is unmaintainable). Instead:

- Hardcode the schedule as a list of tuples in a single script, e.g.
  `(date "YYYY-MM-DD", trigger HH:MM, payload HH:MM, [names])`.
- Schedule **one** job at `* * * * *` (every minute) with `no_agent: true`.
- The script computes "now" in the event's timezone, builds a `YYYY-MM-DD HH:MM`
  key, and prints a line only when the current minute matches a trigger.
- Silent otherwise (empty stdout → no delivery), so the every-minute cadence
  costs nothing and spams nothing.

Updating the schedule = editing one list in one file. The running job picks up
the edited script automatically on the next tick; no re-scheduling needed.

## Timezone-aware minute matching

All comparisons happen in the *event's* local zone, never the scheduler's UTC:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
MT = ZoneInfo("America/Denver")
now = datetime.now(MT)
key = now.strftime("%Y-%m-%d %H:%M")
# "10 min before" trigger:
pre = (datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M") - timedelta(minutes=10))
if pre.strftime("%Y-%m-%d %H:%M") == key: emit(...)
```

`zoneinfo` handles DST automatically (MDT vs MST) — do not hardcode a UTC
offset. The host clock can be UTC; only the comparison zone matters.
Use `%-I:%M %p` to render friendly 12-hour times in the alert text.

## CRITICAL: cron script path must be a bare filename

`cronjob(action=create, script=...)` **rejects absolute and `~`-relative
paths**. The error is:

> Script path must be relative to ~/.hermes/scripts/. Got absolute or
> home-relative path: '/opt/data/.hermes/scripts/foo.py'

Write the script into `~/.hermes/scripts/` (resolve `$HOME` first — it may be
e.g. `/opt/data/home`, while the scripts dir is `/opt/data/.hermes/scripts/`),
then pass **just the filename**: `script="foo.py"`. The scheduler resolves it
under the scripts dir itself.

## Verify the source of truth BEFORE committing the schedule

When the schedule comes from a user-supplied artifact (a photo, a screenshot,
a "preliminary" spreadsheet tab), cross-check it against the authoritative
source before building alerts:

- Find the official event/schedule page; look for linked PDFs (start list,
  final session schedule). On dynamic pages, enumerate links via
  `browser_console` with a JS `querySelectorAll('a')` filter rather than
  scrolling the snapshot.
- If `web_extract` is unavailable (DDG search-only backend), `curl` the PDF
  and parse locally with `pypdf` in a `uv venv` (`uv pip install --python
  <venv>/bin/python pypdf`).
- Multi-column PDFs extract as jumbled text — good enough to confirm
  *presence* of every name and to spot-check section times, even if clean
  per-row mapping isn't possible.

This caught two real issues in one session: it confirmed the photo's corrected
times (superseding a preliminary spreadsheet) and surfaced a name typo
(`Eleanor Cier` → official `Eleanor Cler`) that was then fixed in the script.

## Enriching alerts with a stable resource link

When alerts should include a "watch/join here" link, prefer the site's clean
permanent path (e.g. `https://org.example/live`) over a deep per-session URL.
Verify it resolves (`curl -sIL ... -w '%{url_effective}'`) and embed it as a
module constant. Add the link only to the alert variant where it's actionable
(e.g. the "happening now" ping, not the "10 min before" pre-alert).

## Test matrix before scheduling

Monkeypatch `datetime.now` to a fixed zone-aware instant and assert:
- a "pre" trigger minute emits the pre-alert (and no link, if applicable),
- the exact event minute emits the event alert (with link, if applicable),
- a normal minute emits nothing (silent, exit 0).
