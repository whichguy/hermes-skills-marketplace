# Google Calendar Add-Event Deep-Link Template

Use this to hyperlink any event time/date so Jim can tap to add it to Google Calendar.

## URL format

```
https://calendar.google.com/calendar/r/eventedit?text=EVENT+TITLE&dates=START/END&location=ADDRESS&details=NOTES
```

## Parameter encoding

| Parameter | Format | Example |
|-----------|--------|---------|
| `text` | URL-encoded string | `Steam+Sauna+%E2%80%94+VASA+Fitness` |
| `dates` | `YYYYMMDDTHHmmss/YYYYMMDDTHHmmss` (local time, no Z) | `20260622T060000/20260622T070000` |
| `location` | URL-encoded address | `7655+N+Union+Blvd+Colorado+Springs+CO+80920` |
| `details` | URL-encoded notes | `Drop-in+day+pass+%2415.` |

## Notes
- Do NOT append `Z` to dates — let Google Calendar infer timezone from location
- All spaces → `+`, special chars → `%XX` percent-encoding
- Keep `text` concise — it becomes the calendar event title
- Jim's timezone: **MT** while in Colorado Springs (Jun 20–28 2026), **PT** at home in San Ramon

## Example — VASA Fitness steam sauna morning visit

```
https://calendar.google.com/calendar/r/eventedit?text=Steam+Sauna+%E2%80%94+VASA+Fitness&dates=20260622T060000/20260622T070000&location=7655+N+Union+Blvd+Colorado+Springs+CO+80920&details=Drop-in+day+pass+%2415.+Steam+room%2C+dry+sauna%2C+cold+plunge.+Opens+4+AM.
```

Renders as: `[Add to Calendar: Steam Sauna at VASA](url)`

## When to include

- Any specific event time or date mentioned in a response (match kickoffs, appointments, sessions, TO assignments)
- World Cup matches, USAW sessions, travel departures, spa bookings, reminders
- Even casual "opens at 4 AM" references warrant a calendar link if the user might want to plan around it
