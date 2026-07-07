# ESPN API Pattern for Sports Cron Prechecks

Used by the World Cup daily update cron (`world_cup_daily_update.py`). The ESPN
API is JSON, reliable, and doesn't require web_extract summarization — ideal for
automated cron prechecks.

## Endpoints

| Data | URL |
|------|-----|
| Schedule + scores | `https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates=YYYYMMDD` |
| Standings | `https://site.web.api.espn.com/apis/v2/sports/soccer/{league}/standings` |
| Bracket | `https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/bracket/season/{year}` (404s for some leagues) |

League slugs: `fifa.world`, `eng.1` (Premier League), `uefa.champions`, etc.

## Key fields

### Scoreboard events
- `event.date` — ISO timestamp (UTC, with `Z` suffix)
- `event.name` — e.g. "Egypt at Australia"
- `event.status.type.state` — `"pre"`, `"in"`, `"post"`, `"final"`
- `event.status.type.shortDetail` — `"Scheduled"`, `"HT"`, `"FT"`, `"45'"`, etc.
- `event.competitions[0].altGameNote` — round info: `"FIFA World Cup, Round of 32"`, `"FIFA World Cup, Round of 16"`, `"FIFA World Cup, Quarterfinals"`
- `event.competitions[0].competitors[].homeAway` — `"home"` or `"away"`
- `event.competitions[0].competitors[].team.shortDisplayName` — team name
- `event.competitions[0].competitors[].score` — score string (only when `state` is `"in"`/`"post"`/`"final"`)
- `event.competitions[0].venue.address.city` — venue city

### Standings
- `children[]` — array of groups
- `children[].name` — group name (e.g. "Group A")
- `children[].standings.entries[]` — team entries
- `entries[].team.shortDisplayName` — team name
- `entries[].stats[]` — array of `{name, displayValue}` for: `gamesPlayed`, `wins`, `ties`, `losses`, `points`, `pointDifferential`, `rank`

## Timezone handling

ESPN returns UTC timestamps. Convert to the user's local timezone:
```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

local = parse_dt(event["date"]).astimezone(ZoneInfo("America/Los_Angeles"))
```

## Date range for scoreboard

ESPN's scoreboard endpoint accepts `dates=YYYYMMDD`. To catch all games for a
local day, query multiple UTC date keys (the local day may span two UTC dates):
```python
local_start = local_day.replace(hour=0, minute=0, second=0, microsecond=0)
date_keys = sorted({
    (local_start + timedelta(days=offset)).astimezone(timezone.utc).strftime("%Y%m%d")
    for offset in (-1, 0, 1, 2)
} | {
    (local_start + timedelta(days=offset)).strftime("%Y%m%d")
    for offset in (-1, 0, 1, 2)
})
```

## Bracket path tracing for knockout rounds

For "ladder conditions" (what's at stake per game), the precheck gathers:
1. Today's games with `altGameNote` (round info)
2. The next 7 days of scheduled games (to find the next-round opponent)
3. Group standings (for group-stage scenarios)

The LLM then traces: "if Team A wins R32 → they advance to R16 vs winner of X vs Y (Jul 4)".

TBD opponents appear as `"Round of 32 16 Winner"` in the team name — the LLM
should explain which game's winner fills that slot.

## User-Agent requirement

ESPN's API requires a User-Agent header:
```python
UA = "Mozilla/5.0 (Hermes daily World Cup update)"
req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
```

## Pitfalls

- **Bracket endpoint 404s**: `https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/bracket/season/2026` returns 404. Use the web bracket page as fallback: `https://www.espn.com/soccer/bracket/_/season/2026/league/fifa.world`
- **TBD team names**: In knockout rounds before the previous round completes, team names are `"Round of 32 16 Winner"` — handle these gracefully in the LLM prompt
- **Date key ambiguity**: A local day like "Jul 3 PDT" spans `20260703` and `20260704` in UTC. Query both.
- **Dedup**: The same event may appear in multiple date queries. Deduplicate by `event.id` or `event.uid`.
