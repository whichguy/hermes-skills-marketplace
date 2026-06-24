#!/usr/bin/env python3
"""
Test suite for usaw_event_extractor.py — validates fuzzy matching across
event pages from different years, layouts, and event types.

Tests cover:
  1. 2026 event pages (6 events: NCW, VWS1, Masters/Uni, VWS2, WZA, Finals)
  2. 2025 event pages (5 events: NCW, VWS1, VWS2, Masters, Finals) — prior year
  3. Required info types per event type (national vs minimal events)
  4. Sport80 URL pattern detection
  5. Inline metadata extraction (fees, milestones, dates, venue)
  6. Results folder link detection (Google Drive)
  7. TBA/TBD status detection (upcoming events)
  8. Edge cases (WZA minimal page, combined events, renamed events)

Usage:
  uv run --with beautifulsoup4 --with requests --with rapidfuzz \
    python scripts/test_extractor.py

  # Verbose (print details on failure)
  uv run --with beautifulsoup4 --with requests --with rapidfuzz \
    python scripts/test_extractor.py -v
"""

import json
import subprocess
import sys
import argparse
from collections import defaultdict

SCRIPT = "/opt/data/skills/sports/usaw-event-info/scripts/usaw_event_extractor.py"

# ──────────────────────────────────────────────────────────────────────
# Test definitions
# ──────────────────────────────────────────────────────────────────────

# Each test: (name, url, expected_fields)
# expected_fields: dict of field → assertion
#   "min_links": int — minimum total classified links
#   "zero_unclassified": bool — expect 0 unclassified links
#   "info_types": list — info types that MUST be present
#   "info_types_absent": list — info types that should NOT be present
#   "title_contains": str — title must contain this substring
#   "dates_contains": str — dates_raw must contain this substring
#   "venue_contains": str — venue_raw must contain this substring
#   "has_fees": bool — metadata.registration_fees must exist
#   "has_milestones": bool — metadata.schedule_milestones must exist
#   "has_results_link": bool — full_results info type must have a Google Drive URL

TESTS_2026 = [
    {
        "name": "2026 NCW (National Championships Week)",
        "url": "https://www.usaweightlifting.org/2026-national-championships",
        "expected": {
            "min_links": 25,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "preliminary_schedule",
                          "final_schedule", "start_list", "full_results", "tickets",
                          "live_stream", "hotel", "media_credentials", "event_policy",
                          "edit_entry", "photo_packages", "schedule_announcement",
                          "helpful_links", "training_sites"],
            "title_contains": "National Championships",
            "dates_contains": "2026",
            "venue_contains": "Ed Robson",
            "has_fees": True,
            "has_milestones": True,
            "has_results_link": True,
        },
    },
    {
        "name": "2026 VWS1 (VIRUS Weightlifting Series 1)",
        "url": "https://www.usaweightlifting.org/2026-virus-weightlifting-series-1",
        "expected": {
            "min_links": 15,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "preliminary_schedule",
                          "full_results", "tickets", "live_stream", "hotel",
                          "media_credentials", "start_list", "final_schedule",
                          "training_sites"],
            "title_contains": "VIRUS",
            "dates_contains": "Mar",
            "venue_contains": "Columbus",
            "has_milestones": True,
            "has_results_link": True,
        },
    },
    {
        "name": "2026 Masters/Uni (combined event)",
        "url": "https://www.usaweightlifting.org/2026-masters-national-championships-national-university-championships",
        "expected": {
            "min_links": 15,
            "zero_unclassified": True,
            "info_types": ["registration", "adaptive_registration", "qualifying_totals",
                          "preliminary_schedule", "final_schedule", "start_list",
                          "full_results", "tickets", "live_stream", "hotel",
                          "media_credentials", "wso_registration"],
            "title_contains": "Masters",
            "dates_contains": "Apr",
            "venue_contains": "Salt Palace",
            "has_fees": True,
            "has_milestones": True,
            "has_results_link": True,
        },
    },
    {
        "name": "2026 VWS2 (upcoming — schedules TBA)",
        "url": "https://www.usaweightlifting.org/2026-virus-weightlifting-series-2-championships",
        "expected": {
            "min_links": 12,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "tickets",
                          "live_stream", "hotel", "media_credentials"],
            "info_types_absent": ["full_results"],  # TBA — no Drive link yet
            "title_contains": "Series 2",
            "dates_contains": "Sep",
            "venue_contains": "Fort Worth",
            "has_fees": True,
            "has_milestones": True,
            "has_results_link": False,
        },
    },
    {
        "name": "2026 WZA (minimal event — different structure)",
        "url": "https://www.usaweightlifting.org/2026-usaw-x-gymreapers-wodapalooza-socal",
        "expected": {
            "min_links": 5,
            "zero_unclassified": True,
            "info_types": ["registration", "tickets"],
            "title_contains": "Wodapalooza",
            "dates_contains": "Sep",
            "has_fees": False,  # WZA has $100 flat fee, different pattern
        },
    },
    {
        "name": "2026 VIRUS Finals (upcoming — schedules TBA)",
        "url": "https://www.usaweightlifting.org/2026-virus-weightlifting-finals",
        "expected": {
            "min_links": 12,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "tickets",
                          "live_stream", "hotel", "media_credentials"],
            "title_contains": "Finals",
            "dates_contains": "Dec",
            "venue_contains": "Alameda",
            "has_fees": True,
            "has_milestones": True,
        },
    },
]

TESTS_2025 = [
    {
        "name": "2025 NCW (prior year — different URL slug)",
        "url": "https://www.usaweightlifting.org/2025-usaw-national-championships",
        "expected": {
            "min_links": 20,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "preliminary_schedule",
                          "final_schedule", "start_list", "full_results", "tickets",
                          "live_stream", "hotel"],
            "title_contains": "National Championships",
            "dates_contains": "2025",
            "venue_contains": "Ed Robson",
            "has_fees": False,  # 2025 page doesn't show fee amounts in HTML
            "has_results_link": True,
        },
    },
    {
        "name": "2025 VWS1 (prior year — different URL slug)",
        "url": "https://www.usaweightlifting.org/2025-north-american-open-series-1",
        "expected": {
            "min_links": 12,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "preliminary_schedule",
                          "full_results", "tickets", "live_stream"],
            "title_contains": "Weightlifting Series 1",
            "dates_contains": "2025",
            "has_results_link": True,
        },
    },
    {
        "name": "2025 VWS2 (prior year)",
        "url": "https://www.usaweightlifting.org/2025-north-american-open-series-2",
        "expected": {
            "min_links": 15,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "preliminary_schedule",
                          "final_schedule", "start_list", "full_results", "tickets",
                          "live_stream", "hotel"],
            "title_contains": "Series 2",
            "dates_contains": "Aug",
            "has_fees": True,
            "has_results_link": True,
        },
    },
    {
        "name": "2025 Masters Nationals (prior year)",
        "url": "https://www.usaweightlifting.org/2025-masters-national-championships",
        "expected": {
            "min_links": 15,
            "zero_unclassified": True,
            "info_types": ["registration", "adaptive_registration", "qualifying_totals",
                          "preliminary_schedule", "full_results", "tickets",
                          "live_stream", "hotel"],
            "title_contains": "Masters",
            "dates_contains": "Apr",
            "has_results_link": True,
        },
    },
    {
        "name": "2025 VIRUS Finals / UMWF (prior year — combined naming)",
        "url": "https://www.usaweightlifting.org/2025-north-american-open-finals",
        "expected": {
            "min_links": 15,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "preliminary_schedule",
                          "full_results", "tickets", "live_stream"],
            "title_contains": "Finals",
            "dates_contains": "Dec",
            "has_results_link": True,
        },
    },
]


# ──────────────────────────────────────────────────────────────────────
# Test runner
# ──────────────────────────────────────────────────────────────────────

def run_extractor(url: str) -> dict:
    """Run the extractor and return parsed JSON."""
    cmd = [
        "uv", "run", "--with", "beautifulsoup4", "--with", "requests", "--with", "rapidfuzz",
        "python", SCRIPT, url, "--json",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"Extractor failed: {r.stderr[:500]}")
    return json.loads(r.stdout)


def check_test(name: str, url: str, expected: dict, result: dict, verbose: bool = False) -> tuple[bool, list[str]]:
    """Run assertions. Returns (passed, list of failure messages)."""
    failures = []
    info_types = set(result.get("info_by_type", {}).keys())
    
    # min_links
    min_links = expected.get("min_links")
    if min_links and result["classified_count"] < min_links:
        failures.append(f"min_links: expected >={min_links}, got {result['classified_count']}")
    
    # zero_unclassified
    if expected.get("zero_unclassified") and result["unclassified_count"] > 0:
        failures.append(f"zero_unclassified: got {result['unclassified_count']} unclassified")
        if verbose:
            for item in result["unclassified"]:
                failures.append(f"  → {item.get('link_text', '')}: {item.get('url', '')[:80]}")
    
    # info_types present
    for itype in expected.get("info_types", []):
        if itype not in info_types:
            failures.append(f"missing info_type: {itype}")
    
    # info_types absent
    for itype in expected.get("info_types_absent", []):
        if itype in info_types:
            failures.append(f"unexpected info_type present: {itype}")
    
    # title_contains
    tc = expected.get("title_contains")
    if tc and tc.lower() not in result.get("title", "").lower():
        failures.append(f"title_contains: '{tc}' not in '{result.get('title', '')}'")
    
    # dates_contains
    dc = expected.get("dates_contains")
    if dc and dc.lower() not in result.get("dates_raw", "").lower():
        failures.append(f"dates_contains: '{dc}' not in '{result.get('dates_raw', '')}'")
    
    # venue_contains
    vc = expected.get("venue_contains")
    if vc and vc.lower() not in result.get("venue_raw", "").lower():
        failures.append(f"venue_contains: '{vc}' not in '{result.get('venue_raw', '')}'")
    
    # has_fees
    if expected.get("has_fees") and not result.get("metadata", {}).get("registration_fees"):
        failures.append("has_fees: no registration_fees in metadata")
    
    # has_milestones
    if expected.get("has_milestones") and not result.get("metadata", {}).get("schedule_milestones"):
        failures.append("has_milestones: no schedule_milestones in metadata")
    
    # has_results_link
    if expected.get("has_results_link"):
        fr = result.get("info_by_type", {}).get("full_results", [])
        if not any("drive.google.com" in item.get("url", "") for item in fr):
            failures.append("has_results_link: no Google Drive link in full_results")
    
    if expected.get("has_results_link") is False:
        fr = result.get("info_by_type", {}).get("full_results", [])
        drive_links = [item for item in fr if "drive.google.com" in item.get("url", "")]
        if drive_links:
            failures.append(f"has_results_link=False: found Google Drive link(s): {len(drive_links)}")
    
    return (len(failures) == 0, failures)


def main():
    parser = argparse.ArgumentParser(description="Test USAW event extractor")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show details on failure")
    parser.add_argument("--year", choices=["2026", "2025", "all"], default="all", help="Which year's tests to run")
    args = parser.parse_args()
    
    all_tests = []
    if args.year in ("2026", "all"):
        all_tests.extend(TESTS_2026)
    if args.year in ("2025", "all"):
        all_tests.extend(TESTS_2025)
    
    passed = 0
    failed = 0

    print(f"🧪 USAW Event Extractor Test Suite")
    print(f"   {len(all_tests)} tests ({args.year})\n")
    
    for test in all_tests:
        name = test["name"]
        url = test["url"]
        expected = test["expected"]
        
        try:
            result = run_extractor(url)
        except Exception as e:
            print(f"❌ {name}")
            print(f"   ERROR: {e}")
            failed += 1
            continue
        
        ok, failures = check_test(name, url, expected, result, args.verbose)
        
        if ok:
            print(f"✅ {name}")
            print(f"   {result['classified_count']} links | {result['title'][:40]} | {result.get('dates_raw', '')[:25]}")
            passed += 1
        else:
            print(f"❌ {name}")
            print(f"   {result['classified_count']} links | {result['title'][:40]}")
            for f in failures:
                print(f"   ⚠️  {f}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed ({passed+failed} total)")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("🎉 All tests passed!")


if __name__ == "__main__":
    main()