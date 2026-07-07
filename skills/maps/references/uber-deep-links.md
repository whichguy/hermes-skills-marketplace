# Uber Deep Link Generation with Address Resolution

## When to use

When the user has a landing/arrival flight and needs a clickable Uber deep link
from the airport to their destination. The destination may be a logical name
("Magnus's house", "the office") that can't be blindly geocoded.

## The problem

Blind geocoding of logical names like "Magnus's house" returns wrong results
(e.g., a random house in France for "Magnus's house"). The user explicitly
called this out: "sometimes I'll have a logical destination and we might need
to do an address resolution to figure out where to book Uber."

## 3-layer resolution

The script `scripts/uber_deep_link.py` (at `$HERMES_HOME/scripts/uber_deep_link.py`)
resolves destinations in this order:

| Layer | Source | Example | When it fires |
|---|---|---|---|
| 1 | `known_places.json` | "Magnus's house" → `12660 Adair Creek Way NE, Redmond, WA 98052` | Personal address book with aliases — friend's houses, offices, regular spots |
| 2 | Nominatim geocoding | "Lumen Field, Seattle" → `800 Occidental Ave S, Seattle, WA 98134` | Named public places/venues/landmarks |
| 3 | `--addr` flag | Explicit street address | Direct override, no lookup needed |

## Usage

```bash
# Known place (resolves via known_places.json)
python3 ${HERMES_HOME}/scripts/uber_deep_link.py --to "Magnus's house"

# Public venue (resolves via Nominatim)
python3 ${HERMES_HOME}/scripts/uber_deep_link.py --to "Lumen Field, Seattle"

# Explicit address override
python3 ${HERMES_HOME}/scripts/uber_deep_link.py --to "Magnus" --addr "12660 Adair Creek Way NE, Redmond, WA"

# JSON output for programmatic use
python3 ${HERMES_HOME}/scripts/uber_deep_link.py --to "Magnus's house" --json
```

Output: a clickable `https://m.uber.com/looking?...` deep link with the
destination pre-filled. Pickup defaults to current location (the airport).

## known_places.json format

`$HERMES_HOME/scripts/known_places.json` — a personal address book mapping
logical names to street addresses:

```json
{
  "places": {
    "magnus house": {
      "aliases": ["magnus", "magnus's house", "magnus nystrom"],
      "address": "12660 Adair Creek Way NE, Redmond, WA 98052",
      "label": "Magnus Nystrom's House, Redmond"
    }
  }
}
```

Keys are matched case-insensitively. Aliases provide fuzzy matching. The
`label` field is used in the output for human-readable display.

To add a new place: edit `known_places.json` and add an entry with aliases.
The script picks it up automatically — no code changes needed.

## Pitfalls

- **Never blind-geocode logical names.** Always check `known_places.json` first.
  Blind geocoding "Magnus's house" returned a random house in France.
- **Google Contacts API doesn't return addresses.** The `google_api.py contacts list`
  command only returns name/emails/phones — no address fields. Don't try to
  resolve personal contacts' addresses from Google Contacts.
- **Nominatim is for public places.** It works for "Lumen Field" or "Embassy
  Suites Seattle" but not for personal addresses described by relationship
  ("my friend's house").
- **The Uber deep link uses `m.uber.com/looking`** with a `drop[0]` JSON
  parameter. This pre-fills the destination and uses current location as
  pickup — ideal for landing flights.

## Integration with calendar alerts

When generating calendar travel alerts for landing flights, include an Uber
deep link. The memory rule (in USER.md) says:

> Any time Jim has a landing/arrival flight, include a reminder to book an
> Uber from the airport to his destination with a clickable Uber deep link.
> Resolution order: (1) known_places.json, (2) maps_client.py search,
> (3) --addr flag. Use uber_deep_link.py --to "<destination>".

Link text should identify both origin airport and destination:
`🚗 Book Uber: SEA → Magnus's House, Redmond`
