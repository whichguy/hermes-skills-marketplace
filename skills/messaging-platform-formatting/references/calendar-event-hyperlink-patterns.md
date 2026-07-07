# Calendar Event Hyperlink Patterns

## Google Calendar HTML Support

Google Calendar event descriptions support basic HTML tags:
- `<a href="...">link text</a>` — hyperlinks
- `<b>bold</b>` — bold text
- `<i>italic</i>` — italic text
- `<br>` — line breaks

## Gmail Booking Email Link (Mandatory on All Trip Events)

Every calendar event related to a trip (flight, hotel, Uber, check-in reminder, drive to airport) must include a link to the original booking confirmation email in Gmail.

**Format:**
```html
<a href="https://mail.google.com/mail/u/0/#inbox/<thread_id>">📋 View original booking email</a>
```

**How to find the thread ID:**
1. Search Gmail for the confirmation code (e.g., `EPPAYQ`)
2. The thread ID is in the message URL or can be extracted from the Gmail API response
3. Format: `https://mail.google.com/mail/u/0/#inbox/<thread_id>`

**Application rule:** Add this link to EVERY event in the trip chain, not just the flight itself. Jim should be able to tap any event in the trip and get back to the original booking.

## Maps Address Link

```html
<a href="https://maps.google.com/?q=<URL-encoded address>">📍 <street address></a>
```

## Check-In Page Link

```html
<a href="<check-in URL from checkin_links.json>">✈️ <Airline Name> Check-In</a>
```

## Full Trip Chain Example

For a flight SEA → SJC with hotel, the following events all get the Gmail booking link:
- ✈️ Flight AS481 SEA → SJC
- 🚗 Uber: SEA → Hotel
- 🏨 Hotel check-in
- ⏰ Check-in reminder (24h before)
- 🚗 Uber: Hotel → SEA (return)

## Pitfalls

- **Raw URLs in calendar descriptions** — Jim explicitly said "I never really want to see URLs. I just want to see hyperlink texts." Always use `<a href>` HTML tags.
- **Missing events in the chain** — if you add the link to the flight but not the hotel or Uber events, Jim can't reference the booking from those events. Apply to ALL related events.
- **Wrong thread ID** — always verify by searching Gmail for the exact confirmation code. Don't guess or use a similar-looking thread.
