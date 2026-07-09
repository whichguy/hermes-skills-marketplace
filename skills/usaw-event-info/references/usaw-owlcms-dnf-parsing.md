# owlcms DNF Parsing — Complete Pattern Reference

> **Last updated:** 2026-07-08 — `lines_consumed` refactor + standalone DNF handler complete, 0 false parses
> **Test PDF:** 2026 NCW Full Results (1,341 athletes, 45 DNF)

## The Three DNF Layouts

The string "DNF" appears in owlcms results PDFs in three distinct layouts. Only one is a reliable athlete-start marker.

### Layout 1: All-DNF on one line ("DNF DNF DNF")

```
DNF DNF DNF  ← all 6 attempts failed
119
THIBAULT, McKenzie
Orlando Strength
51.55
18
Age Group JR W    ← next section (no attempt values follow)
```

**Meaning:** The athlete failed all attempts. The next lines contain lot → name → team → bodyweight → age. No attempt values follow — the next section header or athlete starts immediately after age.

**Parser behavior:** Detect the "DNF DNF DNF" line, find the lot number in the following lines, call `parse_athlete_lines()` starting at the lot line. Skip `lines_consumed` lines.

### Layout 2: All-DNF on three lines (3 consecutive "DNF" lines)

```
DNF          ← sn_rank
DNF          ← cj_rank
DNF          ← total_rank
9
DNF          ← snatch attempt (failed)
303
LIVINGSTON, Ciara
```

**Meaning:** Same as Layout 1 (all attempts failed), but the DNF markers are split across three lines. The lot may be followed by a "DNF" attempt value before the next numeric value.

**Parser behavior:** Detect 3 consecutive "DNF" lines, search forward for the lot number (first digit after the block), call `parse_athlete_lines()` starting at the lot line. The DNF boundary detection inside `parse_athlete_lines` handles the attempt-value DNF after the lot.

### Layout 3: Partial DNF ("DNF DNF" + 1 numeric rank)

```
99
152.696
DNF DNF  ← cj_rank + total_rank (athlete had valid snatch, DNF'd CJ)
7
1240
ILANO, Lucy
Orlando Strength
51.55
18
50  51  51    ← snatch attempts
65  68  70    ← cj attempts
121           ← total
```

**Meaning:** The athlete had a valid snatch (and thus a snatch rank) but DNF'd clean & jerk. The cj_rank and total_rank are both "DNF". The next lines contain the NEXT athlete's rank + lot + name.

**Parser behavior:** Skip the "DNF DNF" line. The next athlete starts with a numeric rank (7), then lot (1240), then name. Detected by the **1-rank detector**.

## Detection Logic (current implementation)

### 1. Normal athlete detection (3-rank pattern)

Three consecutive small integers (ranks 1-20) followed by a larger integer (lot 1-2000):
```python
if line.isdigit() and 1 <= int(line) <= 20:
    if (i + 3 < len(lines) and all lines[i+j].strip().isdigit() and 1 <= int(lines[i+j].strip()) <= 20 for j in range(3))
            and lines[i+3].strip().isdigit() and 1 <= int(lines[i+3].strip()) <= 2000):
        athlete, consumed = parse_athlete_lines(lines, i + 3, int(lines[i+3].strip()), ...)
        i = i + 3 + consumed  # skip exactly consumed lines
```

### 2. 1-rank DNF detection (handles Layout 3)

When only 1 numeric rank precedes the lot (other 2 ranks are "DNF" text, already skipped):
```python
if line.isdigit() and 1 <= int(line) <= 50:
    if (i + 2 < len(lines) and lines[i+1].strip().isdigit()
            and 1 <= int(lines[i+1].strip()) <= 2000
            and int(lines[i+1].strip()) > 50):
        name_line = lines[i+2].strip()
        if "," in name_line or (name_line.isupper() and len(name_line) > 3):
            athlete, consumed = parse_athlete_lines(lines, i + 1, int(lines[i+1].strip()), ...)
            i = i + 1 + consumed
```

**Key insight:** The rank must be ≤50 and the lot must be >50. This distinguishes rank values (1-50) from attempt values (50-200+ kg). Without this distinction, attempt values like 53, 65, 68 were being treated as rank+lot pairs, creating false parses.

### 3. 3-DNF block detection (handles Layouts 1 & 2)

```python
# Layout 1: single line "DNF DNF DNF"
if line == "DNF DNF DNF":
    # Search forward for lot number, parse athlete
    athlete, consumed = parse_athlete_lines(lines, lot_idx, int(lines[lot_idx].strip()), ...)
    i = lot_idx + consumed

# Layout 2: three consecutive "DNF" lines
if (line == "DNF" and i + 2 < len(lines)
        and lines[i+1].strip() == "DNF"
        and lines[i+2].strip() == "DNF"):
    # Search forward for lot number, parse athlete
    athlete, consumed = parse_athlete_lines(lines, lot_idx, int(lines[lot_idx].strip()), ...)
    i = lot_idx + consumed
```

### 4. Standalone DNF skip → DNF athlete detection

Single "DNF" and "DNF DNF" lines that aren't part of a 3-DNF block are now checked for a lot number within 5 lines:

```python
if line == "DNF" or line == "DNF DNF":
    # Check if there's a lot number following within 5 lines
    lot_idx = None
    for j in range(i + 1, min(i + 6, len(lines))):
        v = lines[j].strip()
        try:
            n = int(v)
            if 1 <= n <= 2000:
                lot_idx = j
                lot_val = n
                break
        except ValueError:
            pass
    
    if lot_idx is not None:
        # This IS a DNF athlete - parse it starting from the lot position
        athlete, consumed = parse_athlete_lines(lines, lot_idx, lot_val, ...)
        if athlete:
            athletes.append(athlete)
        i = lot_idx + 1 + consumed
    else:
        # No lot found - this is a status marker for another athlete
        pass
    i += 1
    continue
```

**This catches 26 additional DNF athletes** that were previously skipped as noise (1,315 → 1,341 athletes, 22 → 45 DNF). The key insight: some DNF athletes have their DNF markers on a separate line from their lot number, and the old code treated these as standalone noise to skip.

## `parse_athlete_lines` Return Type

**As of 2026-07-08, `parse_athlete_lines` returns `(athlete, lines_consumed)` tuple.** The function tracks `last_consumed_idx` during line iteration and returns the exact number of lines consumed. All 3 call sites use `athlete, consumed = parse_athlete_lines(...)` and set `i = start_position + consumed`.

**DNF boundary detection:** The function stops collecting values when it encounters a "DNF" line after already collecting ≥3 values. This prevents attempt-value DNFs inside athlete data (e.g., LIVINGSTON's "DNF" after lot 9) from triggering a false boundary — the function has only collected 1 value (the lot) at that point, so it continues past the DNF to collect the rest of the athlete's data.

**The old fixed-skip approach (16/12/13) is fully retired.** It took 4 iterations to tune and was still wrong for edge cases. The `lines_consumed` approach is precise and handles variable-length athlete blocks (QPoints, QYouth extra fields) correctly.

## Verification

After any parser change, verify against the NCW 2026 Results.pdf:

```bash
cd /opt/data/skills/sports/usaw-event-info/scripts
uv run --with pymupdf python3 -c "
import sys; sys.path.insert(0, '.')
from usaw_results_parser import parse_full_results
result = parse_full_results('../tests/fixtures/pdfs/2026-ncw-results.pdf')
athletes = result.get('athletes', [])
print(f'Total: {len(athletes)}')
print(f'DNF in name: {len([a for a in athletes if \"DNF\" in a.get(\"name\",\"\")])}')
print(f'DNF (total=0): {len([a for a in athletes if a.get(\"total\") == 0])}')
"
```

Expected: **1,341 athletes, 0 false parses, 45 DNF (total=0).**

Also run the full test suite:
```bash
uv run --with pytest --with beautifulsoup4 --with rapidfuzz python3 -m pytest test_extractor_mock.py test_extractor_units.py test_results_parser.py test_page_health.py test_coverage_expansion.py -q
```

Expected: **134/134 pass**.

## Key Athletes (regression checks)

These athletes exercise all three DNF layouts and must be present after any parser change:

| Athlete | Lot | Layout | Expected total | Notes |
|---------|-----|--------|---------------|-------|
| THIBAULT, McKenzie | 119 | 1 (DNF DNF DNF, made both lifts) | 125 (56+69) | total computed from snatch_best + cj_best |
| ILANO, Lucy | 7 | 3 (DNF DNF, 1 numeric rank) | 121 | normal athlete after partial-DNF predecessor |
| LIVINGSTON, Ciara | 9 | 2 (3 consecutive DNF lines) | 0 | all attempts failed |
| SHARP, [first] | 4 | Normal (full ranks) | 169 | baseline normal athlete |
| CAMPBELL, [first] | 1076 | Normal (full ranks) | 95 | baseline normal athlete |

## Unit Tests (isolated, no PDF fixture needed)

Three isolated unit tests in `test_results_parser.py` cover each DNF layout:

```python
def test_dnf_layout_1_all_dnf_one_line():   # "DNF DNF DNF" → lot → name
def test_dnf_layout_2_all_dnf_three_lines(): # 3× "DNF" → lot → name
def test_dnf_layout_3_partial_dnf_one_rank(): # "DNF DNF" → rank → lot → name
```

Each test constructs a minimal line list, calls `parse_athlete_lines()` directly, and asserts the athlete dict fields. No PDF fixture needed — these test the parser logic in isolation.
