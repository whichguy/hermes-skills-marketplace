#!/usr/bin/env python3
"""
USAW Results Parser — downloads and parses owlcms-generated results PDFs from
Google Drive folders into structured JSON.

Handles three PDF types:
  1. Full Results (Results.pdf) — owlcms export with all sessions/athletes/attempts
  2. Best Lifters ({DIV} Best Lifters.pdf) — ranked list by Sinclair/QPoints
  3. Start List (start-list.pdf) — pre-event registration list

Usage:
  # Parse a local PDF file
  uv run --with pymupdf python usaw_results_parser.py /path/to/results.pdf --json

  # Parse a local PDF, show summary
  uv run --with pymupdf python usaw_results_parser.py /path/to/results.pdf

  # Download from Google Drive folder (requires auth)
  uv run --with pymupdf --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
    python usaw_results_parser.py --folder-id 14ncrwEnqErUKGomckAdG_LOT0qEbRomI --json

  # Download a specific file by Drive file ID
  uv run --with pymupdf --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
    python usaw_results_parser.py --drive-file-id 1V9-fFSa4C2GrPB-4hIqD7G-4qzg_Mf2Z --json

  # Parse all PDFs in a Drive folder and output combined JSON
  uv run --with pymupdf --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
    python usaw_results_parser.py --folder-id 14ncrwEnqErUKGomckAdG_LOT0qEbRomI --all --json

Requires: pymupdf (fitz), and optionally google-api-python-client for Drive access.
"""

import re
import sys
import json
import argparse
from pathlib import Path

try:
    import fitz  # pymupdf
except ImportError:
    print("ERROR: pip install pymupdf", file=sys.stderr)
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────
# PDF type detection
# ──────────────────────────────────────────────────────────────────────

def detect_pdf_type(doc: fitz.Document) -> str:
    """Detect the type of USAW results PDF by examining its text.
    
    Detection order matters: specific formats must be checked before generic
    headers. The owlcms header appears in ALL PDF types, so 'owlcms' or
    'Age Group' checks must come AFTER format-specific checks (Best Lifters,
    Start List, Final Schedule, Medal Schedule). Otherwise schedule/start-list
    PDFs get misidentified as full_results.
    """
    first_page_text = doc[0].get_text() if len(doc) > 0 else ""
    
    # Best Lifters: typically 1 page, contains "Best Lifters" or ranked list
    if "Best Lifters" in first_page_text or ("Best" in first_page_text and "Women" in first_page_text and "Men" in first_page_text):
        return "best_lifters"
    
    # Start List: contains "Start list provided by" header
    if "Start list" in first_page_text or "start-list" in first_page_text.lower():
        return "start_list"
    
    # Final Schedule: contains session/platform/weigh-in columns
    if "Session" in first_page_text and "Platform" in first_page_text and "Weigh-In" in first_page_text:
        return "final_schedule"

    # Full Results: owlcms header, multiple pages, "Age Group" sections
    if "Age Group" in first_page_text or "owlcms" in first_page_text:
        return "full_results"
    
    # Medal Schedule
    if "Medal Schedule" in first_page_text or "Medal" in first_page_text:
        return "medal_schedule"
    
    return "unknown"


# ──────────────────────────────────────────────────────────────────────
# Full Results parser (owlcms format)
# ──────────────────────────────────────────────────────────────────────

AGE_GROUP_HEADER = re.compile(
    r"Age Group\s+([A-Z0-9+]+)\s+([MW])\s*\n?\s*Weight Category\s+(\d+)",
    re.IGNORECASE
)


def parse_full_results(doc: fitz.Document) -> dict:
    """
    Parse owlcms Full Results PDF.
    
    Structure: each page contains one or more "Age Group" sections.
    Each section has a header line like:
        "Age Group JR W Weight Category 48"
    or split across two lines:
        "Age Group JR W\\nWeight Category 48"
    
    Data format per athlete (each value on a separate line):
        sn_rank  cj_rank  total_rank  lot
        Name (LAST, First)
        Team
        Wt. (bodyweight, 2 decimal)
        Age
        sn_1st  sn_2nd  sn_3rd
        cj_1st  cj_2nd  cj_3rd
        Total
        Score
    """
    athletes = []
    categories = []
    
    current_age_group = ""
    current_gender = ""
    current_weight_cat = ""
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        lines = text.split("\n")
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Check for Age Group header (may span 2 lines)
            combined = line
            if i + 1 < len(lines) and "Weight Category" not in line and "Weight Category" in lines[i + 1]:
                combined = line + " " + lines[i + 1].strip()
            
            m = AGE_GROUP_HEADER.search(combined)
            if m:
                current_age_group = m.group(1).upper()
                current_gender = m.group(2).upper()
                current_weight_cat = m.group(3)
                categories.append({
                    "age_group": current_age_group,
                    "gender": current_gender,
                    "weight_category": current_weight_cat,
                })
                # Skip past the header (and possibly the second line)
                i += 2 if "Weight Category" not in line else 1
                continue
            
            # Skip column header lines, page headers/footers
            if any(skip in line for skip in ["owlcms", "Page ", "provided by", "Body", "Score", 
                                              "QPoints", "QYouth", "1st", "2nd", "3rd", "Total",
                                              "Lot", "Name", "Team", "Wt.", "Age"]):
                i += 1
                continue
            
            # Try to parse athlete data
            # owlcms format: rank_sn, rank_cj, rank_total, lot, Name, Team, Wt, Age, sn1-3, cj1-3, Total, Score
            # Each value on a separate line. The lot is the 4th integer after the header.
            # Detect: 3 consecutive small integers (ranks 1-20), then a larger integer (lot 1-2000)
            if line.isdigit():
                # Check if this looks like the start of an athlete row (3 ranks + lot)
                vals: list[int] = []
                for j in range(i, min(i + 4, len(lines))):
                    v = lines[j].strip()
                    if v.isdigit():
                        vals.append(int(v))
                    elif v == "-":
                        vals.append(0)
                    else:
                        break
                
                if len(vals) >= 4:
                    # Pattern: rank1 rank2 rank3 lot
                    # Ranks are small (1-50), lot can be 1-2000. The first 3 values
                    # must be rank-like (<=50) to distinguish from attempt values
                    # (50-200+) that appear in athlete data after a missed skip.
                    lot = vals[3]
                    ranks_are_small = all(v <= 50 for v in vals[:3])
                    if ranks_are_small and 1 <= lot <= 2000:
                        # Move index to the lot position
                        athlete, consumed = parse_athlete_lines(lines, i + 3, lot,
                                                     current_age_group, current_gender, current_weight_cat)
                        if athlete:
                            athletes.append(athlete)
                        # Skip past ranks (3) + lot (1) + exactly the lines consumed
                        i = i + 4 + consumed
                        continue

                # DNF athlete with partial ranks: some ranks are DNF (text, skipped),
                # leaving only 1-2 numeric rank values before the lot. Detect: 1-2 small
                # digits followed by a larger digit (lot), followed by a name (comma or uppercase).
                if line.isdigit() and 1 <= int(line) <= 50:
                    # Check 1-rank pattern: rank, lot, name
                    if (i + 2 < len(lines) and lines[i + 1].strip().isdigit()
                            and 1 <= int(lines[i + 1].strip()) <= 2000
                            and int(lines[i + 1].strip()) > 50):
                        name_line = lines[i + 2].strip() if i + 3 < len(lines) else ""
                        if "," in name_line or (name_line.isupper() and len(name_line) > 3):
                            lot = int(lines[i + 1].strip())
                            athlete, consumed = parse_athlete_lines(lines, i + 1, lot,
                                                         current_age_group, current_gender, current_weight_cat)
                            if athlete:
                                athletes.append(athlete)
                            # Skip past rank (1) + lot (1) + exactly the lines consumed
                            i = i + 2 + consumed
                            continue

            # Handle DNF athletes: ALL attempts failed. In owlcms PDFs this appears as
            # either "DNF DNF DNF" on one line, or 3 consecutive "DNF" lines (one per rank).
            # After the DNF ranks, the next integer is the lot for the DNF athlete.
            is_dnf_block = (line == "DNF DNF DNF" or
                           (line == "DNF" and i + 2 < len(lines) and
                            lines[i + 1].strip() == "DNF" and lines[i + 2].strip() == "DNF"))
            if is_dnf_block:
                # Skip past the 3 DNF rank lines (either 1 combined or 3 separate)
                search_start = i + 1 if line == "DNF DNF DNF" else i + 3
                # Search for the next integer that looks like a lot (1-2000) within next 5 lines
                dnf_lot: int | None = None
                lot_idx: int | None = None
                for j in range(search_start, min(search_start + 5, len(lines))):
                    v = lines[j].strip()
                    if v.isdigit() and 1 <= int(v) <= 2000:
                        dnf_lot = int(v)
                        lot_idx = j
                        break

                if dnf_lot is not None and lot_idx is not None:
                    # Parse athlete starting from the lot position
                    athlete, consumed = parse_athlete_lines(lines, lot_idx, dnf_lot,
                                                 current_age_group, current_gender, current_weight_cat)
                    if athlete:
                        athletes.append(athlete)
                    # Skip past lot + exactly the lines consumed
                    i = lot_idx + 1 + consumed
                    continue
                # If no lot found, just skip past the DNF lines
                i = search_start
                continue

            # Handle DNF entries that represent an entire athlete (all attempts failed).
            # In owlcms PDFs, a DNF-only athlete appears as "DNF" or "DNF DNF" followed
            # by the lot number. These are NOT status markers for other athletes.
            if line == "DNF" or line == "DNF DNF":
                # Check if there's a lot number following within 5 lines
                lot_idx = None
                lot_val: int | None = None
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
                
                if lot_idx is not None and lot_val is not None:
                    # This IS a DNF athlete - parse it starting from the lot position
                    athlete, consumed = parse_athlete_lines(lines, lot_idx, lot_val,
                                                 current_age_group, current_gender, current_weight_cat)
                    if athlete:
                        athletes.append(athlete)
                    # Skip past lot + exactly the lines consumed
                    i = lot_idx + 1 + consumed
                else:
                    # No lot found - this is a status marker for another athlete
                    # Just skip it and continue
                    pass
                i += 1
                continue
            
            i += 1
    
    return {
        "pdf_type": "full_results",
        "total_athletes": len(athletes),
        "total_categories": len(categories),
        "categories": categories,
        "athletes": athletes,
    }


def parse_athlete_lines(lines: list, start_idx: int, lot: int, 
                        age_group: str, gender: str, weight_cat: str) -> tuple:
    """
    Parse athlete data starting from the lot number line.
    
    The owlcms PDF outputs each value on a separate line. After the lot number,
    the sequence is:
    Name (LAST, First), Team, Wt., Age,
    sn_1st, sn_2nd, sn_3rd, cj_1st, cj_2nd, cj_3rd, Total, Score
    
    Returns (athlete_dict | None, lines_consumed: int).
    lines_consumed is the number of lines past start_idx that were consumed,
    so callers can skip exactly that far without fragile fixed-line guesses.
    """
    vals: list[str] = []
    last_consumed_idx = start_idx  # tracks the last line index we consumed
    for j in range(start_idx + 1, min(start_idx + 20, len(lines))):
        val = lines[j].strip()
        if not val:
            continue
        # Stop at next athlete — but only if we see 3 consecutive rank-like numbers
        # (the start of the next athlete row). A single integer like "66" (a snatch
        # attempt) should NOT trigger a stop.
        if val.isdigit() and 1 <= int(val) <= 2000 and len(vals) >= 8:
            # Check if the next 3 lines are also small integers (ranks)
            # If so, this is the start of a new athlete row
            next_vals: list[int] = []
            for k in range(j, min(j + 4, len(lines))):
                v = lines[k].strip()
                if v.isdigit():
                    next_vals.append(int(v))
                elif v == "-":
                    next_vals.append(0)
                else:
                    break
            if len(next_vals) >= 4:
                break  # This is the next athlete (3 ranks + lot)
        if AGE_GROUP_HEADER.search(val):
            break
        if "Age Group" in val:
            break
        # Stop at DNF boundary lines — but only after we've collected enough
        # data for a valid athlete (at least a name). DNF as the first value
        # after the lot is an attempt value inside the athlete's data, not a
        # boundary between athletes.
        if len(vals) >= 3 and (val == "DNF" or val == "DNF DNF" or val == "DNF DNF DNF"):
            break
        vals.append(val)
        last_consumed_idx = j
    
    lines_consumed = last_consumed_idx - start_idx
    
    if len(vals) < 5:
        return None, lines_consumed
    
    # Find name (first value containing a comma)
    name = None
    name_idx = None
    for idx, v in enumerate(vals):
        if "," in v or (v.isupper() and len(v) > 3):
            name = v
            name_idx = idx
            break
    
    if name is None or name_idx is None:
        return None, lines_consumed
    
    remaining = vals[name_idx + 1:]
    
    if len(remaining) < 3:
        return None, lines_consumed
    
    # Team is the next value (may span multiple lines if no comma)
    team = remaining[0] if remaining else ""
    team_extra = []
    
    # Parse numeric values from the rest
    nums: list[float] = []
    for v in remaining[1:]:
        v_clean = v.replace("-", "").replace("DNF", "").strip()
        if v_clean:
            try:
                nums.append(float(v_clean))
            except ValueError:
                if not nums:
                    team_extra.append(v)
                # else: ignore
    
    team = (team + " " + " ".join(team_extra)).strip()
    
    athlete = {
        "lot": lot,
        "name": name,
        "team": team,
        "age_group": age_group,
        "gender": gender,
        "weight_category": weight_cat,
    }
    
    if len(nums) >= 2:
        athlete["bodyweight"] = nums[0]
        athlete["age"] = int(nums[1]) if nums[1] == int(nums[1]) else nums[1]
    else:
        return athlete, lines_consumed  # Insufficient data — return partial record
    
    # Snatch attempts (3 values after age)
    if len(nums) >= 5:
        athlete["snatch_attempts"] = [nums[2], nums[3], nums[4]]
        sn_attempts = [a for a in [nums[2], nums[3], nums[4]] if a > 0]
        athlete["snatch_best"] = max(sn_attempts) if sn_attempts else 0
    
    # C&J attempts (3 values after snatch)
    if len(nums) >= 8:
        athlete["cj_attempts"] = [nums[5], nums[6], nums[7]]
        cj_attempts = [a for a in [nums[5], nums[6], nums[7]] if a > 0]
        athlete["cj_best"] = max(cj_attempts) if cj_attempts else 0
    
    # Total and Score
    # In owlcms PDFs, "DNF" appears as text (not a number) on the total line when
    # an athlete didn't complete a valid total (failed to make >=1 snatch AND >=1 cj).
    # DNF means result of 0 — not "DNF" string, not None.
    if len(nums) >= 9:
        total = nums[8]
        athlete["total"] = total if total > 0 else 0
    else:
        # Total line was "DNF" (text, filtered out of nums) or missing.
        # Compute from best lifts if both exist; 0 if either is missing.
        sn = float(athlete.get("snatch_best", 0) or 0)  # type: ignore[arg-type]
        cj = float(athlete.get("cj_best", 0) or 0)  # type: ignore[arg-type]
        athlete["total"] = (sn + cj) if (sn and cj and sn > 0 and cj > 0) else 0
    if len(nums) >= 10:
        athlete["score"] = nums[9]
    
    return athlete, lines_consumed


# ──────────────────────────────────────────────────────────────────────
# Final Schedule parser
# ──────────────────────────────────────────────────────────────────────

PLATFORM_NAMES = {"WHITE", "BLUE", "RED", "GREEN", "YELLOW", "ORANGE"}

def parse_final_schedule(doc: fitz.Document) -> dict:
    """Parse owlcms Final Schedule PDF.
    
    Structure: each session has platform, weigh-in time, start time, gender,
    age group, weight category, qualifying totals, entry count.
    Each value is on a separate line.
    """
    sessions = []
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        lines = text.split("\n")
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip headers
            if any(skip in line for skip in ["owlcms", "Page ", "Age", "Weight", "Date",
                                              "Session", "Platform", "Weigh-In", "Start",
                                              "Gndr", "Group", "Category", "Entry Total",
                                              "Grp", "Ses"]):
                i += 1
                continue
            
            # Detect session start: platform name (WHITE/BLUE/RED)
            if line in PLATFORM_NAMES:
                # Try to parse: platform, weigh_in, start, gender, age_group, 
                # weight_cat, qualifying_totals, entry_count, entry_count
                vals: list[str] = []
                for j in range(i, min(i + 12, len(lines))):
                    v = lines[j].strip()
                    if not v:
                        continue
                    if v in ["owlcms", "Page "] or "Page " in v:
                        break
                    vals.append(v)
                
                if len(vals) >= 8:
                    # Full format: platform, weigh_in, start, gender, age_group,
                    # weight_category, qualifying_totals, entry_count
                    gender_ok = vals[3] in ("M", "F")
                    weight_cat_ok = any(c in vals[5] for c in "0123456789+BCD") and vals[5] not in PLATFORM_NAMES
                    entry_ok = vals[7].isdigit() if len(vals) > 7 else False
                    if gender_ok and weight_cat_ok and entry_ok:
                        session = {
                            "platform": vals[0],
                            "weigh_in": vals[1],
                            "start_time": vals[2],
                            "gender": vals[3],
                            "age_group": vals[4],
                            "weight_category": vals[5],
                            "qualifying_totals": vals[6],
                            "entry_count": int(vals[7]),
                        }
                        sessions.append(session)
                        i += len(vals)
                        continue

                # Condensed format: platform, weigh_in, start, gender, age_group
                # (no weight category, qualifying totals, or entry count)
                if len(vals) >= 5 and vals[3] in ("M", "F"):
                    if len(vals) >= 6 and vals[5] in PLATFORM_NAMES:
                        session = {
                            "platform": vals[0],
                            "weigh_in": vals[1],
                            "start_time": vals[2],
                            "gender": vals[3],
                            "age_group": vals[4],
                            "weight_category": "",
                            "qualifying_totals": "",
                            "entry_count": 0,
                        }
                        sessions.append(session)
                        i += 5
                        continue
                    if len(vals) == 5:
                        session = {
                            "platform": vals[0],
                            "weigh_in": vals[1],
                            "start_time": vals[2],
                            "gender": vals[3],
                            "age_group": vals[4],
                            "weight_category": "",
                            "qualifying_totals": "",
                            "entry_count": 0,
                        }
                        sessions.append(session)
                        i += 5
                        continue
            
            # WSO/ADAP sessions: no platform, no times. Format: age_group,
            # weight_category, qualifying_totals, entry_count (4 values).
            # These are adaptive/masters sessions grouped separately.
            # Detect: age_group keyword followed by a weight-category-like value
            WSO_AGE_GROUPS = {"ADAP", "WSO", "WSO U13", "WSO U17", "WSO JR", "WSO U25",
                              "WSO W35", "WSO W40", "WSO W45", "WSO W50", "WSO W55",
                              "WSO W60", "WSO M35", "WSO M40", "WSO M45", "WSO M50",
                              "WSO M60"}
            if line in WSO_AGE_GROUPS and i + 3 < len(lines):
                # Check if next 3 lines look like weight_cat, qualifying_totals, entry_count
                wc = lines[i + 1].strip() if i + 1 < len(lines) else ""
                qt = lines[i + 2].strip() if i + 2 < len(lines) else ""
                ec = lines[i + 3].strip() if i + 3 < len(lines) else ""
                wc_has_digits = any(c in wc for c in "0123456789+BCD") and wc not in PLATFORM_NAMES
                ec_is_digit = ec.isdigit()
                if wc_has_digits and ec_is_digit:
                    session = {
                        "platform": "",
                        "weigh_in": "",
                        "start_time": "",
                        "gender": "",
                        "age_group": line,
                        "weight_category": wc,
                        "qualifying_totals": qt,
                        "entry_count": int(ec),
                    }
                    sessions.append(session)
                    i += 4
                    continue
            
            i += 1
    
    return {
        "pdf_type": "final_schedule",
        "total_sessions": len(sessions),
        "sessions": sessions,
    }


# ──────────────────────────────────────────────────────────────────────
# Best Lifters parser
# ──────────────────────────────────────────────────────────────────────

def parse_best_lifters(doc: fitz.Document) -> dict:
    """
    Parse Best Lifters PDF.
    
    Structure: ranked list with columns:
    Age | Body | Group | Name | Team | Wt. | Age | Snatch | CJ | Total | QYouth/QPoints
    
    Separate sections for Women and Men.
    """
    text = doc[0].get_text() if len(doc) > 0 else ""
    
    # Extract athlete entries using regex on cleaned text
    # Pattern: DIVISION GENDER NAME(LAST, First) TEAM Wt Age Snatch CJ Total Score
    athlete_pattern = re.compile(
        r"(U\d{2}|JR|Open|ADAP|Senior|Masters|Military|University)\s+([MW])\s+"
        r"([A-Z][A-Z\s\-'']+,\s+[A-Za-z]+)\s+"  # Name: LAST, First
        r"(.+?)\s+"  # Team (non-greedy)
        r"(\d+\.\d+)\s+"  # Wt
        r"(\d+)\s+"  # Age
        r"(\d+)\s+"  # Snatch
        r"(\d+)\s+"  # CJ
        r"(\d+)\s+"  # Total
        r"(\d+\.?\d*)",  # Score
        re.MULTILINE
    )
    
    # Clean text: merge lines but keep division markers as line starts
    clean_text = re.sub(r'\n', ' ', text)
    
    athletes = []
    for m in athlete_pattern.finditer(clean_text):
        athletes.append({
            "division": m.group(1),
            "gender": m.group(2),
            "name": m.group(3).strip(),
            "team": m.group(4).strip(),
            "bodyweight": float(m.group(5)),
            "age": int(m.group(6)),
            "snatch": int(m.group(7)),
            "cj": int(m.group(8)),
            "total": int(m.group(9)),
            "score": float(m.group(10)),
        })
    
    return {
        "pdf_type": "best_lifters",
        "total_athletes": len(athletes),
        "athletes": athletes,
    }


# ──────────────────────────────────────────────────────────────────────
# Start List parser
# ──────────────────────────────────────────────────────────────────────

START_LIST_HEADER = re.compile(r"(?:Session|Date|Gndr|Group|Cat|Lot|Age|A/B/C|Name|Total|Team|Comps)", re.IGNORECASE)

def parse_start_list(doc: fitz.Document) -> dict:
    """
    Parse Start List PDF.
    
    Structure: similar to full results but pre-event. Columns:
    Lot | Name | Team | Total (entry total) | Age | Sessions
    """
    athletes = []
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        lines = text.split("\n")
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if START_LIST_HEADER.search(line) or "owlcms" in line or "Page " in line or "Start list" in line:
                i += 1
                continue
            
            if line.isdigit() and 1 <= int(line) <= 2000:
                lot = int(line)
                vals: list[str] = []
                for j in range(i + 1, min(i + 15, len(lines))):
                    val = lines[j].strip()
                    if not val:
                        continue
                    if val.isdigit() and 1 <= int(val) <= 2000 and len(vals) >= 3:
                        break
                    vals.append(val)
                
                name = None
                name_idx = None
                for idx, v in enumerate(vals):
                    if "," in v:
                        name = v
                        name_idx = idx
                        break
                
                if name and name_idx is not None and name_idx + 1 < len(vals):
                    team = vals[name_idx + 1] if name_idx + 1 < len(vals) else ""
                    nums: list[float] = []
                    for v in vals[name_idx + 2:]:
                        try:
                            nums.append(float(v))
                        except ValueError:
                            continue
                    
                    athlete = {
                        "lot": lot,
                        "name": name,
                        "team": team,
                    }
                    if nums:
                        athlete["entry_total"] = int(nums[0]) if nums and nums[0] == int(nums[0]) else nums[0]
                    if len(nums) >= 2:
                        athlete["age"] = int(nums[1]) if nums[1] == int(nums[1]) else nums[1]
                    
                    athletes.append(athlete)
            
            i += 1
    
    return {
        "pdf_type": "start_list",
        "total_athletes": len(athletes),
        "athletes": athletes,
    }


# ──────────────────────────────────────────────────────────────────────
# Google Drive integration
# ──────────────────────────────────────────────────────────────────────

def download_drive_file(file_id: str, output_path: str, account: str = "personal"):
    """Download a file from Google Drive via google_api.py helper."""
    import subprocess
    import os
    # Resolve google_api.py from productivity skill or fallback
    candidates = [
        os.path.expanduser("~/.hermes/skills/productivity/google-workspace/scripts/google_api.py"),
        os.path.expanduser("/opt/data/skills/productivity/google-workspace/scripts/google_api.py"),
    ]
    gapi_script = next((p for p in candidates if os.path.exists(p)), None)
    if not gapi_script:
        raise FileNotFoundError("google_api.py not found — install google-workspace skill")
    cmd = [
        "uv", "run", "--quiet",
        "--with", "google-api-python-client",
        "--with", "google-auth-oauthlib",
        "--with", "google-auth-httplib2",
        "python", gapi_script,
        "--account", account,
        "drive", "download", file_id,
        "--output", output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Drive download failed: {r.stderr[:500]}")
    return output_path


def list_drive_folder(folder_id: str, account: str = "personal"):
    """List PDF files in a Google Drive results folder."""
    import subprocess
    import json
    import os
    candidates = [
        os.path.expanduser("~/.hermes/skills/productivity/google-workspace/scripts/google_api.py"),
        os.path.expanduser("/opt/data/skills/productivity/google-workspace/scripts/google_api.py"),
    ]
    gapi_script = next((p for p in candidates if os.path.exists(p)), None)
    if not gapi_script:
        raise FileNotFoundError("google_api.py not found — install google-workspace skill")
    cmd = [
        "uv", "run", "--quiet",
        "--with", "google-api-python-client",
        "--with", "google-auth-oauthlib",
        "--with", "google-auth-httplib2",
        "python", gapi_script,
        "--account", account,
        "drive", "search", "Results",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"Drive search failed: {r.stderr[:500]}")
    files = json.loads(r.stdout) if r.stdout else []
    return [f for f in files if f.get("mimeType") == "application/pdf"]


# ──────────────────────────────────────────────────────────────────────
# File name classification (inside results folders)
# ──────────────────────────────────────────────────────────────────────

FILE_NAME_PATTERNS = {
    # Specific patterns first — they must be checked before the generic
    # full_results pattern, which matches any filename ending in "Results.pdf"
    "best_lifters": re.compile(r"Results\s*-\s*(.+?)\s*Best\s*Lifters\.pdf$", re.IGNORECASE),
    "teams": re.compile(r"Results\s*-\s*(.+?)\s*Teams\.pdf$", re.IGNORECASE),
    "medal_schedule": re.compile(r"Medal\s*Schedule\.pdf$", re.IGNORECASE),
    "registered_teams": re.compile(r"Registered\s*Teams\.pdf$", re.IGNORECASE),
    "glen_middleton": re.compile(r"Glen\s*Middleton.*\.pdf$", re.IGNORECASE),
    "start_list": re.compile(r"start.?list", re.IGNORECASE),
    "full_results": re.compile(r"Results\.pdf$", re.IGNORECASE),
}

DIVISION_CODES = {
    "U11": "Under 11", "U13": "Under 13", "U15": "Under 15 (14-15)",
    "U17": "Under 17 (16-17)", "U23": "Under 23", "U25": "Under 25",
    "JR": "Junior (U20)", "Open": "Senior/Open", "Masters": "Masters",
    "Military": "Military", "Military Masters": "Military Masters",
    "University": "University/Collegiate", "ADAP": "Adaptive",
}

def classify_file_name(filename: str) -> dict:
    """Classify a results folder file by its name."""
    for doc_type, pattern in FILE_NAME_PATTERNS.items():
        m = pattern.search(filename)
        if m:
            result = {"doc_type": doc_type, "division": None}
            if doc_type in ("best_lifters", "teams") and m.groups():
                div = m.group(1).strip()
                result["division"] = div
                result["division_name"] = DIVISION_CODES.get(div, div)
            return result
    return {"doc_type": "unknown", "division": None}


# ──────────────────────────────────────────────────────────────────────
# Main parser
# ──────────────────────────────────────────────────────────────────────

def parse_pdf(pdf_path: str) -> dict:
    """Parse a USAW results PDF and return structured data."""
    doc = fitz.open(pdf_path)
    
    pdf_type = detect_pdf_type(doc)
    file_info = classify_file_name(Path(pdf_path).name)
    
    if pdf_type == "full_results":
        result: dict = parse_full_results(doc)
    elif pdf_type == "best_lifters":
        result = parse_best_lifters(doc)
    elif pdf_type == "start_list":
        result = parse_start_list(doc)
    elif pdf_type == "medal_schedule":
        result = {"pdf_type": "medal_schedule", "note": "Medal schedule parsing not implemented"}
    elif pdf_type == "final_schedule":
        result = parse_final_schedule(doc)
    else:
        result = {"pdf_type": "unknown", "note": "Could not determine PDF type"}
    
    result["source_file"] = pdf_path
    result["file_name"] = Path(pdf_path).name
    result["file_classification"] = file_info
    result["page_count"] = len(doc)
    
    doc.close()
    return result


def format_summary(result: dict) -> str:
    """Format parsing result as human-readable summary."""
    lines = []
    lines.append(f"📄 {result.get('file_name', 'unknown')}")
    lines.append(f"   Type: {result.get('pdf_type', 'unknown')}")
    lines.append(f"   Pages: {result.get('page_count', '?')}")
    
    fc = result.get("file_classification", {})
    if fc.get("doc_type") != "unknown":
        lines.append(f"   File type: {fc['doc_type']}" + (f" ({fc.get('division', '')})" if fc.get("division") else ""))
    
    if result.get("total_athletes"):
        lines.append(f"   Athletes: {result['total_athletes']}")
    
    if result.get("total_categories"):
        lines.append(f"   Categories: {result['total_categories']}")
    
    athletes = result.get("athletes", [])
    if athletes:
        lines.append(f"\n   First {min(5, len(athletes))} athletes:")
        for a in athletes[:5]:
            name = a.get("name", "?")
            team = a.get("team", "?")[:25]
            total = a.get("total", "?")
            cat = a.get("weight_category", a.get("division", ""))
            ag = a.get("age_group", "")
            gender = a.get("gender", "")
            lines.append(f"     {ag} {gender} {cat}kg | {name} ({team}) | Total: {total}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Parse USAW results PDFs from Google Drive")
    parser.add_argument("file", nargs="?", help="Local PDF file to parse")
    parser.add_argument("--folder-id", help="Google Drive folder ID to download from")
    parser.add_argument("--drive-file-id", help="Specific Google Drive file ID to download and parse")
    parser.add_argument("--all", action="store_true", help="Parse all PDFs in the Drive folder")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--account", default="personal", help="Google account to use")
    parser.add_argument("--output-dir", default="/tmp/usaw_results", help="Directory for downloaded files")
    args = parser.parse_args()
    
    import os
    os.makedirs(args.output_dir, exist_ok=True)
    
    if args.file:
        result = parse_pdf(args.file)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(format_summary(result))
    
    elif args.drive_file_id:
        output_path = os.path.join(args.output_dir, f"{args.drive_file_id}.pdf")
        download_drive_file(args.drive_file_id, output_path, args.account)
        result = parse_pdf(output_path)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(format_summary(result))
    
    elif args.folder_id:
        files = list_drive_folder(args.folder_id, args.account)
        print(f"Found {len(files)} PDF files in folder\n", file=sys.stderr)
        
        if args.all:
            all_results = []
            for f in files:
                file_id = f["id"]
                file_name = f.get("name", file_id)
                output_path = os.path.join(args.output_dir, file_name)
                print(f"Downloading {file_name}...", file=sys.stderr)
                try:
                    download_drive_file(file_id, output_path, args.account)
                    result = parse_pdf(output_path)
                    all_results.append(result)
                    if not args.json:
                        print(format_summary(result))
                        print()
                except Exception as e:
                    print(f"  ❌ Failed: {e}", file=sys.stderr)
            
            if args.json:
                print(json.dumps(all_results, indent=2, default=str))
        else:
            for f in files:
                fc = classify_file_name(f.get("name", ""))
                print(f"  {f['name']:50s}  →  {fc['doc_type']}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()