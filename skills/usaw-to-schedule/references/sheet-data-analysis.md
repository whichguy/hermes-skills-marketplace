# TO Sheet Data Analysis — Findings & Feature Ideas

Analysis run Jun 22, 2026 against the live `2026 NCW` tab of the TO Sign-up
workbook. Findings are data-driven from the actual sheet contents, not
hypothetical. Feature ideas are ranked by impact and effort.

## Sheet overview

- **45 sessions** across 9 days (Jun 20–28, 2026)
- **3 platforms** (RED, WHITE, BLUE) running concurrently per session
- **73 unique TOs** assigned across all role columns
- **7 role types**: Referee (335 assignments), Marshal (194), Weigh-in (174),
  Speaker (120), Timekeeper (8), TC (4), Jury (only on A sessions)

## Workbook tabs

| Tab | Meet | Date range | Notes |
|-----|------|------------|-------|
| `2026 NCW` | Nationals / Youth | Jun 20–28, 2026 | Current event, header row 7 |
| `2026 WZA` | WZA meet | Mar 2026 | Compressed layout, 1 ref/platform, header row 8 |
| `VWS1` | Virus Weightlifting Series 1 | Mar 2026 | Columns shifted right vs NCW |
| `2026 MC & UNI` | Masters & University Nationals | Apr 2026 | Columns shifted, Special Jury slot |
| `List of TOs` | TO roster directory | — | 2,558 entries: name, cert tag, email, phone |

### List of TOs tab

- Columns: A=Name (with cert tag), B=Cert tag only, C=Email, D=Phone
- Some phone fields are `#ERROR!` (import formula failures) or raw floats
  (e.g. `17185551234.0` — missing leading `+`)
- Use case: quick lookup of a TO's certification level or contact info during
  the meet (finding a substitute, identifying someone on site)

## Multi-platform conflicts

**42 conflicts found** where a single TO is assigned to 2+ platforms in the
same session. This is common for weigh-in officials who also referee —
weigh-in runs 1hr before start, then they move to refereeing on another
platform. Most are intentional, but some may not be.

### Jim's conflicts (4)

| Session | Platform 1 | Role 1 | Platform 2 | Role 2 | Feasible? |
|---------|-----------|--------|-----------|--------|-----------|
| S7 | RED | Weigh-in | WHITE | Speaker | ✅ weigh-in ends 1hr before start |
| S11 | WHITE | Weigh-in | BLUE | Referee | ✅ same pattern |
| S18 | RED | Weigh-in | BLUE | Referee | ✅ weigh-in 1PM, ref 3PM |
| S20 | RED | Weigh-in | BLUE | Marshal | ✅ weigh-in 5PM, marshal 7PM |

### Conflict detection logic

A conflict is **time-feasible** if:
- Weigh-in duty (max 1hr) ends before the other role's report time
- Weigh-in ends at `win_time + 1hr`
- Other roles report at `start_time` (referee/speaker/TC/jury) or `start_time - 30min` (marshal)

A conflict is **not feasible** if two same-time roles are on different platforms
(e.g. refereeing RED and WHITE at the same start time — impossible, platforms
run concurrently).

## Empty role slots

**364 total empty slots** across the meet:

| Role | Empty count | Critical? |
|------|-------------|-----------|
| Jury | 122 | No — only needed on A sessions (JR/U25 & Nationals) |
| Timekeeper | 114 | Low — often filled day-of |
| TC | 109 | Low — technical controller, 1 per session |
| Weigh-in | 14 | **Yes** — weigh-in can't run without officials |
| Speaker | 2 | **Yes** — announcement role |
| Marshal | 2 | **Yes** — platform safety role |
| Referee | 1 | **Yes** — required for competition |

The critical gaps (Weigh-in, Speaker, Marshal, Referee) are the ones meet
organizers need to fill. The rest may be intentionally left open.

## Jim & Kelly workload

| Day | Jim sessions | Kelly sessions | First start | Last start | Notes |
|-----|-------------|---------------|-------------|------------|-------|
| Sat Jun 20 | 2 | 3 | 8:00 AM | 8:00 PM | Long day |
| Sun Jun 21 | 1 | 2 | 8:00 AM | 8:00 PM | |
| Mon Jun 22 | 4 | 4 | 9:00 AM | 7:00 PM | Heaviest day — S15, S16, S18, S20 |
| Tue Jun 23 | 2 | 2 | 10:00 AM | 6:00 PM | |
| Wed Jun 24 | 0 | 0 | — | — | Day off |
| Thu–Sun | 0 | 0 | — | — | No assignments |

### Jim role distribution

| Role | Count |
|------|-------|
| Referee | 8 |
| Weigh-in | 4 |
| Speaker | 3 |
| Marshal | 2 |

### Kelly role distribution

| Role | Count |
|------|-------|
| Referee | 13 |
| Weigh-in | 5 |
| Marshal | 2 |

## Feature ideas (ranked)

### 1. Multi-platform conflict warnings (high value, low effort)
- Alert when a TO's assignments on different platforms in the same session
  are **not time-feasible** (weigh-in + same-time refereeing on another platform)
- Could run as part of the change-watch cron — alert only on NEW conflicts
- Most conflicts are intentional (weigh-in → referee pattern), so filter to
  only flag infeasible ones

### 2. Daily workload summary (high value, low effort)
- Morning "day ahead" message: total sessions, first weigh-in, last session
  end, total break time, platforms assigned, roles
- Could be a no_agent script run at 6 AM MT during the event window
- Helps Jim plan his day, meals, breaks

### 3. Empty slot tracker (medium value, low effort)
- Daily report of critical unfilled roles (Weigh-in, Referee, Marshal, Speaker)
- Filter out non-critical (Timekeeper, TC, Jury — often filled day-of)
- Could be a no_agent script run once daily for meet organizers
- Less useful for Jim personally, more useful for USAW staff

### 4. TO roster quick-lookup (medium value, medium effort)
- Query the `List of TOs` tab for name → certification + contact info
- Useful on-site when needing a substitute or identifying someone
- Would need a simple CLI or Telegram command interface

### 5. Athlete-TO cross-reference (low value, high effort)
- Cross-reference `ncw_alerts.py` athlete schedule with TO assignments
- Alert when Jim's TO assignment is same platform/session as a Fortified
  Strength athlete (Athlete Name, Kimberly, etc.)
- Limited use — Jim already knows his athletes' schedules

### 6. Multi-meet support (low value, medium effort)
- Make the `TAB` constant configurable so scripts can point at WZA, VWS, etc.
- Only useful if Jim TOs at multiple meets in the same workbook
- Low priority until next meet season