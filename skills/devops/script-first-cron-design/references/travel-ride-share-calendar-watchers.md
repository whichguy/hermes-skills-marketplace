# Travel, ride-share, and calendar-reminder watchers

Use this reference when updating deterministic calendar/travel cron jobs for Jim.

## Trigger class

Flag events early enough for planning when they look like:

- Flights, airports, hotels, boarding, reservations, travel, trips.
- Business/work/client travel: business, conference, client, Salesforce, meeting, work trip, Fortified Strength/nonprofit work.
- Events/trips that may include alcohol: wine, winery, cellar/cellars, bar, brewery, beer, cocktail, distillery, tasting, BBQ, dinner.

## User-facing behavior

When triggered, the watcher should deliver a concise Telegram alert that asks Jim to check:

- whether Uber / ride-share is needed;
- whether travel-time calendar reminders/events exist **to and from** the destination.

Keep it read-only. Do not create calendar events/reminders, book rides, send messages, or mutate Google Workspace without Jim approving the exact change.

## Script pattern

- Expand the lookahead beyond “starting soon” for planning classes; 48–72 hours is a useful default.
- Use deterministic keyword classification in the script; do not rely on an LLM for no-agent alerts.
- Deduplicate by event ID + start time + category (`ride`, `travel`, `soon`) so adding a new category can trigger once without spamming every tick.
- Keep output minimal: event title, friendly local time, location when present, reason for the Uber/travel-time check, and read-only reminder.

## Pitfalls

- Do not treat routine workouts or ordinary local events as ride-share prompts unless alcohol/travel/business-trip indicators are present.
- Do not imply Hermes can verify an Uber booking unless a real booking source was inspected.
- Do not create travel-time calendar blocks automatically; ask first with the proposed to/from times and account alias.
