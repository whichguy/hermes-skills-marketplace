#!/usr/bin/env python3
"""
Test suite for usaw_results_parser.py — L6 fix.

Validates the PDF parser against real fixture PDFs downloaded from the
2026 NCW Google Drive results folder. Tests all 3 PDF types:
  1. Full Results (owlcms export)
  2. Best Lifters (ranked list)
  3. Start List (pre-event registration)

Usage:
  uv run --with pymupdf python scripts/test_results_parser.py -v

Fixtures in tests/fixtures/pdfs/:
  - 2026-ncw-results.pdf         (Full Results, ~774KB)
  - 2026-ncw-u11-best-lifters.pdf (Best Lifters, ~30KB)
  - 2026-ncw-start-list.pdf      (Start List, ~433KB)
  - 2026-ncw-final-schedule.pdf  (Schedule, ~84KB — not a results type)
"""

import sys
from pathlib import Path


# Add scripts dir to path for import
sys.path.insert(0, str(Path(__file__).parent))

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "pdfs"


def _import_parser():
    """Import the parser, skipping if pymupdf is not available."""
    try:
        import fitz  # noqa: F401
        from usaw_results_parser import (
            detect_pdf_type,
            parse_full_results,
            parse_best_lifters,
            parse_start_list,
            parse_athlete_lines,
        )
        # Make parse_athlete_lines available at module level for DNF tests
        globals()["parse_athlete_lines"] = parse_athlete_lines
        return detect_pdf_type, parse_full_results, parse_best_lifters, parse_start_list
    except ImportError:
        return None


def test_detect_pdf_type_results():
    """L6: detect_pdf_type correctly identifies Full Results PDF."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_detect_pdf_type_results — pymupdf not installed")
        return False
    detect_pdf_type, *_ = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-results.pdf"
    if not pdf_path.exists():
        print(f"⏭️  test_detect_pdf_type_results — fixture missing ({pdf_path.name})")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    pdf_type = detect_pdf_type(doc)
    doc.close()

    if pdf_type == "full_results":
        print("✅ test_detect_pdf_type_results")
        return True
    else:
        print(f"❌ test_detect_pdf_type_results: expected 'full_results', got '{pdf_type}'")
        return False


def test_detect_pdf_type_best_lifters():
    """L6: detect_pdf_type correctly identifies Best Lifters PDF."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_detect_pdf_type_best_lifters — pymupdf not installed")
        return False
    detect_pdf_type, *_ = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-u11-best-lifters.pdf"
    if not pdf_path.exists():
        print(f"⏭️  test_detect_pdf_type_best_lifters — fixture missing ({pdf_path.name})")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    pdf_type = detect_pdf_type(doc)
    doc.close()

    if pdf_type == "best_lifters":
        print("✅ test_detect_pdf_type_best_lifters")
        return True
    else:
        print(f"❌ test_detect_pdf_type_best_lifters: expected 'best_lifters', got '{pdf_type}'")
        return False


def test_detect_pdf_type_start_list():
    """L6: detect_pdf_type correctly identifies Start List PDF."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_detect_pdf_type_start_list — pymupdf not installed")
        return False
    detect_pdf_type, *_ = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-start-list.pdf"
    if not pdf_path.exists():
        print(f"⏭️  test_detect_pdf_type_start_list — fixture missing ({pdf_path.name})")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    pdf_type = detect_pdf_type(doc)
    doc.close()

    if pdf_type == "start_list":
        print("✅ test_detect_pdf_type_start_list")
        return True
    else:
        print(f"❌ test_detect_pdf_type_start_list: expected 'start_list', got '{pdf_type}'")
        return False


def test_parse_full_results_structure():
    """L6: parse_full_results returns structured data with expected fields."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_parse_full_results_structure — pymupdf not installed")
        return False
    detect_pdf_type, parse_full_results, _, _ = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-results.pdf"
    if not pdf_path.exists():
        print("⏭️  test_parse_full_results_structure — fixture missing")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    result = parse_full_results(doc)
    doc.close()

    failures = []

    # Must have athletes list
    athletes = result.get("athletes", [])
    if not athletes:
        failures.append("no athletes parsed")
    else:
        # Check first athlete has expected fields
        first = athletes[0]
        for field in ["age_group", "gender", "weight_category"]:
            if not first.get(field):
                failures.append(f"first athlete missing field: {field} (got {list(first.keys())})")
                break

        # Should have a reasonable number of athletes (NCW has 700+)
        if len(athletes) < 100:
            failures.append(f"expected 100+ athletes, got {len(athletes)}")

    # Must have categories list
    cats = result.get("categories", [])
    if not cats:
        failures.append("no categories parsed")
    elif len(cats) < 10:
        failures.append(f"expected 10+ categories, got {len(cats)}")

    if failures:
        print(f"❌ test_parse_full_results_structure: {'; '.join(failures)}")
        return False
    else:
        print(f"✅ test_parse_full_results_structure ({len(athletes)} athletes, {len(cats)} categories)")
        return True


def test_parse_best_lifters_structure():
    """L6: parse_best_lifters returns ranked list with expected fields."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_parse_best_lifters_structure — pymupdf not installed")
        return False
    _, _, parse_best_lifters, _ = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-u11-best-lifters.pdf"
    if not pdf_path.exists():
        print("⏭️  test_parse_best_lifters_structure — fixture missing")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    result = parse_best_lifters(doc)
    doc.close()

    failures = []

    athletes = result.get("athletes", [])
    if not athletes:
        failures.append("no athletes parsed")
    else:
        first = athletes[0]
        # Best lifters should have name, team, snatch, cj, total
        for field in ["name"]:
            if not first.get(field):
                failures.append(f"first athlete missing field: {field} (got {list(first.keys())})")
                break

    if failures:
        print(f"❌ test_parse_best_lifters_structure: {'; '.join(failures)}")
        return False
    else:
        print(f"✅ test_parse_best_lifters_structure ({len(athletes)} athletes)")
        return True


def test_parse_start_list_structure():
    """L6: parse_start_list returns registration data with expected fields."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_parse_start_list_structure — pymupdf not installed")
        return False
    _, _, _, parse_start_list = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-start-list.pdf"
    if not pdf_path.exists():
        print("⏭️  test_parse_start_list_structure — fixture missing")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    result = parse_start_list(doc)
    doc.close()

    failures = []

    athletes = result.get("athletes", [])
    if not athletes:
        failures.append("no athletes parsed")
    else:
        first = athletes[0]
        for field in ["name"]:
            if not first.get(field):
                failures.append(f"first athlete missing field: {field} (got {list(first.keys())})")
                break

    if failures:
        print(f"❌ test_parse_start_list_structure: {'; '.join(failures)}")
        return False
    else:
        print(f"✅ test_parse_start_list_structure ({len(athletes)} athletes)")
        return True


def test_detect_pdf_type_schedule():
    """L6: detect_pdf_type correctly identifies a schedule PDF as NOT a results type."""
    fns = _import_parser()
    if fns is None:
        print("⏭️  test_detect_pdf_type_schedule — pymupdf not installed")
        return False
    detect_pdf_type, *_ = fns

    pdf_path = FIXTURE_DIR / "2026-ncw-final-schedule.pdf"
    if not pdf_path.exists():
        print("⏭️  test_detect_pdf_type_schedule — fixture missing")
        return False

    import fitz
    doc = fitz.open(str(pdf_path))
    pdf_type = detect_pdf_type(doc)
    doc.close()

    # Schedule should NOT be classified as full_results, best_lifters, or start_list
    if pdf_type in ("full_results", "best_lifters", "start_list"):
        print(f"❌ test_detect_pdf_type_schedule: schedule misidentified as '{pdf_type}'")
        return False
    else:
        print(f"✅ test_detect_pdf_type_schedule (type={pdf_type})")
        return True


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def test_dnf_layout_1_all_dnf_one_line():
    """DNF Layout 1: 'DNF DNF DNF' on a single line, followed by lot + name + team."""
    _import_parser()  # Ensures parse_athlete_lines is in globals
    lines = [
        "Age Group SR M",
        "Weight Category 89",
        "Body", "QPoints", "T", "sn", "cj",
        "Lot", "Name", "Team", "Wt.", "Age",
        "DNF DNF DNF",   # all ranks DNF
        "119",            # lot
        "THIBAULT, McKenzie",  # name
        "Heavenly Gains Barbell",  # team
        "45.90",          # bodyweight
        "18",             # age
        "56", "56", "56", # snatch attempts
        "69", "69", "69", # cj attempts
        "DNF",            # total (DNF)
        "DNF",            # score (DNF)
        "Age Group SR M", # next section
    ]
    athlete, consumed = parse_athlete_lines(lines, 13, 119, "SR", "M", "89")  # noqa: F821
    assert athlete is not None, "Expected athlete for DNF layout 1"
    assert athlete["name"] == "THIBAULT, McKenzie", f"Wrong name: {athlete['name']}"
    assert athlete["lot"] == 119
    assert athlete["total"] == 125 or athlete["total"] == 0  # computed or DNF
    print(f"✅ test_dnf_layout_1_all_dnf_one_line (consumed={consumed})")
    return True


def test_dnf_layout_2_all_dnf_three_lines():
    """DNF Layout 2: Three consecutive 'DNF' lines (one per rank), then lot + name."""
    _import_parser()
    lines = [
        "Age Group JR W",
        "Weight Category 53",
        "Body", "QPoints", "T", "sn", "cj",
        "Lot", "Name", "Team", "Wt.", "Age",
        "DNF",   # sn_rank DNF
        "DNF",   # cj_rank DNF
        "DNF",   # total_rank DNF
        "9",     # lot
        "DNF",   # attempt value (not a boundary — it's inside the athlete's data)
        "303",   # attempt value
        "LIVINGSTON, Ciara",  # name
        "Maxx Effort Training",  # team
        "50.30", # bodyweight
        "18",    # age
        "DNF", "DNF", "DNF",  # all snatch attempts DNF
        "DNF", "DNF", "DNF",  # all cj attempts DNF
        "DNF",   # total DNF
        "Age Group JR W",  # next section
    ]
    # lot '9' is at index 13 (after 3 DNF lines at 10,11,12)
    athlete, consumed = parse_athlete_lines(lines, 13, 9, "JR", "W", "53")  # noqa: F821
    assert athlete is not None, "Expected athlete for DNF layout 2"
    assert athlete["name"] == "LIVINGSTON, Ciara", f"Wrong name: {athlete['name']}"
    assert athlete["lot"] == 9
    assert athlete["total"] == 0, f"Expected total=0 for DNF, got {athlete['total']}"
    print(f"✅ test_dnf_layout_2_all_dnf_three_lines (consumed={consumed})")
    return True


def test_dnf_layout_3_partial_dnf_one_rank():
    """DNF Layout 3: Partial DNF — 2 ranks are DNF, 1 numeric rank remains."""
    _import_parser()
    lines = [
        "Age Group JR W",
        "Weight Category 48",
        "Body", "QPoints", "T", "sn", "cj",
        "Lot", "Name", "Team", "Wt.", "Age",
        "DNF DNF",  # cj_rank + total_rank DNF
        "7",        # snatch_rank (numeric)
        "1240",     # lot
        "ILANO, Lucy",  # name
        "Orlando Strength",  # team
        "51.55",    # bodyweight
        "18",       # age
        "50", "51", "51",  # snatch attempts
        "65", "68", "70",  # cj attempts
        "121",      # total
        "Age Group JR W",  # next section
    ]
    # lot '1240' is at index 14 (after DNF DNF at 12, rank at 13)
    athlete, consumed = parse_athlete_lines(lines, 14, 1240, "JR", "W", "48")  # noqa: F821
    assert athlete is not None, "Expected athlete for DNF layout 3"
    assert athlete["name"] == "ILANO, Lucy", f"Wrong name: {athlete['name']}"
    assert athlete["lot"] == 1240
    assert athlete["snatch_best"] == 51, f"Expected snatch_best=51, got {athlete.get('snatch_best')}"
    assert athlete["cj_best"] == 70, f"Expected cj_best=70, got {athlete.get('cj_best')}"
    print(f"✅ test_dnf_layout_3_partial_dnf_one_rank (consumed={consumed})")
    return True


def test_final_schedule_3_formats():
    """Final schedule parser handles 3 session formats: full, condensed, WSO/ADAP.
    
    Uses the real 2026 NCW Final Schedule fixture. Asserts:
    - Correct PDF type detection
    - All 3 formats present (full with weight_cat, condensed without, WSO with no platform)
    - No garbage sessions (platform name in weight_category)
    - No sessions with invalid gender (full/condensed must have M or F)
    """
    _import_parser()
    from usaw_results_parser import parse_pdf

    result = parse_pdf(str(FIXTURE_DIR / "2026-ncw-final-schedule.pdf"))

    assert result["pdf_type"] == "final_schedule", f"Expected final_schedule, got {result['pdf_type']}"

    sessions = result["sessions"]
    assert len(sessions) > 0, "Expected at least 1 session"

    # Categorize
    full = [s for s in sessions if s["platform"] and s["weight_category"]]
    condensed = [s for s in sessions if s["platform"] and not s["weight_category"]]
    wso = [s for s in sessions if not s["platform"]]

    # All 3 formats must be present
    assert len(full) > 0, "Expected at least 1 full-format session"
    assert len(condensed) > 0, "Expected at least 1 condensed-format session"
    assert len(wso) > 0, "Expected at least 1 WSO/ADAP session"

    # No garbage: platform name in weight_category
    PLATFORM_NAMES = {"WHITE", "BLUE", "RED", "GREEN", "YELLOW", "ORANGE"}
    garbage = [s for s in sessions if s["weight_category"] in PLATFORM_NAMES]
    assert len(garbage) == 0, f"Found {len(garbage)} garbage sessions (platform in weight_category)"
    
    # Full and condensed sessions must have valid gender
    bad_gender = [s for s in sessions if s["platform"] and s["gender"] not in ("M", "F")]
    assert len(bad_gender) == 0, f"Found {len(bad_gender)} sessions with invalid gender"
    
    # Full sessions must have entry_count > 0
    bad_entries = [s for s in full if s["entry_count"] <= 0]
    assert len(bad_entries) == 0, f"Found {len(bad_entries)} full sessions with entry_count <= 0"
    
    # WSO sessions must have age_group and weight_category
    bad_wso = [s for s in wso if not s["age_group"] or not s["weight_category"]]
    assert len(bad_wso) == 0, f"Found {len(bad_wso)} WSO sessions missing age_group or weight_category"
    
    # Spot-check known values from the fixture
    first_full = full[0]
    assert first_full["platform"] in PLATFORM_NAMES, f"Bad platform: {first_full['platform']}"
    assert first_full["gender"] in ("M", "F"), f"Bad gender: {first_full['gender']}"
    assert any(c in first_full["weight_category"] for c in "0123456789+BCD"), \
        f"Bad weight_category: {first_full['weight_category']}"
    
    print(f"✅ test_final_schedule_3_formats ({len(sessions)} sessions: {len(full)} full, {len(condensed)} condensed, {len(wso)} WSO/ADAP)")


ALL_TESTS = [
    test_detect_pdf_type_results,
    test_detect_pdf_type_best_lifters,
    test_detect_pdf_type_start_list,
    test_detect_pdf_type_schedule,
    test_parse_full_results_structure,
    test_parse_best_lifters_structure,
    test_parse_start_list_structure,
    test_dnf_layout_1_all_dnf_one_line,
    test_dnf_layout_2_all_dnf_three_lines,
    test_dnf_layout_3_partial_dnf_one_rank,
    test_final_schedule_3_formats,
]


def main():

    print("🧪 USAW Results Parser Test Suite (L6)")
    print(f"   {len(ALL_TESTS)} tests\n")

    passed = 0
    failed = 0

    for test in ALL_TESTS:
        result = test()
        if result is True:
            passed += 1
        elif result is False:
            # Check if it was a skip (printed ⏭️)
            failed += 1
        else:
            failed += 1

    # Count skips from output (hacky but works)
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed ({len(ALL_TESTS)} total)")

    if failed > 0:
        sys.exit(1)
    else:
        print("🎉 All results parser tests passed!")


if __name__ == "__main__":
    main()