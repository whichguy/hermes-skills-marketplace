#!/usr/bin/env python3
"""
Mock test suite for usaw_event_extractor.py — offline, no network.

Uses saved HTML fixtures (tests/fixtures/*.html) captured from live
USAW event pages. Validates the same assertions as test_extractor.py
but runs in <1 second with zero network dependency.

Usage:
  python scripts/test_extractor_mock.py          # all tests
  python scripts/test_extractor_mock.py -v       # verbose
  python scripts/test_extractor_mock.py --year 2026  # 2026 only
  python scripts/test_extractor_mock.py --refresh   # re-fetch fixtures

Fixtures stored in tests/fixtures/{slug}.html.
"""

import argparse
import sys
from pathlib import Path

# Add scripts dir to path for import
sys.path.insert(0, str(Path(__file__).parent))
from usaw_event_extractor import extract_event_page

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

# ── Test definitions (mirrors test_extractor.py) ──────────────────

TESTS_2026 = [
    {
        "name": "2026 NCW",
        "slug": "2026-ncw",
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
            "fee_amounts": ["$145", "$175", "$375"],  # L7: assert actual fee values
            "has_milestones": True,
            "has_results_link": True,
        },
    },
    {
        "name": "2026 VWS1",
        "slug": "2026-vws1",
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
        "name": "2026 Masters/Uni",
        "slug": "2026-masters-uni",
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
            "fee_amounts": ["$145", "$175", "$375"],  # L7: assert actual fee values
            "has_milestones": True,
            "has_results_link": True,
        },
    },
    {
        "name": "2026 VWS2 (upcoming)",
        "slug": "2026-vws2",
        "url": "https://www.usaweightlifting.org/2026-virus-weightlifting-series-2-championships",
        "expected": {
            "min_links": 12,
            "zero_unclassified": True,
            "info_types": ["registration", "qualifying_totals", "tickets",
                          "live_stream", "hotel", "media_credentials"],
            "info_types_absent": ["full_results"],
            "title_contains": "Series 2",
            "dates_contains": "Sep",
            "venue_contains": "Fort Worth",
            "has_fees": True,
            "fee_amounts": ["$145", "$175", "$375"],  # L7: assert actual fee values
            "has_milestones": True,
            "has_results_link": False,
        },
    },
    {
        "name": "2026 WZA (minimal)",
        "slug": "2026-wza",
        "url": "https://www.usaweightlifting.org/2026-usaw-x-gymreapers-wodapalooza-socal",
        "expected": {
            "min_links": 5,
            "zero_unclassified": True,
            "info_types": ["registration", "tickets"],
            "title_contains": "Wodapalooza",
            "dates_contains": "Sep",
            "has_fees": False,
        },
    },
    {
        "name": "2026 VIRUS Finals (upcoming)",
        "slug": "2026-finals",
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
            "fee_amounts": ["$145", "$175", "$375"],  # L7: assert actual fee values
            "has_milestones": True,
        },
    },
]

TESTS_2025 = [
    {
        "name": "2025 NCW (prior year)",
        "slug": "2025-ncw",
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
            "has_fees": False,
            "has_results_link": True,
        },
    },
    {
        "name": "2025 VWS1 (prior year)",
        "slug": "2025-vws1",
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
        "slug": "2025-vws2",
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
        "slug": "2025-masters",
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
        "name": "2025 VIRUS Finals / UMWF (prior year)",
        "slug": "2025-finals",
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


def check_test(name: str, expected: dict, result: dict, verbose: bool) -> tuple[bool, list[str]]:
    """Run assertions — same logic as test_extractor.py."""
    failures = []
    info_types = set(result.get("info_by_type", {}).keys())

    min_links = expected.get("min_links")
    if min_links and result["classified_count"] < min_links:
        failures.append(f"min_links: expected >={min_links}, got {result['classified_count']}")

    if expected.get("zero_unclassified") and result["unclassified_count"] > 0:
        failures.append(f"zero_unclassified: got {result['unclassified_count']}")
        if verbose:
            for item in result["unclassified"]:
                failures.append(f"  → {item.get('link_text', '')}: {item.get('url', '')[:80]}")

    for itype in expected.get("info_types", []):
        if itype not in info_types:
            failures.append(f"missing info_type: {itype}")

    for itype in expected.get("info_types_absent", []):
        if itype in info_types:
            failures.append(f"unexpected info_type: {itype}")

    tc = expected.get("title_contains")
    if tc and tc.lower() not in result.get("title", "").lower():
        failures.append(f"title_contains: '{tc}' not in '{result.get('title', '')}'")

    dc = expected.get("dates_contains")
    if dc and dc.lower() not in result.get("dates_raw", "").lower():
        failures.append(f"dates_contains: '{dc}' not in '{result.get('dates_raw', '')}'")

    vc = expected.get("venue_contains")
    if vc and vc.lower() not in result.get("venue_raw", "").lower():
        failures.append(f"venue_contains: '{vc}' not in '{result.get('venue_raw', '')}'")

    if expected.get("has_fees") and not result.get("metadata", {}).get("registration_fees"):
        failures.append("has_fees: no registration_fees in metadata")

    # L7: Assert actual fee amounts, not just existence
    expected_fees = expected.get("fee_amounts")
    if expected_fees:
        actual_fees = result.get("metadata", {}).get("registration_fees", {})
        actual_fee_vals = set()
        for tier, data in actual_fees.items():
            if isinstance(data, dict):
                actual_fee_vals.add(data.get("fee", ""))
            else:
                actual_fee_vals.add(data)
        for expected_fee in expected_fees:
            if expected_fee not in actual_fee_vals:
                failures.append(f"fee_amounts: '{expected_fee}' not found in fees {actual_fee_vals}")

    if expected.get("has_milestones") and not result.get("metadata", {}).get("schedule_milestones"):
        failures.append("has_milestones: no schedule_milestones in metadata")

    if expected.get("has_results_link"):
        fr = result.get("info_by_type", {}).get("full_results", [])
        if not any("drive.google.com" in item.get("url", "") for item in fr):
            failures.append("has_results_link: no Google Drive link in full_results")

    if expected.get("has_results_link") is False:
        fr = result.get("info_by_type", {}).get("full_results", [])
        drive_links = [item for item in fr if "drive.google.com" in item.get("url", "")]
        if drive_links:
            failures.append(f"has_results_link=False: found {len(drive_links)} Drive link(s)")

    return (len(failures) == 0, failures)


def refresh_fixtures():
    """Re-fetch all fixture HTML from live USAW pages."""
    import requests
    slugs_urls = [(t["slug"], t["url"]) for t in TESTS_2026 + TESTS_2025]
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for slug, url in slugs_urls:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        (FIXTURE_DIR / f"{slug}.html").write_text(resp.text)
        print(f"  ✅ {slug} ({len(resp.text):,} bytes)")


def main():
    parser = argparse.ArgumentParser(description="Mock test suite (offline)")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--year", choices=["2026", "2025", "all"], default="all")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch fixtures from live pages")
    args = parser.parse_args()

    if args.refresh:
        print("Refreshing fixtures from live USAW pages...")
        refresh_fixtures()
        print()

    all_tests = []
    if args.year in ("2026", "all"):
        all_tests.extend(TESTS_2026)
    if args.year in ("2025", "all"):
        all_tests.extend(TESTS_2025)

    passed = 0
    failed = 0

    print("🧪 USAW Event Extractor Mock Test Suite (offline)")
    print(f"   {len(all_tests)} tests ({args.year})\n")

    for test in all_tests:
        name = test["name"]
        slug = test["slug"]
        expected = test["expected"]
        fixture_path = FIXTURE_DIR / f"{slug}.html"

        if not fixture_path.exists():
            print(f"⏭️  {name} — fixture missing ({fixture_path.name})")
            print("    Run with --refresh to fetch fixtures")
            failed += 1
            continue

        html = fixture_path.read_text()
        result = extract_event_page(test["url"], html=html)
        ok, failures = check_test(name, expected, result, args.verbose)

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
        print("🎉 All mock tests passed! (offline)")


if __name__ == "__main__":
    main()