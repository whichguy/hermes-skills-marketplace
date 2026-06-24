---
name: usaw-event-info
description: "Use when looking up USAW weightlifting event information — national events, local meets, registration, qualifying totals, schedules, results, live stream, tickets, or event policies. Knows the URL patterns, data locations, and info types across usaweightlifting.org and Sport80."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [usaw, weightlifting, events, registration, schedule, results, sport80]
    related_skills: [usaw-to-schedule, usaw-meet-card-parser]
---

# USAW Event Information Lookup

How to find any type of USA Weightlifting event information: national events, local meets, registration, schedules, results, qualifying totals, tickets, live streams, policies, and hotels.

## When to Use

- "Where do I find info about [USAW event]?"
- "How do I register for [national championship]?"
- "What are the qualifying totals for [event]?"
- "Where is the schedule / start list / results for [event]?"
- "How do I find a local meet near me?"
- "What's the live stream / ticket link for [event]?"
- "What are the event policies / rules?"
- "Where are hotels / venue info for [event]?"

Don't use for: TO-specific schedule management (→ `usaw-to-schedule`), athlete meet card parsing (→ `usaw-meet-card-parser`).

## USAW Website Architecture

USA Weightlifting operates two primary web platforms:

| Platform | URL | Purpose |
|----------|-----|---------|
| **usaweightlifting.org** | Marketing/info site | Event pages, news, qualifying totals, policies, governance, general info |
| **Sport80** (`usaweightlifting.sport80.com`) | Registration/membership platform | Event registration, membership management, athlete profiles, meet sanctioning, event calendar widget |

All **registration** links from usaweightlifting.org event pages deep-link into Sport80. Athletes must have an active Sport80 account + USAW membership to register.

## Information Type → Where to Find It

This is the core lookup table. Each info type maps to a URL pattern and the data you'll find there.

### 1. National Events — Landing Page

**URL:** `https://www.usaweightlifting.org/national-events`

Lists all upcoming national events with dates, venue, location, and links to each event's dedicated page. This is the **starting point** for any national event query.

Each event has a **dedicated event page** following the URL pattern:
```
https://www.usaweightlifting.org/{YEAR}-{event-slug}
```

Confirmed 2026 event page URLs:

| Event | URL |
|-------|-----|
| 2026 National Championships (NCW) | `/2026-national-championships` |
| 2026 VIRUS Weightlifting Series 1 | `/2026-virus-weightlifting-series-1` |
| 2026 Masters Nationals & University Nationals | `/2026-masters-national-championships-national-university-championships` |
| 2026 VIRUS Weightlifting Series 2 | `/2026-virus-weightlifting-series-2-championships` |
| 2026 USAW x Gymreapers Wodapalooza SoCal | `/2026-usaw-x-gymreapers-wodapalooza-socal` |
| 2026 VIRUS Weightlifting Finals | `/2026-virus-weightlifting-finals` |

**URL pattern recognition:** For future years, replace `2026` with `{YEAR}`. The event slug stays mostly stable year-to-year but check `/national-events` for the current year's links.

### 2. Registration (Sport80)

Each national event page contains registration links organized by championship division. Registration is on **Sport80** and follows this URL pattern:
```
https://usaweightlifting.sport80.com/v/808740/e/meets/{MEET_ID}/overview
```

Where `{MEET_ID}` is a numeric ID unique to each championship division (e.g. National Championships, U25, Junior, Youth, Adaptive divisions each have their own meet ID).

Registration categories per national event typically include:
- Senior National Championships (+ Adaptive)
- U25 National Championships (+ Adaptive)
- Junior National Championships (+ Adaptive)
- Youth National Championships (+ Adaptive)
- **WSO Championships** (e.g. "Mountain North WSO Championships" at NCW)
- Some events also include University or Masters divisions

**Registration tiers** (same across most national events):
| Tier | Fee | Closes |
|------|-----|-------|
| Early Bird | $145 | ~6 weeks before event |
| Regular | $175 | ~4 weeks before event |
| Late | $375 | ~2 weeks before event |

(VWS1 has a different fee structure — $199 flat.)

**Registration opens:** Typically January 1 of the event year, 2:00 p.m. MT.

### 3. Qualifying Totals

**URL:** `https://www.usaweightlifting.org/{YEAR}-usa-weightlifting-national-event-qualifying-totals`

Example: `/2026-usa-weightlifting-national-event-qualifying-totals`

Lists the minimum totals required to qualify for each national event, broken down by:
- Age group (Youth, Junior, U25, Senior, Masters)
- Gender
- Bodyweight category

**Key rule:** An athlete can hit a qualifying total in one bodyweight category and register in a different category for the competition. The qualifying total is tied to the athlete's performance, not the category they register in.

**New bodyweight categories** (effective Aug 1, 2026): USAW adopted IWF's new bodyweight categories. Post-Aug-1 qualifying totals apply to VWS2 and VIRUS Finals 2026.

**Adaptive athletes:** Minimum qualification total = 50% of the national qualifying standard. See [Adaptive Athlete Competition Requirements](https://www.usaweightlifting.org/resources/qualifying-totals/adaptive-athlete-competition-requirements).

### 4. Schedules, Start Lists, and Results

Each national event page publishes these documents, typically as PDFs hosted on Contentstack CDN:

| Document | What it contains | When published |
|----------|-------------------|----------------|
| **Preliminary Schedule** | Session order, platforms, weight categories | ~4 weeks before event |
| **Final Schedule** | Final session times, platforms, groups (A/B) | ~10 days before event |
| **Start List** | All registered athletes by session/platform | Same time as Final Schedule |
| **Full Results** | Session-by-session results | Updated live during event (Google Drive folder) |

**Schedule milestone timeline** (typical for a June national event):
1. Preliminary Schedule Released — ~4 weeks before
2. Verification of Final Entries (VFE) — ~2 weeks before (10:00–10:30 a.m. MT)
3. Final Schedule Released — ~7–10 days before
4. Start List published — same time as Final Schedule
5. Full Results — Google Drive folder, updated after each "A" session

**Results location:** Usually a Google Drive folder linked on the event page.

### 5. Event Policies & Rules

**URL:** `https://www.usaweightlifting.org/about-us/governance-and-financial/bylaws-technical-rules-and-policies/rules`

Contains:
- Competition Rules & USAW Rules Addendum
- National Events Policies
- Event edit/withdrawal policies
- Technical rules (IWF alignment)

### 6. Live Stream

**URL:** `https://www.usaweightlifting.org/live`

National events are typically live-streamed. The live page activates during event days.

### 7. Tickets

**URL:** `https://www.usaweightlifting.org/tickets`

Spectator tickets for national events. Usually available for purchase before the event.

### 8. Hotels / Accommodations

Each national event page includes hotel booking links with **group codes** for discounted rates. Hotels are typically near the venue with group rates available for the event window (sometimes extended a few days before/after).

Example (2026 NCW):
- Hilton Garden Inn COS Downtown (group code USAW26)
- Element (Marriott group link)
- SpringHill Suites (Marriott group link)
- Hyatt Regency (sometimes listed)

### 9. Local Meets / Event Calendar

**URL:** `https://usaweightlifting.sport80.com/public/widget/1`

The Sport80 event calendar widget lists **both local and national events**. This is the comprehensive calendar for finding any sanctioned USAW competition.

Also accessible from: `https://www.usaweightlifting.org/events` → "Find an Event"

### 10. WSO (Weightlifting State Organization) Championships

**URL:** `https://docs.google.com/spreadsheets/d/1FEmvRRzohx8aUvuHoNJ7yhPAIaeEQK_J/edit?gid=395204416#gid=395204416`

Google Sheet listing WSO championship events. Also linked from `/events`.

Some WSO championships run concurrently with national events (e.g. "Mountain North WSO Championships" at NCW, "Texas-Oklahoma WSO Championships" at VWS2).

### 11. National Team / International Events

**URL:** `https://www.usaweightlifting.org/resources/athlete-information-and-programs/international-squad-standings`

International competition schedule and USAW national team rankings.

### 12. Coaching Courses

**URL:** `https://usaweightlifting.sport80.com/public/widget/2`

Listed on the Event Calendars page (`/events`).

### 13. Event Photos

**URL:** `https://www.lifting.life/preorder` (for national events)

Photo packages are typically available for preorder before the event.

### 14. Media Credentials

Each national event page includes a media section with requirements:
1. Current U.S. Center for SafeSport training
2. Valid background check on file (effective March 2026)
3. Background checks take ~5 days — apply early

### 15. Annual Schedule Announcement

**URL pattern:** `https://www.usaweightlifting.org/news/{YEAR}/{month}/01/{YEAR}-usa-weightlifting-national-event-schedule`

USAW announces the full year's national event schedule each August for the following year. This news article lists all dates, venues, locations, and key changes.

## National Event Lifecycle (how info is released)

Understanding this timeline helps know what info is available when:

```
August (prior year)    → Schedule announced (news article)
January (event year)  → Registration opens (2:00 p.m. MT)
~6 weeks before       → Early Bird registration closes
~4 weeks before       → Regular registration closes / Preliminary schedule
~2 weeks before       → Late registration closes / VFE
~10 days before       → Final schedule + Start list
During event          → Live stream + Results (Google Drive)
After event           → Full results archived
```

## 2026 National Events Calendar (confirmed)

| Event | Dates | Venue | Location |
|-------|-------|-------|----------|
| VWS1 | Mar 5–8 | Greater Columbus Convention Center | Columbus, OH |
| Masters Nationals / University Nationals | Apr 9–12 | Salt Palace Convention Center | Salt Lake City, UT |
| National Championships Week | Jun 20–28 | Ed Robson Arena | Colorado Springs, CO |
| VIRUS Weightlifting Series 2 | Sep 10–13 | Fort Worth Convention Center | Fort Worth, TX |
| USAW x Gymreapers Wodapalooza SoCal | Sep 25–27 | — | Huntington Beach, CA |
| VIRUS Weightlifting Finals | Dec 3–6 | Alameda County Fairgrounds | Pleasanton, CA |

## How to Look Up Event Info (procedure)

1. **Identify the event and year.** If the user names a specific event (e.g. "2026 Nationals"), go to its dedicated event page at `usaweightlifting.org/{YEAR}-{slug}`. If unsure which event, start at `/national-events`.
2. **Extract the event page** with `web_extract`. The page contains: dates, venue, location, registration links (Sport80 deep-links), qualifying totals link, schedule PDFs, start list, results, hotel links, tickets, live stream, media info, and policy links.
3. **For registration details**, follow the Sport80 deep-links from the event page. Each division (Senior, U25, Junior, Youth, Adaptive) has its own Sport80 meet ID.
4. **For qualifying totals**, go to `/{YEAR}-usa-weightlifting-national-event-qualifying-totals`.
5. **For schedules/results**, check the event page for PDF links. If the event is in progress or past, check for a Google Drive results folder link.
6. **For local meets**, use the Sport80 calendar widget at `usaweightlifting.sport80.com/public/widget/1` or the `/events` page.
7. **For policies/rules**, go to `/about-us/governance-and-financial/bylaws-technical-rules-and-policies/rules`.
8. **Check the wiki** (`/opt/data/wiki`) for Jim's existing knowledge — search for `usaw-event-info-sources`, `usaw-competitions-events`, `usaw-weightlifting`, or `ncw-2026-to-logistics`.

## Wiki cross-references

- [[usaw-event-info-sources]] — wiki page with full URL catalog and info-type mapping (companion to this skill)
- [[usaw-weightlifting]] — USAW governing body entity page
- [[usaw-competitions-events]] — competition calendar and event participation data
- [[ncw-2026-to-logistics]] — NCW 2026 TO logistics (event-specific)

## Google Drive Results Folders

Each national event publishes results to a Google Drive folder (linked from the event page as "Full Results"). The `/results` archive page lists all historical folders (2012–present).

### Folder naming convention
```
{YEAR} - {EVENT_ABBR} - Results
```
Examples: `2026 - NCW - Results`, `2026 - VWS1 - Results`, `2026 - Masters & Uni - Results`

### File types inside results folders

| Doc Type | File Pattern | Description |
|----------|-------------|-------------|
| **Full Results** | `Results.pdf` | All sessions, all athletes, all attempts (owlcms-generated) |
| **Best Lifters** | `Results - {DIV} Best Lifters.pdf` | Top 10 per weight class by Sinclair/QPoints |
| **Teams** | `Results - {DIV} Teams.pdf` | Team standings by division |
| **Medal Schedule** | `Medal Schedule.pdf` | Ceremony times by category |
| **Registered Teams** | `Registered Teams.pdf` | Pre-event team list (NUC only) |
| **Glen Middleton Award** | `Glen Middleton Award.pdf` | Team award (NCW only) |

### Full Results PDF data structure (owlcms)

Each page = one Age Group + Gender + Weight Category. Columns:
```
T (sn/cj/total rank) | sn 1st 2nd 3rd | cj 1st 2nd 3rd | Lot | Name | Team | Wt. | Age | Total | Score
```
- Attempts in kg, bodyweight to 2 decimal places
- DNF entries show `DNF` in Total/Score
- Score = Sinclair (senior) or QPoints/QYouth (youth/junior)

### Division codes in filenames

U11, U13, U15, U17, U23, U25, JR, Open, Masters, Military, Military Masters, University, ADAP (Adaptive)

### Historical results archive

`usaweightlifting.org/results` — Google Drive links for all events 2012–present.
- 2018+: Google Drive folders
- Pre-2018: AWS S3 direct PDF/Excel links
- Sponsor naming: "American Open" → "North American Open" (~2021) → "VIRUS Weightlifting Series" (~2024)

`usaweightlifting.org/prior-year-event-schedules` — Prelim/Final schedule PDFs from 2021–2025 on Contentstack CDN (stable URLs).

## Auto-Extraction Script

`scripts/usaw_event_extractor.py` — fetches any USAW event page and extracts all structured info using fuzzy header matching + URL pattern classification.

```bash
# Markdown output (human-readable, grouped by info type)
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/usaw_event_extractor.py https://www.usaweightlifting.org/2026-national-championships

# JSON output (for programmatic use)
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/usaw_event_extractor.py https://www.usaweightlifting.org/2026-national-championships --json

# Verbose (show unclassified links for debugging)
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/usaw_event_extractor.py https://www.usaweightlifting.org/2026-national-championships -v
```

**What it extracts:**
- Event title, dates, venue, location (from H1 + overview paragraph)
- Registration links per division (Sport80, with meet IDs and URL pattern)
- Qualifying totals, event policies, edit entry guides
- Schedule PDFs (preliminary, final, start list) + results (Google Drive)
- Tickets, live stream, photo packages, hotels, training sites
- Media credentials + background check links
- Inline metadata: registration fees ($145/$175/$375 tiers), schedule milestones, deadlines
- Sport80 URL classification: `/v/meets/{ID}`, `/public/wizard/e/{ID}`, `/public/events/{ID}/entries/{ID}`

**Info type taxonomy (22 types):**

| Category | Info Types |
|----------|-----------|
| Registration | `registration`, `adaptive_registration`, `wso_registration`, `team_registration` |
| Reference | `qualifying_totals`, `event_policy`, `edit_entry`, `event_guide`, `adaptive_athlete_info`, `become_member`, `schedule_announcement` |
| Schedule | `preliminary_schedule`, `final_schedule`, `start_list`, `full_results`, `medal_schedule` |
| Spectator | `tickets`, `live_stream`, `photo_packages` |
| Travel | `hotel`, `training_sites`, `helpful_links` |
| Media | `media_credentials` |

**Fuzzy matching strategy:**
1. URL pattern matching first (most reliable — e.g. `sport80.com/v/meets/` → registration)
2. H3 header fuzzy matching via `rapidfuzz.fuzz.partial_ratio` (threshold: 60)
3. Link text as fallback context when H3 is empty (VWS1 inline style)
4. Navigation/footer link filtering via `_is_nav_link()` denylist

**Handles layout differences:**
- **Chakra UI** (NCW, VWS2, Finals): H2 and UL in sibling divs inside `.content-tile-block`
- **Inline** (VWS1): Links in `<p>` tags without structured H3 sections
- **Minimal** (WZA): Fewer sections, no hotels/schedules (TBA)
- **Combined** (Masters/Uni): Multiple registration divisions with different Sport80 patterns

Test results across all 6 event pages (2026): **100% classification rate, 0 unclassified, 0 noise**.

## Fuzzy Matching Techniques

The extractor uses a **header_priority** disambiguation pattern when multiple
info types match the same URL pattern. This is the core technique for handling
layout differences across events.

**How it works:**
1. URL pattern matching runs first — some patterns match multiple types
   (e.g. `assets.contentstack.io.*schedule` matches both `preliminary_schedule`
   and `final_schedule`)
2. Types with `header_priority: True` require the H3 header text to fuzzy-match
   their aliases at ≥80% threshold (higher than the 60% default)
3. If only one priority type passes, it wins
4. If multiple pass, header fuzzy matching picks the best among priority types
5. If no priority types pass, falls back to header matching among all URL matches
6. If URL matching fails entirely, pure header fuzzy matching at 60% threshold

**When to add `header_priority: True`:** Any info type whose URL pattern
overlaps with another type's URL pattern. Without it, the first dict iteration
order wins arbitrarily.

See `references/usaw-event-page-layouts.md` for the full DOM layout reference
(Chakra UI, inline, minimal, combined-event patterns) and nav link filter list.

## Test Suite

`scripts/test_extractor.py` — 11 tests across 2026 (6 events) + 2025 (5 events).

```bash
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/test_extractor.py -v
```

Tests validate: required info types per event, zero unclassified, title/dates/venue
extraction, Sport80 URL patterns, Google Drive results links, TBA/TBD status,
fee/milestone metadata, and edge cases (WZA minimal, Masters/Uni combined, prior-year slugs).

## Results PDF Parser Script

`scripts/usaw_results_parser.py` — downloads and parses owlcms-generated results PDFs from Google Drive folders into structured JSON.

```bash
# Parse a local PDF
uv run --with pymupdf python scripts/usaw_results_parser.py /path/to/results.pdf --json

# Download + parse a specific Drive file
uv run --with pymupdf --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
  python scripts/usaw_results_parser.py --drive-file-id 1V9-fFSa4C2GrPB-4hIqD7G-4qzg_Mf2Z --json

# List files in a Drive results folder
uv run --with pymupdf --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
  python scripts/usaw_results_parser.py --folder-id 14ncrwEnqErUKGomckAdG_LOT0qEbRomI

# Download + parse ALL PDFs in a Drive results folder
uv run --with pymupdf --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
  python scripts/usaw_results_parser.py --folder-id 14ncrwEnqErUKGomckAdG_LOT0qEbRomI --all --json
```

**Three PDF types parsed:**
- **Full Results** (`Results.pdf`): owlcms export — all athletes, all attempts, all categories. Extracts: lot, name, team, bodyweight, age, snatch attempts (3), CJ attempts (3), total, score, age_group, gender, weight_category.
- **Best Lifters** (`{DIV} Best Lifters.pdf`): ranked list by Sinclair/QPoints. Extracts: division, gender, name, team, bodyweight, age, snatch, CJ, total, score.
- **Start List** (`start-list.pdf`): pre-event registration. Extracts: lot, name, team, entry_total, age.

**Test results** (2026 NCW PDFs):
- Full Results: 788 athletes, 88 categories, 755 complete records with full attempt data
- Best Lifters: 20 athletes (U11 division), all with snatch/CJ/total/score
- Start List: parsing functional (tested separately)

**Reference files:**
- `references/usaw-sport80-meet-ids.md` — all confirmed 2026 Sport80 meet IDs (25 divisions across 6 events)
- `references/usaw-results-folder-ids.md` — all confirmed Google Drive folder IDs (2024–2026)

## Daily Sync Cron

`scripts/usaw_event_info_sync.py` — re-runs the extractor daily on all 2026 event pages, compares to the previous snapshot, runs the test suite, and reports any new/changed info.

```bash
# Manual dry run
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/usaw_event_info_sync.py --dry-run

# Run and update snapshot (used by cron)
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/usaw_event_info_sync.py
```

**Cron job:** `usaw-event-info-sync` runs daily at 4:00 a.m. PT. It is a
script-only cron (`no_agent: true`) and stays silent when no changes are found.

**What it monitors:**
- Event title, dates, venue, status
- New/removed info types
- New URLs added to the event page
- Test suite pass/fail status

## USAW Event Information Schema

For the **persistent schema** behind this skill — the metadata fields, competition lifecycle, age groups, bodyweight categories, scoring systems, and historical synonyms — see the wiki page `[[usaw-event-info-schema]]`.

The schema page documents:
- Registration → VFE → Schedule → Competition → Results lifecycle
- Age groups and divisions (U11, U13, U15, U17, JR, U23, U25, Senior, Masters, University, Military, Adaptive)
- Bodyweight category changes (pre/post Aug 1, 2026)
- Qualifying totals and cross-period qualification rules
- Scoring system evolution (Sinclair → QPoints, SMF → Q-Masters, SHMF, QYouth)
- Event naming evolution (American Open → North American Open → VIRUS Weightlifting Series)
- Synonyms and alternate terms (Sport:80/BARS, VFE, NCW, WSO, TO, etc.)
- owlcms data model and document types

## Common Pitfalls

1. **Event pages change yearly.** The `{YEAR}-{slug}` pattern is stable for recurring events, but new events (e.g. Wodapalooza SoCal) or combined events (Masters + University Nationals 2026) may have unexpected slugs. Always verify via `/national-events`.

2. **Sport80 meet IDs are per-division.** A single national event has 5–10 separate Sport80 meet IDs (one per championship division). Don't assume one registration link covers all divisions.

3. **Qualifying totals change mid-year.** USAW adopted new IWF bodyweight categories effective Aug 1, 2026. Events before Aug 1 use pre-change totals; events after use new totals. Always check the date on the qualifying totals page.

4. **Schedule PDFs are on Contentstack CDN.** These URLs are long `assets.contentstack.io` links that change when updated. Don't hardcode them — always extract from the event page.

5. **Results are often in Google Drive folders**, not on the USAW site. The event page links to a shared Drive folder that gets updated after each session.

6. **Local meets are NOT on usaweightlifting.org event pages.** They're on the Sport80 calendar widget only. The `/national-events` page only lists national-level events.

7. **Times are always Mountain Time (MT)** unless otherwise noted. USAW is headquartered in Colorado Springs and defaults to MT for all announcements and deadlines.

8. **Registration deadlines are at 2:00 p.m. MT**, not midnight. Missing a deadline by a few hours means paying the next tier ($145 → $175 → $375).

9. **Event page layouts differ.** The extractor uses fuzzy matching (rapidfuzz) + URL patterns to handle Chakra UI (NCW/VWS2/Finals), inline-paragraph (VWS1), minimal (WZA), and combined-event (Masters/Uni) layouts. If a new event page uses a different CMS layout, add new nav patterns to `_is_nav_link()` and new info type aliases to `INFO_TYPES`. Run with `-v` to see unclassified links.

10. **Sport80 URL patterns vary by event.** NCW uses `/v/808740/e/meets/{ID}/overview`, VWS1 uses `/public/wizard/e/{ID}`, Masters/Uni uses `/public/wizard/e/{ID}/home`. The extractor's `classify_sport80_url()` handles all three and extracts the meet_id.

11. **`header_priority` threshold must be 80%, not 60%.** The default fuzzy threshold is 60, but `"wso championships"` matches `"National Championships Registration"` at 82 via `partial_ratio` — both contain "championships". Using 60 would misclassify every standard registration as WSO registration. The 80% threshold catches this. When adding new `header_priority` types, always test the false-positive rate with `rapidfuzz.fuzz.partial_ratio` against known headers.

12. **Prior-year pages use different URL slugs.** The `{YEAR}-{event-slug}` pattern is NOT stable across years. 2025 NCW is `/2025-usaw-national-championships` (with "usaw" prefix), while 2026 is `/2026-national-championships` (without). VWS1 was `/2025-north-american-open-series-1` in 2025 but `/2026-virus-weightlifting-series-1` in 2026. Always verify event URLs via `/national-events` rather than guessing the slug.

## Verification Checklist

- [ ] Correct event year and slug identified
- [ ] Event page extracted and parsed for all available info types
- [ ] Sport80 registration links identified (per division)
- [ ] Qualifying totals URL checked for the correct period (pre/post Aug 1)
- [ ] Schedule milestone timeline checked (what's been published vs what's pending)
- [ ] Wiki searched for existing Jim-specific knowledge about the event
- [ ] All URLs verified as live (not 404) before presenting to user
- [ ] If extractor was modified: run `scripts/test_extractor.py -v` — all 11 tests must pass