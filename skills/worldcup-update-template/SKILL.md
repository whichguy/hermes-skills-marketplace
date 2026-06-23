---
name: worldcup-update-template
description: 'Jim''s preferred Telegram format for World Cup match-day updates: blockquote
  header-card layout (B3-b) with per-match duration lines. Times in Pacific when Jim
  is home, Mountain Time (MT) when traveling. Short labels like ''9:30 PM'' with no
  tz suffix per line, note timezone once at top only. DirecTV San Ramon (94582) channel
  numbers.'
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - telegram
    - formatting
    - worldcup
    - soccer
    - football
    - sports
    - template
    - directv
    config:
    - key: worldcup-update-template.enabled
      description: Enable worldcup-update-template skill behavior
      default: true
      prompt: Enable worldcup-update-template skill?
    category: productivity
platforms:
- linux
- macos
- windows
---
---

# World Cup Update Template (Jim)

Use this when Jim asks for World Cup / FIFA match schedules, scores, or live status. He has locked in a specific Telegram layout, timezone, and TV-provider channel set.

## Hard rules

- **Always hyperlink everything** — every business name, address (→ Google Maps), phone (→ `tel:`), website, and broadcaster. Event kickoff times → Google Calendar add-event link pre-populated with title, date, time, location. Raw URLs are never acceptable; always use named hyperlinks.
- **Timezone: always Jim's current local time.** When Jim is home (San Ramon CA), use Pacific Time (PT). When traveling (e.g. Colorado Springs for USAW NCW), use Mountain Time (MT). Short labels like `9:30 PM` — no tz suffix on every line; state the timezone once at the top only. Source feeds (e.g. ESPN) usually list Eastern Time — subtract 2h for MT, 3h for PT. Always state the conversion was applied.
- **Layout: blockquote "header-card" style** — one blockquote group per match, generous spacing (never cram matches into one sentence/line).
- **Each upcoming match gets BOTH a clock time AND an approximate countdown duration** (e.g. `⏰ 2:00 PM PT · ⏳ in ~6.5h`). Compute the countdown from the CURRENT Pacific time — ask or infer it; do not reuse a stale delta.
- Flag that ⏳ countdowns are approximate (depend on exact current moment); offer to refresh.
- **Include DirecTV channel numbers** for each match's broadcaster (Jim has DirecTV satellite in San Ramon, CA 94582 — SF/Oakland/San Jose DMA).

## Status sections / emoji

- ✅ **FINAL** — completed matches
- 🔴 **LIVE · ~NN'** — in-progress, include minute mark
- Upcoming — lead with country flag + bold matchup, then time/duration/channel line

## Template shape

```
> **🏆 WORLD CUP**
> 🗓 <Weekday, Month D> · 🌎 Los Angeles (PT)
> 📡 DirecTV · San Ramon, CA 94582

> ✅ **FINAL**
> 🇭🇹 Haiti **0–1** Scotland 🏴...

> 🔴 **LIVE · ~30'**
> 🇦🇺 Australia **1–0** Turkey 🇹🇷
> 📡 FS1 — **Ch. 219**

> 🇩🇪 **Germany v Curaçao** 🇨🇼
> ⏰ 2:00 PM PT · ⏳ in ~6.5h
> 📡 FOX KTVU — **Ch. 2**
```

Separate each `>` blockquote group with a blank line so Telegram renders distinct cards.

**Google Calendar add-event link pattern for kickoff times:**
```
https://calendar.google.com/calendar/r/eventedit?text=TITLE&dates=YYYYMMDDTHHMMSS/YYYYMMDDTHHMMSS&location=VENUE&details=DETAILS
```
- Use local time in the dates param (no Z suffix); include broadcaster + channel in details
- Example: `[📅 Add to Calendar](https://calendar.google.com/calendar/r/eventedit?text=Spain+vs+Saudi+Arabia&dates=20260621T140000/20260621T160000&location=Mercedes-Benz+Stadium+Atlanta&details=FOX+Ch.2+%7C+DirecTV+Ch.2)`

## DirecTV channel reference — San Ramon 94582 (SF/Oakland/San Jose DMA)

| Network | DirecTV Ch. | Notes |
|---------|-------------|-------|
| FS1 (national) | **219** | Stable nationwide |
| FOX — KTVU | **2** | Bay Area local affiliate |
| Telemundo — KSTS | **48** | Bay Area local affiliate |
| FOX Deportes | **464** | National Spanish |
| Universo | **410** | National Spanish |
| FS2 | **618** | National |

- Locals (FOX, Telemundo) map to their OTA virtual channel number and are stable market-wide.
- **Peacock is NOT a DirecTV channel** — it's NBC's streaming app; list it as `📱 Peacock (stream)` only if relevant, not as a channel number.
- Anchors if anything looks off: FS1 = 219, FOX = 2.

## Closing

- Optionally add a short "Conversions applied (ET → PT)" recap list.
- Offer to refresh live scores/countdowns or set kickoff reminders (cron requires Jim's approval before creating).

## Data sourcing

- **Step 1 — schedule page** (most reliable for today's games + times):
  `https://www.espn.com/soccer/schedule/_/league/fifa.world` via web_extract
- **Step 2 — scoreboard page** (for live/final scores):
  `https://www.espn.com/soccer/scoreboard/_/league/fifa.world` via web_extract
  ⚠️ The scoreboard page may lag — cross-check completed scores with a targeted web_search like `"Ecuador vs Curaçao score June 21 2026"` for early-morning games that finished before you check.
- **Step 3 — targeted search for completed games** played more than a few hours ago that don't appear in the scoreboard summary. ESPN scoreboard is truncated by LLM summarization at ~5000 chars; specific match searches fill the gaps.
- web_search may be down (EXA_API_KEY unset) — go straight to web_extract first.
- FIFA's own page is cookie-wall noise. Yahoo Sports `sports.yahoo.com/soccer/article/2026-world-cup-results...` is a reliable backup for standings + full schedule.
- DirecTV's lineup tool (`directv.com/channel-lineup`) is JS-gated and frequently throws HTTP2 errors; TitanTV/antennaweb also unreliable. Rely on the table above unless Jim reports a mismatch.

## Yelp blocking — pitfall & workaround

**Yelp blocks both browser and web_extract reliably** — do not waste turns on either:
- `browser_navigate` to yelp.com → DataDome CAPTCHA wall, no content returned.
- `web_extract` of yelp.com URLs → `"error": "Failed to fetch url"`.

**Workaround:** Use `web_search` with `site:yelp.com <query>` — search engine snippets surface Yelp's top-10 list titles, star ratings, review counts, addresses, and hours even though the page itself is blocked. Combine with direct `web_extract` of each business's own website for full detail. This pattern was confirmed working in June 2026.
