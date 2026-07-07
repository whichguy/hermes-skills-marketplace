# End-of-Day Forecast Pattern

## Problem

An end-of-day cron was a **backward-looking recap** ("here's what happened today"). At end of day, the user already knows what happened — they want to know what's coming tomorrow.

## Solution: Recap → Forecast conversion

Convert the cron from backward recap to **forward-looking forecast** with travel/logistics gap analysis and dynamic local context (weather, news, road impacts).

### Precheck script changes

1. **Shift calendar window from today to tomorrow.** Pull `timeMin = tomorrow_start`, `timeMax = tomorrow_end` instead of today's window.
2. **Add travel-keyword detection.** Scan event summaries/locations for: `flight`, `hotel`, `rental`, `checkout`, `airport`, `departure`, `arrival`, `boarding`, `terminal`, `gate`, `Uber`, `Lyft`, `taxi`, `shuttle`, `train`, `bus`, `cruise`, `ferry`.
3. **Emit `travel_events` list** — events flagged as travel-related, with their start/end times and locations.
4. **Emit `tonight_calendar`** — remaining events for the current day (still ahead of the user).
5. **Change `precheck_type`** from `eod_wrap_seed` to `eod_forecast_seed` so the prompt can branch on it.
6. **Emit `tomorrow_label`** — human-readable date string for the forecast header.
7. **Add dynamic local context** — weather, local news, and road/holiday impact data (see below).

### Dynamic Local Context (weather, news, road impacts)

Three keyless, curl-based data sources added to the precheck payload under `local_context`:

#### Weather (`wttr.in`)

```
WEATHER_URL = 'https://wttr.in/{loc}?format=j1'
```

Returns structured JSON with `maxtempF`, `mintempF`, `hourly[].chanceofRain` (take max across all hours), `astronomy[].sunrise`/`sunset`, `moon_phase`, `current_condition[].temp_F`/`weatherDesc`. No API key needed. Use `urllib.parse.quote(location)` for the URL — spaces in city names must be encoded.

**Pitfall:** wttr.in returns `mintempF`/`maxtempF` as strings, not ints. Convert with `int()` before comparison. The `chanceofrain` field is per-hour — take the max across all 8 three-hour blocks for the day's rain chance.

#### Local News (Google News RSS)

```
NEWS_URL = 'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
```

Parse with `re.findall(r'<item>.*?</item>', xml, re.DOTALL)`, extract `<title>` and `<link>` from each. Return top 5 headlines.

**Critical pitfall — URL encoding:** City names with spaces (e.g. "San Ramon") must be URL-encoded in the query. `f'{city}+CA'` where `city = "San Ramon"` produces `San Ramon+CA` — the space breaks the query. Fix: `city_url = city.replace(' ', '+')` then `f'{city_url}+CA'` → `San+Ramon+CA`.

**Pitfall — `when:Nd` filter kills results:** Google News RSS `when:3d` appended to the query string returns 0 items even when news exists. Omit time filters entirely; let the LLM judge recency from the headlines.

#### Road & Holiday Impacts (Google News RSS)

```
ROAD_URL = 'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
```

Two queries combined with dedup by title:
1. `{city_url}+CA+traffic+road+closure` — local road impacts
2. `Bay+Area+traffic+holiday+road+closure+July` — regional holiday traffic

Return up to 4 items. Same URL-encoding pitfall as local news applies.

#### Dynamic Location Detection

If `travel_events` are detected, extract the destination city from event locations and use that for weather/news queries instead of the home location. Falls back to home base (`San Ramon, CA`) when no travel is detected. The `local_context` payload includes both `active_location` and `travel_location_detected` (null when at home).

### Prompt structure

The new prompt produces:

1. **🌅 Tomorrow's Forecast** — chronological timeline of all events
2. **🌤️ Weather** — one-liner: condition, high/low, rain %, sunrise/sunset. Skip if weather has an error field.
3. **📰 Local News** — top 2-3 relevant headlines, hyperlinked. Skip noise (real estate listings, generic sports scores).
4. **🚧 Road & Holiday Impacts** — closures/traffic affecting the user's routes. Hyperlinked.
5. **✈️ Travel & Logistics Gaps** — suggests specific calendar items to add:
   - Hotel checkout time (if hotel stay ends tomorrow)
   - Airport departure buffer (~2h before flight for domestic)
   - Ride-share timing (Uber/Lyft to airport, ~30 min from downtown)
   - Arrival pickup at destination if needed
6. **🌙 Tonight (still ahead)** — remaining events for the current day
7. **📬 Still Pending** — unread mail + unsent drafts

### Key design decisions

- **All times in user's current timezone.** The precheck checks memory for travel location and adjusts TZ accordingly.
- **Gap suggestions are suggestions, not calendar writes.** The LLM identifies gaps but does not create calendar events — the user decides.
- **Travel detection is keyword-based, not calendar-type-based.** Flight events may be labeled differently across calendar providers; keyword matching on summary/location is more reliable.
- **The precheck still gates on content.** If tomorrow is empty and tonight is empty, `wakeAgent: false` — the LLM never fires.
- **Weather/news/road data is fetched unconditionally** when the precheck fires — the LLM decides which sections to include based on relevance.
- **All three data sources are keyless** — no API keys, no auth, pure curl. This keeps the precheck portable and zero-config beyond the location string.

### Verification

Dry-run the precheck with `python3 eod_wrap_precheck.py --dry-run` and verify:
- `tomorrow_label` is tomorrow, not today
- `precheck_type` is `eod_forecast_seed`
- `travel_events` contains flight/hotel events
- `tomorrow_calendar` has events
- `wakeAgent` is `true` when content exists
- `local_context.weather` has `max_temp_f`, `min_temp_f`, `condition`, `max_rain_chance`
- `local_context.local_news` has 3-5 headlines with `title` and `link`
- `local_context.road_impacts` has 2-4 items with `title` and `link`

### Pitfalls

- **Don't forget the prompt update.** Changing the precheck without updating the prompt means the LLM still writes a backward recap from forward-looking data — confusing output.
- **Travel detection false positives.** "Hotel conference room" or "flight of stairs" could match. Keep the keyword list specific to actual travel modes.
- **Timezone handling.** If the user is traveling, the precheck must use the destination timezone, not the home timezone. Check memory for current location.
- **Google News RSS URL encoding.** Spaces in city names break the query silently (0 results). Always `city.replace(' ', '+')` before building the URL.
- **`when:Nd` time filter kills Google News RSS.** The `when:3d` suffix returns 0 items. Omit it; let the LLM filter recency.
- **wttr.in returns string temps.** `mintempF`/`maxtempF` are strings — convert with `int()` before formatting or comparison.
- **Cron prompt is frozen at creation time.** After updating the precheck script, you MUST also update the cron job's prompt via `cronjob action=update` — the scheduler does not re-read shared prompt files at runtime.
- **Add `web` toolset to the cron job** if the LLM needs to resolve news links or fetch additional context. The default `terminal, skills, file` may not be enough.
