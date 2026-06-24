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
    """Detect the type of USAW results PDF by examining its text."""
    first_page_text = doc[0].get_text() if len(doc) > 0 else ""
    
    # Best Lifters: typically 1 page, contains "Best Lifters" or ranked list
    if "Best Lifters" in first_page_text or ("Best" in first_page_text and "Women" in first_page_text and "Men" in first_page_text):
        return "best_lifters"
    
    # Start List: contains "Start list provided by" header
    if "Start list" in first_page_text or "start-list" in first_page_text.lower():
        return "start_list"
    
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
    
    current_age_group = None
    current_gender = None
    current_weight_cat = None
    
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
                vals = []
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
                    lot = vals[3]
                    if 1 <= lot <= 2000:
                        # Move index to the lot position
                        athlete = parse_athlete_lines(lines, i + 3, lot, 
                                                     current_age_group, current_gender, current_weight_cat)
                        if athlete:
                            athletes.append(athlete)
                        i += 4
                        continue
                # Also handle DNF entries: "DNF DNF DNF" then lot
                if line == "DNF" or (line.isdigit() and 1 <= int(line) <= 2000):
                    # Might be a standalone lot (after DNF ranks on same line)
                    # or a rank. Use the athlete_lines parser as fallback.
                    pass
            
            i += 1
    
    return {
        "pdf_type": "full_results",
        "total_athletes": len(athletes),
        "total_categories": len(categories),
        "categories": categories,
        "athletes": athletes,
    }


def parse_athlete_lines(lines: list, start_idx: int, lot: int, 
                        age_group: str, gender: str, weight_cat: str) -> dict | None:
    """
    Parse athlete data starting from the lot number line.
    
    The owlcms PDF outputs each value on a separate line. After the lot number,
    the sequence is:
    Name (LAST, First), Team, Wt., Age,
    sn_1st, sn_2nd, sn_3rd, cj_1st, cj_2nd, cj_3rd, Total, Score
    """
    vals = []
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
            next_vals = []
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
        vals.append(val)
    
    if len(vals) < 5:
        return None
    
    # Find name (first value containing a comma)
    name = None
    name_idx = None
    for idx, v in enumerate(vals):
        if "," in v or (v.isupper() and len(v) > 3):
            name = v
            name_idx = idx
            break
    
    if name is None:
        return None
    
    remaining = vals[name_idx + 1:]
    
    if len(remaining) < 3:
        return None
    
    # Team is the next value (may span multiple lines if no comma)
    team = remaining[0] if remaining else ""
    team_extra = []
    
    # Parse numeric values from the rest
    nums = []
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
        return athlete  # Insufficient data — return partial record
    
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
    if len(nums) >= 9:
        total = nums[8]
        athlete["total"] = total if total > 0 else "DNF"
    if len(nums) >= 10:
        athlete["score"] = nums[9]
    
    return athlete


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
                vals = []
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
                
                if name and name_idx + 1 < len(vals):
                    team = vals[name_idx + 1] if name_idx + 1 < len(vals) else ""
                    nums = []
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
    import subprocess, os
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
    import subprocess, json, os
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
    "full_results": re.compile(r"Results\.pdf$", re.IGNORECASE),
    "best_lifters": re.compile(r"Results\s*-\s*(.+?)\s*Best\s*Lifters\.pdf$", re.IGNORECASE),
    "teams": re.compile(r"Results\s*-\s*(.+?)\s*Teams\.pdf$", re.IGNORECASE),
    "medal_schedule": re.compile(r"Medal\s*Schedule\.pdf$", re.IGNORECASE),
    "registered_teams": re.compile(r"Registered\s*Teams\.pdf$", re.IGNORECASE),
    "glen_middleton": re.compile(r"Glen\s*Middleton.*\.pdf$", re.IGNORECASE),
    "start_list": re.compile(r"start.?list", re.IGNORECASE),
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
        result = parse_full_results(doc)
    elif pdf_type == "best_lifters":
        result = parse_best_lifters(doc)
    elif pdf_type == "start_list":
        result = parse_start_list(doc)
    elif pdf_type == "medal_schedule":
        result = {"pdf_type": "medal_schedule", "note": "Medal schedule parsing not implemented"}
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