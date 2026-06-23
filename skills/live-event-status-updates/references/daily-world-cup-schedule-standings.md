# Daily World Cup Schedule + Standings Cron Pattern

## When to use

Use this when the user asks for recurring World Cup / tournament updates focused on **schedule and standings**, not long analysis.

The best shape is a deterministic `no_agent: true` cron script because the data is structured and the user wants consistent Telegram formatting.

## Data sources

ESPN public endpoints worked for FIFA World Cup-style updates:

- Scoreboard: `https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard`
- Date-scoped scoreboard: append `?dates=YYYYMMDD`
- Standings: `https://site.web.api.espn.com/apis/v2/sports/soccer/fifa.world/standings`

For date-scoped schedules, ESPN buckets can cross local-day boundaries. Fetch a small window around the user's local day and filter events by parsed event datetime in the user's timezone.

## Output shape

Telegram-readable script output:

```markdown
## ⚽ World Cup daily update
As of: Saturday, Jun 13 at 7:00 AM PDT
Source: ESPN public scoreboard/standings

## Today's schedule
• 12:00 PM PDT: Switzerland vs Qatar · Santa Clara, California
• 3:00 PM PDT: Morocco vs Brazil · East Rutherford, New Jersey

## Yesterday's results
• Final: Paraguay 1 — 4 USA

## Group leaders
• Group A: Mexico 3 pts, GD +2, GP 1; South Korea 3 pts, GD +1, GP 1

## Bottom line
Today's match list is ready; standings above show the current top two in each group.
```

## Implementation notes

- Use `zoneinfo.ZoneInfo('America/Los_Angeles')` for Jim unless he requests another timezone.
- Avoid raw UTC/ISO timestamps in user-facing output.
- Use `no_agent: true`; stdout is the final Telegram message.
- Keep external calls read-only; no account credentials needed.
- Include a source line so the user knows where live data came from.
- For standings, display top two per group by ESPN `rank`, with points, goal differential, and games played.
- If no events are scheduled, say so plainly and still include standings if available.
- If the API fails, print a concise error alert and exit 0 so the cron job reports the source problem without stack traces.

## Cron shape

```text
name: Daily World Cup schedule and standings
schedule: 0 14 * * *   # 7 AM Pacific during PDT
script: world_cup_daily_update.py
no_agent: true
deliver: origin
enabled_toolsets: [terminal]
```

If the user later asks for goal/red-card/final-result pings, create a separate deduped alert job rather than bloating the daily digest.
