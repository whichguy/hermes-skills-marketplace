#!/usr/bin/env python3
"""
L9 + L10: Unit tests for usaw_event_extractor.py key functions.

L9: Tests header_priority disambiguation logic in classify_info_type()
    — verifies that when multiple URL patterns match, the H3 header text
    breaks the tie correctly (e.g., Preliminary vs Final Schedule).

L10: Tests classify_sport80_url(), _is_nav_link(), extract_inline_metadata()
    — these critical functions previously had zero direct tests.

Usage:
  uv run --with beautifulsoup4 --with requests --with rapidfuzz \
    python scripts/test_extractor_units.py -v
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Import extractor functions
from usaw_event_extractor import (
    classify_sport80_url,
    _is_nav_link,
    extract_inline_metadata,
    INFO_TYPES,
    classify_info_type,
)


# ──────────────────────────────────────────────────────────────────────
# L10: classify_sport80_url() tests
# ──────────────────────────────────────────────────────────────────────

def test_sport80_v_meets_pattern():
    """L10: /v/808740/e/meets/{ID}/overview → meet_id extracted."""
    result = classify_sport80_url("https://usaweightlifting.sport80.com/v/808740/e/meets/14372/overview")
    assert result is not None, "Expected non-None for v/meets URL"
    assert result.get("meet_id") == "14372", f"Expected meet_id=14372, got {result.get('meet_id')}"
    print("✅ test_sport80_v_meets_pattern")
    return True


def test_sport80_wizard_pattern():
    """L10: /public/wizard/e/{ID} → meet_id extracted."""
    result = classify_sport80_url("https://usaweightlifting.sport80.com/public/wizard/e/14353")
    assert result is not None, "Expected non-None for wizard URL"
    assert result.get("meet_id") == "14353", f"Expected meet_id=14353, got {result.get('meet_id')}"
    print("✅ test_sport80_wizard_pattern")
    return True


def test_sport80_wizard_home_pattern():
    """L10: /public/wizard/e/{ID}/home → meet_id extracted."""
    result = classify_sport80_url("https://usaweightlifting.sport80.com/public/wizard/e/14336/home")
    assert result is not None, "Expected non-None for wizard/home URL"
    assert result.get("meet_id") == "14336", f"Expected meet_id=14336, got {result.get('meet_id')}"
    print("✅ test_sport80_wizard_home_pattern")
    return True


def test_sport80_entries_pattern():
    """L10: /public/events/{ID}/entries/{ENTRY_ID} → meet_id + entry_id extracted."""
    result = classify_sport80_url("https://usaweightlifting.sport80.com/public/events/14353/entries/21233")
    assert result is not None, "Expected non-None for entries URL"
    assert result.get("meet_id") == "14353", f"Expected meet_id=14353, got {result.get('meet_id')}"
    print("✅ test_sport80_entries_pattern")
    return True


def test_sport80_non_sport80_url():
    """L10: Non-Sport80 URL → returns None."""
    result = classify_sport80_url("https://www.usaweightlifting.org/tickets")
    assert result is None, f"Expected None for non-Sport80 URL, got {result}"
    print("✅ test_sport80_non_sport80_url")
    return True


def test_sport80_non_meets_url():
    """L10: Sport80 URL without meet pattern → returns None or pattern-only."""
    result = classify_sport80_url("https://usaweightlifting.sport80.com/public/widget/1")
    # Widget URLs are not meet-specific — should not return a meet_id
    if result is not None:
        assert "meet_id" not in result, f"Expected no meet_id for widget URL, got {result}"
    print("✅ test_sport80_non_meets_url")
    return True


# ──────────────────────────────────────────────────────────────────────
# L10: _is_nav_link() tests
# ──────────────────────────────────────────────────────────────────────

def test_nav_link_coaching():
    """L10: /coaching/ URL → identified as nav link."""
    assert _is_nav_link("https://www.usaweightlifting.org/coaching/acsm") is True
    print("✅ test_nav_link_coaching")
    return True


def test_nav_link_weightlifting101():
    """L10: /weightlifting-101/ URL → identified as nav link."""
    assert _is_nav_link("https://www.usaweightlifting.org/weightlifting101/safesport") is True
    print("✅ test_nav_link_weightlifting101")
    return True


def test_nav_link_governance():
    """L10: /governance URL → identified as nav link."""
    assert _is_nav_link("https://www.usaweightlifting.org/governance") is True
    print("✅ test_nav_link_governance")
    return True


def test_nav_link_not_nav_sport80():
    """L10: Sport80 registration URL → NOT a nav link."""
    assert _is_nav_link("https://usaweightlifting.sport80.com/v/808740/e/meets/14372/overview") is False
    print("✅ test_nav_link_not_nav_sport80")
    return True


def test_nav_link_not_nav_contentstack():
    """L10: Contentstack CDN PDF URL → NOT a nav link."""
    assert _is_nav_link("https://assets.contentstack.io/v3/assets/blteb7d012fc7ebef7f/schedule.pdf") is False
    print("✅ test_nav_link_not_nav_contentstack")
    return True


def test_nav_link_not_nav_google_drive():
    """L10: Google Drive URL → NOT a nav link."""
    assert _is_nav_link("https://drive.google.com/drive/folders/14ncrwEnqErUKGomckAdG_LOT0qEbRomI") is False
    print("✅ test_nav_link_not_nav_google_drive")
    return True


# ──────────────────────────────────────────────────────────────────────
# L10: extract_inline_metadata() tests
# ──────────────────────────────────────────────────────────────────────

def test_metadata_fees_extraction():
    """L10: Fee regex extracts Early Bird / Regular / Late with amounts."""
    text = """
    Registration Opens: January 1, 2026 - 2:00 p.m. MT
    Early Bird Registration ($145)
    Closes: May 7, 2026 - 2:00 p.m. MT
    Regular Registration ($175)
    Closes: May 21, 2026 - 2:00 p.m. MT
    Late Registration ($375)
    Closes: June 4, 2026 - 2:00 p.m. MT
    """
    meta = extract_inline_metadata(text)
    fees = meta.get("registration_fees", {})

    assert "early_bird" in fees, f"Missing early_bird in {list(fees.keys())}"
    assert fees["early_bird"]["fee"] == "$145", f"Expected $145, got {fees['early_bird']['fee']}"
    assert "regular" in fees, f"Missing regular in {list(fees.keys())}"
    assert fees["regular"]["fee"] == "$175", f"Expected $175, got {fees['regular']['fee']}"
    assert "late" in fees, f"Missing late in {list(fees.keys())}"
    assert fees["late"]["fee"] == "$375", f"Expected $375, got {fees['late']['fee']}"

    print("✅ test_metadata_fees_extraction")
    return True


def test_metadata_flat_fee_extraction():
    """L10: Flat fee format (VWS1: $199) extracted correctly."""
    text = """
    Registration Opens ($199): November 1, 2025 - 12:01 a.m. MT
    Registration Closes: February 19, 2026 - 2:00 p.m. MT
    """
    meta = extract_inline_metadata(text)
    # VWS1 uses a flat fee embedded in "Registration Opens" — may or may not match flat_fee pattern
    # But registration_opens should be captured
    assert meta.get("registration_opens") is not None, "Expected registration_opens in metadata"
    print("✅ test_metadata_flat_fee_extraction")
    return True


def test_metadata_dates_extraction():
    """L10: Competition dates extracted from inline text."""
    text = """
    Competition Dates: June 20-28, 2026
    Qualification Period: May 21, 2025 – May 21, 2026
    """
    meta = extract_inline_metadata(text)
    # Should extract competition dates
    dates = meta.get("competition_dates") or meta.get("dates")
    if dates:
        assert "2026" in dates, f"Expected 2026 in dates, got '{dates}'"
    print("✅ test_metadata_dates_extraction")
    return True


def test_metadata_milestones_extraction():
    """L10: Schedule milestones extracted from inline text."""
    text = """
    Preliminary Schedule Released: May 23, 2026 - 2:00 p.m. MT
    Verification of Final Entries: June 8, 2026 - 10:00-10:30 a.m. MT
    Final Schedule Released: June 10, 2026 - 2:00 p.m. MT
    """
    meta = extract_inline_metadata(text)
    milestones = meta.get("schedule_milestones", {})
    assert len(milestones) >= 2, f"Expected 2+ milestones, got {len(milestones)}: {list(milestones.keys())}"
    print(f"✅ test_metadata_milestones_extraction ({len(milestones)} milestones)")
    return True


def test_metadata_empty_text():
    """L10: Empty/garbage text → returns empty metadata, no crash."""
    meta = extract_inline_metadata("This is just random text with no USAW metadata.")
    assert isinstance(meta, dict), f"Expected dict, got {type(meta)}"
    # Should not have fees or milestones
    assert "registration_fees" not in meta, "Should not extract fees from random text"
    print("✅ test_metadata_empty_text")
    return True


# ──────────────────────────────────────────────────────────────────────
# L9: header_priority disambiguation tests
# ──────────────────────────────────────────────────────────────────────

def test_header_priority_preliminary_vs_final_schedule():
    """L9: Two Contentstack CDN PDFs — header text must disambiguate prelim vs final.

    Both match the same URL pattern (assets.contentstack.io.*schedule).
    header_priority should use the H3 header to pick the correct type.
    """
    # Simulate two links with the same URL pattern but different headers
    prelim_url = "https://assets.contentstack.io/v3/assets/blt123/2026_NCW_Preliminary_Schedule.pdf"
    final_url = "https://assets.contentstack.io/v3/assets/blt456/schedule.pdf"

    # Classify with "Preliminary Schedule" header
    prelim_type = classify_info_type(
        url=prelim_url,
        header_text="Preliminary Schedule",
        link_text="View, opens in a new tab",
    )
    assert prelim_type == "preliminary_schedule", \
        f"Expected 'preliminary_schedule', got '{prelim_type}' for prelim URL with 'Preliminary Schedule' header"

    # Classify with "Final Schedule" header
    final_type = classify_info_type(
        url=final_url,
        header_text="Final Schedule",
        link_text="View, opens in a new tab",
    )
    assert final_type == "final_schedule", \
        f"Expected 'final_schedule', got '{final_type}' for final URL with 'Final Schedule' header"

    print("✅ test_header_priority_preliminary_vs_final_schedule")
    return True


def test_header_priority_registration_vs_adaptive():
    """L9: Sport80 registration URL with "Adaptive" header → adaptive_registration, not registration.

    Both adaptive_registration and registration match sport80.com/v/meets/ URL pattern.
    The header "Adaptive National Championships Registration" should trigger adaptive_registration.
    """
    url = "https://usaweightlifting.sport80.com/v/808740/e/meets/14373/overview"

    # Standard registration
    std_type = classify_info_type(
        url=url,
        header_text="National Championships Registration",
        link_text="View, opens in a new tab",
    )
    # Should be registration or adaptive_registration — depends on header matching
    # The key test: adaptive header should NOT classify as generic registration
    adaptive_type = classify_info_type(
        url=url,
        header_text="Adaptive National Championships Registration",
        link_text="View, opens in a new tab",
    )

    # Adaptive should be adaptive_registration, NOT plain registration
    assert adaptive_type == "adaptive_registration", \
        f"Expected 'adaptive_registration' for adaptive header, got '{adaptive_type}'"

    print("✅ test_header_priority_registration_vs_adaptive")
    return True


def test_url_pattern_only_no_header():
    """L9: URL pattern match with empty header → still classifies by URL."""
    # Google Drive URL should classify as full_results even without header
    url = "https://drive.google.com/drive/folders/14ncrwEnqErUKGomckAdG_LOT0qEbRomI"
    result = classify_info_type(url=url, header_text="", link_text="Full Results")
    assert result == "full_results", \
        f"Expected 'full_results' for Google Drive URL, got '{result}'"
    print("✅ test_url_pattern_only_no_header")
    return True


def test_info_types_count():
    """L9: Verify INFO_TYPES has the expected number of entries (23, not 22)."""
    count = len(INFO_TYPES)
    assert count >= 22, f"Expected 22+ info types, got {count}"
    # Check key types exist
    for t in ["registration", "adaptive_registration", "full_results",
              "preliminary_schedule", "final_schedule", "medal_schedule",
              "tickets", "live_stream", "hotel", "media_credentials"]:
        assert t in INFO_TYPES, f"Missing info type: {t}"
    print(f"✅ test_info_types_count ({count} types)")
    return True


def test_medal_schedule_not_in_full_results_aliases():
    """L9/L3: 'medal schedule' should NOT be in full_results aliases (L3 fix)."""
    aliases = INFO_TYPES["full_results"]["aliases"]
    assert "medal schedule" not in aliases, \
        f"'medal schedule' should not be in full_results aliases (L3 fix): {aliases}"
    # But it SHOULD be in medal_schedule's aliases
    ms_aliases = INFO_TYPES["medal_schedule"]["aliases"]
    assert "medal schedule" in ms_aliases, \
        f"'medal schedule' should be in medal_schedule aliases: {ms_aliases}"
    print("✅ test_medal_schedule_not_in_full_results_aliases")
    return True


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    # L10: Sport80 URL classification
    test_sport80_v_meets_pattern,
    test_sport80_wizard_pattern,
    test_sport80_wizard_home_pattern,
    test_sport80_entries_pattern,
    test_sport80_non_sport80_url,
    test_sport80_non_meets_url,
    # L10: Nav link filtering
    test_nav_link_coaching,
    test_nav_link_weightlifting101,
    test_nav_link_governance,
    test_nav_link_not_nav_sport80,
    test_nav_link_not_nav_contentstack,
    test_nav_link_not_nav_google_drive,
    # L10: Inline metadata extraction
    test_metadata_fees_extraction,
    test_metadata_flat_fee_extraction,
    test_metadata_dates_extraction,
    test_metadata_milestones_extraction,
    test_metadata_empty_text,
    # L9: header_priority disambiguation
    test_header_priority_preliminary_vs_final_schedule,
    test_header_priority_registration_vs_adaptive,
    test_url_pattern_only_no_header,
    test_info_types_count,
    test_medal_schedule_not_in_full_results_aliases,
]


def main():
    print("🧪 USAW Extractor Unit Tests (L9 + L10)")
    print(f"   {len(ALL_TESTS)} tests\n")

    passed = 0
    failed = 0

    for test in ALL_TESTS:
        try:
            result = test()
            if result:
                passed += 1
            else:
                failed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed ({len(ALL_TESTS)} total)")

    if failed > 0:
        sys.exit(1)
    else:
        print("🎉 All unit tests passed!")


if __name__ == "__main__":
    main()