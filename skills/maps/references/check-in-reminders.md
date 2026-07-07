# Check-In Reminders for Flights & Hotels

> **Primary skill:** The `check-in-automation` skill (`skills/productivity/check-in-automation/SKILL.md`)
> is the authoritative source for check-in automation. This reference covers the
> calendar event pattern and link registry — for API reverse-engineering, the
> 5-layer discovery process, and automated check-in scripts, load that skill.

When the user has a flight or hotel reservation, create a calendar event 24 hours
before departure/check-in with a direct hyperlink to the check-in page, plus the
confirmation code and all relevant details in the event description.

## Link Registry

`${HERMES_HOME}/scripts/checkin_links.json` — covers 8 airlines and 5 hotel chains with
web check-in URLs, app store links, and whether URL pre-fill is supported.

### Airlines covered
Alaska, Southwest, United, Delta, American, Hawaiian, JetBlue, British Airways

### Hotels covered
Hilton (incl. Embassy Suites), Marriott, Hyatt, IHG

## Calendar Event Pattern

For each flight, create one event 24h before departure:

```
Summary: ✈️ Check in: [Airline] [Flight #] ([Origin]→[Dest])
Start: 24h before departure, 15-min duration
Reminders: popup at start + 10-15 min after

Description:
**Time to check in for your flight!**

✈️ [Airline] [Flight #] · [Origin] → [Dest]
📅 Departs: [Day Date, Time] [TZ]
🪑 Seat [Seat]
👤 Name: [Last Name]
🔑 Confirmation: [Code]

🔗 **Check in here:** [checkin_url from registry]

Enter last name: **[Last Name]**
Enter confirmation code: **[Code]**

📱 Or use the [Airline] app: [app_store_link]
📋 [View original booking email](https://mail.google.com/mail/u/0/#inbox/<thread_id>)

⚠️ Online check-in opens 24h before departure. Get your boarding pass now!
```

For hotels, create one event 24h before check-in time with the hotel chain's
loyalty app link (digital check-in is app-based for most chains).

## URL Pre-Fill Reality

Most airline check-in pages are JS/React apps that do NOT accept URL query params
for pre-filling confirmation codes or names. Tested with Alaska Airlines
(reservations.alaskaair.com/checkin) — the form is a custom component, URL params
populate hidden fields but not visible inputs.

**Therefore**: always include the confirmation code and last name prominently in
the event description for copy-paste. The `url_params` field in the registry is
`false` for all airlines currently; if any airline adds URL pre-fill support,
flip that field to `true` and add the `params_format`.

## Browser-Based Form Investigation

When adding a new airline/hotel to the registry, test whether their check-in page
accepts URL pre-fill:

1. Navigate to the check-in URL with test params:
   `browser_navigate(url="https://airline.com/checkin?conf=TEST&name=TEST")`
2. Wait for JS to render: `browser_console(expression="...")` to check DOM
3. Take a screenshot: `browser_vision(question="Are fields pre-filled?")`
4. If not pre-filled, set `url_params: false` and note in `notes`

## Integration with Location Resolution

If the flight/hotel destination is a logical name ("Magnus's house"), resolve it
using the same chain as Uber deep links: known_places.json → email/calendar
history → Nominatim → ask Jim. The resolved address goes in the calendar event
description for context.
