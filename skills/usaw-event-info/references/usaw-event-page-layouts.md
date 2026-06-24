# USAW Event Page DOM Layouts

Reference for maintaining `usaw_event_extractor.py`. Documents the DOM structures
observed across all 2025–2026 USAW national event pages.

## Layout Patterns

### 1. Chakra UI (NCW, VWS2, Finals)

The most complex layout. Uses Chakra UI component library.

**Structure:**
```
<main>
  <div class="content-tile-block css-8atqhb">      ← container per H2 section
    <div class="css-ieig3t">                        ← H2 wrapper
      <div class="css-1f7farq">
        <h2>Registration</h2>
        <span class="underline-block css-0"/>        ← permalink artifact
      </div>
    </div>
    <div class="css-xztgs2">                        ← UL wrapper (sibling of H2 wrapper)
      <ul class="chakra-list__root css-1thgglz">
        <li>
          <h3>National Championships Registration</h3>
          <a href="sport80.com/...">View</a>
        </li>
        ...
      </ul>
    </div>
  </div>
  <div class="content-tile-block css-8atqhb">        ← next H2 section
    ... (Information) ...
  </div>
</main>
```

**Key insight:** H2 and UL are NOT direct siblings. They're in sibling DIVs
inside a common `.content-tile-block` parent. The extractor walks up from H2
to find the common ancestor containing the UL.

**Link text pattern:** `"View, opens in a new tab"` → cleaned to `"View"`.
The H3 header is the real label for the section.

### 2. Inline/Paragraph (VWS1)

VWS1 uses a mix of Chakra UI sections AND inline paragraph links.

**Structure:**
```
<h2>Registration</h2>
<ul>
  <li><h3>Registration</h3><a href="sport80.com/...">View</a></li>
  <li><h3>Adaptive Athlete Registration</h3><a href="sport80.com/...">View</a></li>
</ul>
...
<p>Alternate Training Sites: <a href="urldefense.com/...">Clintonville Barbell</a></p>
<p><a href="urldefense.com/...">Project Lift</a></p>
```

**Key insight:** Training site links are in `<p>` tags with `urldefense.com`
wrapping (Proofpoint URL defense). The extractor must check for known gym
domains inside the urldefense URL string.

**urldefense.com URL pattern:**
```
https://urldefense.com/v3/__https://www.columbusweightlifting.org/pages/contact-__;!!EsN5QLU!...
```
The real domain is embedded after `__` in the URL path.

### 3. Minimal (WZA)

Fewest sections. No hotels, no schedules (all TBA), no media credentials.

**Structure:**
```
<h1>USAW x Gymreapers Wodapalooza SoCal</h1>
<p>Sep 25, 2026 - Sep 27, 2026 | Huntington Beach, CA, United States</p>
... (description paragraph) ...
<h2>Registration</h2>
<ul>
  <li><h3>Registration</h3><a href="sport80.com/...">View</a></li>
  <li><h3>Become a Member</h3><a href="/Join-USAWeightlifting">View</a></li>
</ul>
<h2>Information</h2>
<ul>
  <li><h3>Tickets</h3><a href="socal.wodapalooza.com/">View</a></li>
  <li><h3>Preliminary Schedule</h3> TBA </li>
  ...
</ul>
```

**Key insight:** TBA items have no link — just text "TBA" inside the LI.
The extractor detects TBA via regex and marks status as "TBA".

### 4. Combined Event (Masters/Uni)

Two championships in one page (Masters Nationals + University Nationals).

**Structure:** Standard Chakra UI, but registration section has twice as many
H3 items (one set for Masters, one set for University, plus adaptive variants).

**H3 headers observed:**
- `University Nationals Registration` → `/public/wizard/e/14333/home`
- `ADAPTIVE ATHLETES - University Nationals Registration` → `/public/wizard/e/14338/home`
- `Masters Nationals Registration` → `/public/wizard/e/14336/home`
- `ADAPTIVE ATHLETES - Masters Nationals Registration` → `/public/wizard/e/14337/home`
- `Mountain South WSO Championships Registration` → `/v/808740/e/meets/14473/overview`
- `Team Registration - University Nationals` → Google Form

**Key insight:** Adaptive headers use "ADAPTIVE ATHLETES - " prefix (uppercase).
The fuzzy matcher needs "adaptive athletes -" as an alias to catch this.

### 5. Prior Year (2025) — Different URL Slugs

2025 event pages use different URL slugs than 2026:

| 2026 URL | 2025 URL |
|----------|----------|
| `/2026-national-championships` | `/2025-usaw-national-championships` |
| `/2026-virus-weightlifting-series-1` | `/2025-north-american-open-series-1` |
| `/2026-virus-weightlifting-series-2-championships` | `/2025-north-american-open-series-2` |
| `/2026-virus-weightlifting-finals` | `/2025-north-american-open-finals` |

**Naming evolution:** "American Open" → "North American Open" (~2021) → "VIRUS Weightlifting Series" (~2024).

**Key insight:** The extractor works on the page HTML regardless of URL slug.
But when looking up an event page, always verify the URL via `/national-events`
rather than guessing the slug pattern.

## Sport80 URL Patterns

Three URL formats observed across events:

| Pattern | Example | Events Using It |
|---------|---------|-----------------|
| `/v/808740/e/meets/{ID}/overview` | `.../meets/14372/overview` | NCW 2026, VWS2, Finals |
| `/public/wizard/e/{ID}` or `/{ID}/home` | `.../wizard/e/14353` | VWS1, Masters/Uni, WZA, 2025 events |
| `/public/events/{ID}/entries/{ID}` | `.../events/14353/entries/21233` | VWS1 entry list |

`808740` is the constant USAW org ID on Sport80.

## H2 Section Headers (consistent across all events)

| H2 | Contains |
|----|----------|
| `Registration` | Sport80 links, qualifying totals, event policy, edit entry |
| `Information` | Tickets, hotels, live stream, photos, schedules, results, media |
| `Related` | Annual schedule announcement news link |
| `TRAINING HALL` | (NCW only) Training hall info + alternate sites |

## H3 Subsection Headers

All observed H3 headers from 2026 NCW (most complete page):

```
Glen Middleton award team registration
National Championships Registration
Adaptive National Championships Registration
U25 National Championships Registration
Adaptive U25 National Championships
Junior National Championships Registration
Adaptive Junior National Championships Registration
Youth National Championships Registration
Adaptive Youth National Championships Registration
Mountain North WSO Championships Registration
Qualifying Totals
Event Policy
Edit Entry
Event Guide
Tickets
Book a Hotel
Live Stream
Preorder Photo Packages
Preliminary Schedule
Final Schedule
Start List
Full Results
Media Credentials
```

## Nav Link Filtering

~35 navigation/footer links appear on every USAW page. These are NOT event
content and must be filtered via `_is_nav_link()`.

**Nav URL patterns denied:**
- `/coaching/`, `/weightlifting-101`, `/elite-education`
- `/youth-coach-fellowship`, `/free-courses`, `/online-education-courses`
- `/clubs-resource-corner`, `/prior-year-event-schedules`
- `/historical-results`, `/results$`, `/american-records`
- `/pan-am-games-medalists`, `/olympic-team-alumni`
- `/usaw-level-1`, `/usaw-level-2`, `/coaching/acsm`
- `/coach-advancement`, `/general-liability-insurance`
- `/referees$`, `/masters$`, `/video/playlists`
- `/womens-coaching-collective`, `/start-a-club`
- `/scholarships-and-support-services`, `/navigation/clubs`
- `/general-education-articles`, `/givebutter.com`
- `usawmeetings.chatango`, `/how-to-host-a-course`
- `usaweightliftingfoundation.org`
- `sport80.com/public/widget/` (calendar widgets, not event-specific)
- `sport80.com/widget/usaw_club`

## Fee Text Format Differences

| Year | Format | Example |
|------|--------|---------|
| 2026 | Inline with parenthetical fee | `Early Bird Registration ($145) Closes: May 7, 2026 - 2:00 p.m. MT` |
| 2025 | Fee on separate line or absent | `Early Registration` / `Closes: 2:00 p.m. MT on Thursday, May 8, 2025` |
| VWS1 | Flat fee | `Registration Cost: $199` |

The fee regex must handle both inline parenthetical `($145)` and separated formats.
2025 pages may not include fee amounts in the HTML at all.