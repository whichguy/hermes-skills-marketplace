# USAW Sport80 Meet IDs (2026)

All confirmed Sport80 meet IDs for 2026 national events, extracted via `usaw_event_extractor.py`.

Sport80 org ID: `808740` (constant in all URLs).

## URL Patterns

| Pattern | Format | Events Using This |
|---------|--------|--------------------|
| `v/meets` | `sport80.com/v/808740/e/meets/{ID}/overview` | NCW, VWS2, Finals |
| `public/wizard` | `sport80.com/public/wizard/e/{ID}` or `/{ID}/home` | VWS1, Masters/Uni, WZA |
| `public/events` | `sport80.com/public/events/{ID}/entries/{ENTRY_ID}` | VWS1 entry list |

## National Championships Week (NCW)

| Division | Meet ID | URL Pattern | Registration URL |
|----------|---------|-------------|-------------------|
| National Championships (Senior) | `14372` | v/meets | `sport80.com/v/808740/e/meets/14372/overview` |
| Adaptive National Championships | `14373` | v/meets | `sport80.com/v/808740/e/meets/14373/overview` |
| U25 National Championships | `14382` | v/meets | `sport80.com/v/808740/e/meets/14382/overview` |
| Adaptive U25 National Championships | `14383` | v/meets | `sport80.com/v/808740/e/meets/14383/overview` |
| Junior National Championships | `14380` | v/meets | `sport80.com/v/808740/e/meets/14380/overview` |
| Adaptive Junior National Championships | `14381` | v/meets | `sport80.com/v/808740/e/meets/14381/overview` |
| Youth National Championships | `14378` | v/meets | `sport80.com/v/808740/e/meets/14378/overview` |
| Adaptive Youth National Championships | `14379` | v/meets | `sport80.com/v/808740/e/meets/14379/overview` |
| Mountain North WSO Championships | `14473` | v/meets | `sport80.com/v/808740/e/meets/14473/overview` |
| Glen Middleton Award Team Registration | (Google Form) | — | `docs.google.com/forms/d/e/1FAIpQLSdwZmZ7MlP_7uuhRd0NOAJqaZFXm6-k2DHaky6KA86h4PNEhA/viewform` |

## VIRUS Weightlifting Series 1 (VWS1)

| Division | Meet ID | URL Pattern | Registration URL |
|----------|---------|-------------|-------------------|
| Standard Registration | `14353` | public/wizard | `sport80.com/public/wizard/e/14353` |
| Adaptive Athlete Registration | `14354` | public/wizard | `sport80.com/public/wizard/e/14354` |
| Entry List | `14353` (meet) / `21233` (entry) | public/events | `sport80.com/public/events/14353/entries/21233?bl=wizard` |

## Masters National Championships & National University Championships

| Division | Meet ID | URL Pattern | Registration URL |
|----------|---------|-------------|-------------------|
| University Nationals Registration | `14333` | public/wizard | `sport80.com/public/wizard/e/14333/home` |
| Masters Nationals Registration | `14336` | public/wizard | `sport80.com/public/wizard/e/14336/home` |
| Adaptive Athletes - University Nationals | `14338` | public/wizard | `sport80.com/public/wizard/e/14338/home` |
| Adaptive Athletes - Masters Nationals | `14337` | public/wizard | `sport80.com/public/wizard/e/14337/home` |
| Mountain South WSO Championships | `14473` | v/meets | `sport80.com/v/808740/e/meets/14473/overview` |

> Note: Mountain South WSO (Masters/Uni) and Mountain North WSO (NCW) share meet ID `14473`.

## VIRUS Weightlifting Series 2 (VWS2)

| Division | Meet ID | URL Pattern | Registration URL |
|----------|---------|-------------|-------------------|
| Registration | `14508` | v/meets | `sport80.com/v/808740/e/meets/14508/overview` |
| Adaptive Athlete Registration | `14509` | v/meets | `sport80.com/v/808740/e/meets/14509/overview` |
| Texas-Oklahoma WSO Championships | `14530` | v/meets | `sport80.com/v/808740/e/meets/14530/overview` |

## USAW x Gymreapers Wodapalooza SoCal (WZA)

| Division | Meet ID | URL Pattern | Registration URL |
|----------|---------|-------------|-------------------|
| Registration | `14783` | public/wizard | `sport80.com/public/wizard/e/14783/home` |

## VIRUS Weightlifting Finals

| Division | Meet ID | URL Pattern | Registration URL |
|----------|---------|-------------|-------------------|
| Registration | `14510` | v/meets | `sport80.com/v/808740/e/meets/14510/stage/21402` |
| Adaptive Athlete Registration | `14511` | v/meets | `sport80.com/v/808740/e/meets/14511/overview` |
| California North WSO Championships | `14678` | v/meets | `sport80.com/v/808740/e/meets/14678/overview` |

## How to Regenerate

```bash
uv run --with beautifulsoup4 --with requests --with rapidfuzz \
  python scripts/usaw_event_extractor.py https://www.usaweightlifting.org/2026-national-championships --json
```

Filter for `sport80` entries in `info_by_type` — the `classify_sport80_url()` function extracts meet_id automatically.