# ESPN Scoreboard API Recipe

## Purpose

Use this reference when a user asks for live soccer/World Cup-style updates and a public ESPN scoreboard endpoint is sufficient.

This is a session-derived pattern from a live 2026 World Cup match update loop where the user repeatedly asked: “update,” “new status?”, “any updates?”, and “where are we at?” The winning format was concise current score + new events only.

## Endpoint Pattern

For FIFA World Cup soccer:

```text
https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard
```

General ESPN pattern:

```text
https://site.api.espn.com/apis/site/v2/sports/<sport>/<league>/scoreboard
```

Examples may vary by ESPN league slug. Inspect returned `leagues`, `events`, and `competitions` fields rather than assuming shape.

## Useful Fields

Top-level event:

- `events[].id`
- `events[].name`
- `events[].date`
- `events[].status.type.description`
- `events[].status.type.detail`
- `events[].status.type.shortDetail`
- `events[].status.type.state`
- `events[].status.type.completed`

Competition:

- `events[].competitions[0].competitors[]`
- `competitors[].homeAway`
- `competitors[].team.displayName`
- `competitors[].team.id`
- `competitors[].score`
- `competitors[].winner`
- `competitions[0].venue.fullName`
- `competitions[0].venue.address.city/country`
- `competitions[0].details[]`

Event details:

- `details[].clock.displayValue` — match minute, e.g. `67'`, `90'+2'`
- `details[].type.text` — Goal, Yellow Card, Red Card, Goal - Header, etc.
- `details[].team.id` — map back to `competitors[].team.id`
- `details[].athletesInvolved[].displayName`
- `details[].scoreValue`

## Minimal Python Probe

```python
import urllib.request, json, datetime

url = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
data = json.load(urllib.request.urlopen(req, timeout=20))
print('as_of_utc', datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))

for event in data.get('events', []):
    comp = event['competitions'][0]
    status = event.get('status', {}).get('type', {})
    print(event.get('name'))
    print(status.get('description'), status.get('detail'), 'completed=', status.get('completed'))
    for c in comp['competitors']:
        print(c.get('homeAway'), c['team'].get('displayName'), c.get('score'), 'winner=', c.get('winner'))
    for d in comp.get('details', []):
        team_id = str(d.get('team', {}).get('id'))
        team = next((c['team'].get('displayName') for c in comp['competitors'] if str(c['team'].get('id')) == team_id), '?')
        names = ', '.join(a.get('displayName', '') for a in d.get('athletesInvolved', []))
        print(d.get('clock', {}).get('displayValue'), d.get('type', {}).get('text'), team, names)
```

## Answering Pattern

For repeated user follow-ups, answer like:

```markdown
## 🔴 Current status

As of: <UTC timestamp>
Match time: <minute/status>

## Score

<Team A> <score> — <score> <Team B>

## New since last check

- <new event, if any>

## Where we’re at

- <short implication>
- <short implication>
```

If no new major event:

```markdown
No new goal/red card since the last check. It is still...
```

## Pitfalls

- ESPN may include betting `odds`; omit by default.
- Do not infer final result unless `completed`/final status says so.
- API event names may use American “away at home” order; display the actual scoreboard clearly.
- For live threads, the user’s short follow-ups mean “refresh status,” not “give another full background summary.”
