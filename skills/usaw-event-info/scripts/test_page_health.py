#!/usr/bin/env python3
"""Tests for check_page_health function in usaw_event_info_sync.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from usaw_event_info_sync import check_page_health


def test_healthy_page():
    """A page with sections, links, and classified info types is healthy."""
    data = {
        "sections": [
            {"title": "Registration", "links": [
                {"url": "https://usaweightlifting.sport80.com/v/808740/e/meets/14372/overview", "info_type": "registration"},
                {"url": "https://example.com/tickets", "info_type": "tickets"},
                {"url": "https://example.com/hotel", "info_type": "hotel"},
                {"url": "https://example.com/stream", "info_type": "live_stream"},
                {"url": "https://example.com/schedule.pdf", "info_type": "preliminary_schedule"},
                {"url": "https://example.com/results", "info_type": "full_results"},
            ]},
        ]
    }
    result = check_page_health(data, "https://www.usaweightlifting.org/2026-national-championships")
    assert result["healthy"] is True, f"Expected healthy, got issues: {result['issues']}"


def test_zero_sections():
    """A page with zero sections is unhealthy."""
    result = check_page_health({"sections": []}, "https://example.com")
    assert result["healthy"] is False
    assert "zero sections extracted" in result["issues"]


def test_low_link_count():
    """A page with fewer than 5 links is unhealthy."""
    data = {"sections": [{"title": "Info", "links": [{"url": "https://a.com", "info_type": "registration"}]}]}
    result = check_page_health(data, "https://example.com")
    assert result["healthy"] is False
    assert any("low link count" in i for i in result["issues"])


def test_zero_classified_links():
    """A page with links but no classified info types is unhealthy."""
    data = {"sections": [{"title": "Info", "links": [
        {"url": "https://a.com", "info_type": None},
        {"url": "https://b.com", "info_type": None},
        {"url": "https://c.com", "info_type": None},
        {"url": "https://d.com", "info_type": None},
        {"url": "https://e.com", "info_type": None},
        {"url": "https://f.com", "info_type": None},
    ]}]}
    result = check_page_health(data, "https://example.com")
    assert result["healthy"] is False
    assert "zero classified links" in result["issues"]


def test_cms_changed():
    """A page with completely different structure (no sections) is unhealthy."""
    result = check_page_health({}, "https://example.com")
    assert result["healthy"] is False
    assert "zero sections extracted" in result["issues"]


if __name__ == "__main__":
    for test in [test_healthy_page, test_zero_sections, test_low_link_count,
                 test_zero_classified_links, test_cms_changed]:
        try:
            test()
            print(f"✅ {test.__name__}")
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")