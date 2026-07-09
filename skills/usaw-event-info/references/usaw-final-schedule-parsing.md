# Final Schedule PDF Parsing — Complete Format Reference

> **Last updated:** 2026-07-08 — 3-format parser, 0 garbage sessions
> **Test PDF:** 2026 NCW Final Schedule (122 sessions: 31 full, 63 condensed, 28 WSO/ADAP)

## The Three Session Formats

The Final Schedule PDF contains sessions in three distinct formats. The parser must handle all three to avoid garbage sessions (platform name in weight_category, entries=0).

### Format 1: Full (8 values)

```
RED
12:00 PM
2:00 PM
M
Open
110+ A
310 - 390
11
```

**Structure:** platform, weigh_in, start_time, gender, age_group, weight_category, qualifying_totals, entry_count

**Validation:** gender must be "M" or "F", weight_category must contain digits and NOT be a platform name (WHITE/BLUE/RED/GREEN/YELLOW/ORANGE), entry_count must be a digit.

**Count:** 31 sessions (main competition sessions with full details)

### Format 2: Condensed (5 values)

```
WHITE
10:00 AM
12:00 PM
F
12
BLUE          ← next session's platform (delimiter)
10:00 AM
12:00 PM
M
10
```

**Structure:** platform, weigh_in, start_time, gender, age_group (no weight category, qualifying totals, or entry count)

**Detection:** The 6th value is another platform name (in PLATFORM_NAMES), or only 5 values remain on the page. The parser consumes exactly 5 values so the next platform becomes the start of the next session.

**Count:** 63 sessions (youth sessions — ages 8-14 — that don't have weight categories or entry counts in the PDF)

### Format 3: WSO/ADAP (4 values)

```
WSO M45
94 A
135 - 225
2
```

**Structure:** age_group, weight_category, qualifying_totals, entry_count (no platform, no times, no gender)

**Detection:** The age_group is in the WSO_AGE_GROUPS set (ADAP, WSO, WSO U13, WSO U17, WSO JR, WSO U25, WSO W35-W60, WSO M35-M60). "Open" is NOT in this set — it's also a valid full-format age group and would cause false detections. The next 3 lines must look like weight_cat (has digits, not a platform name), qualifying_totals (has dash), and entry_count (is digit).

**Count:** 28 sessions (adaptive, masters, and WSO championship sessions grouped separately from the main platform schedule)

## Detection Order (critical)

The parser checks formats in this order:

1. **Full format** — triggered by platform name (WHITE/BLUE/RED). Validates all 8 fields.
2. **Condensed format** — same platform trigger, but validation fails (no weight cat digits, or 6th value is another platform). Falls through to 5-value handling.
3. **WSO/ADAP format** — triggered by WSO_AGE_GROUPS keyword. No platform name needed.

**Why order matters:** The Final Schedule PDF contains "owlcms" in its header, so `detect_pdf_type` must check for `Session` + `Platform` + `Weigh-In` keywords BEFORE the `owlcms`/`Age Group` check. Otherwise the PDF is misidentified as `full_results` and parsed as garbage athletes.

## Garbage Prevention

The original parser (8-value only) produced 2 garbage sessions:
- `weight_category="BLUE"`, `entries=0` — the condensed section's next-platform delimiter was treated as a weight category
- `weight_category="13 RED"`, `entries=0` — the last session's garbled data

The 3-format parser produces **0 garbage sessions** by:
1. Validating weight_category has digits and is not a platform name
2. Detecting condensed format when the 6th value is a platform name
3. Detecting WSO/ADAP format by age_group keyword + field validation
4. Consuming exactly the right number of lines per format (8, 5, or 4)

## Verification

```bash
cd /opt/data/skills/sports/usaw-event-info/scripts
uv run --with pymupdf python3 -c "
import sys; sys.path.insert(0, '.')
from usaw_results_parser import parse_pdf
r = parse_pdf('../tests/fixtures/pdfs/2026-ncw-final-schedule.pdf')
sessions = r['sessions']
full = [s for s in sessions if s['platform'] and s['weight_category']]
condensed = [s for s in sessions if s['platform'] and not s['weight_category']]
wso = [s for s in sessions if not s['platform']]
garbage = [s for s in sessions if s['weight_category'] in {'WHITE','BLUE','RED','GREEN','YELLOW','ORANGE'}]
print(f'Total: {len(sessions)} | Full: {len(full)} | Condensed: {len(condensed)} | WSO/ADAP: {len(wso)} | Garbage: {len(garbage)}')
"
```

Expected: **122 sessions, 31 full, 63 condensed, 28 WSO/ADAP, 0 garbage.**
