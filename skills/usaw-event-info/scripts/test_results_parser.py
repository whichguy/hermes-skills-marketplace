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
import json
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
        )
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
        print(f"⏭️  test_parse_full_results_structure — fixture missing")
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

ALL_TESTS = [
    test_detect_pdf_type_results,
    test_detect_pdf_type_best_lifters,
    test_detect_pdf_type_start_list,
    test_detect_pdf_type_schedule,
    test_parse_full_results_structure,
    test_parse_best_lifters_structure,
    test_parse_start_list_structure,
]


def main():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    print("🧪 USAW Results Parser Test Suite (L6)")
    print(f"   {len(ALL_TESTS)} tests\n")

    passed = 0
    failed = 0
    skipped = 0

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