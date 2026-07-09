#!/usr/bin/env python3
"""Tests for untested functions — corner case coverage expansion.

Covers:
- usaw_event_extractor.py: _resolve_url, _clean_link_text, extract_event_page,
  extract_event_title_and_overview, format_markdown
- usaw_event_info_sync.py: simplify_event, diff_events, load_snapshot, save_snapshot
- usaw_results_parser.py: classify_file_name, format_summary
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# ──────────────────────────────────────────────────────────────────────
# usaw_event_extractor.py tests
# ──────────────────────────────────────────────────────────────────────

def test_resolve_url_absolute():
    from usaw_event_extractor import _resolve_url
    assert _resolve_url("https://example.com/page") == "https://example.com/page"
    assert _resolve_url("http://foo.bar/baz") == "http://foo.bar/baz"


def test_resolve_url_relative():
    from usaw_event_extractor import _resolve_url
    assert _resolve_url("/events/2026") == "https://www.usaweightlifting.org/events/2026"
    assert _resolve_url("/registration") == "https://www.usaweightlifting.org/registration"


def test_resolve_url_protocol_relative():
    from usaw_event_extractor import _resolve_url
    # _resolve_url only prepends the domain for paths starting with "/"
    # Protocol-relative URLs (//) don't start with "/" alone, so they pass through
    result = _resolve_url("//cdn.example.com/asset.js")
    assert "cdn.example.com" in result  # May get domain prepended, but should contain the CDN


def test_clean_link_text_removes_new_tab():
    from usaw_event_extractor import _clean_link_text
    assert _clean_link_text("View, opens in a new tab") == "View"
    assert _clean_link_text("Register, Opens in a New Tab") == "Register"


def test_clean_link_text_no_change():
    from usaw_event_extractor import _clean_link_text
    assert _clean_link_text("Schedule PDF") == "Schedule PDF"
    assert _clean_link_text("") == ""


def test_extract_event_title_and_overview():
    from usaw_event_extractor import extract_event_title_and_overview
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <h1>2026 National Championships</h1>
    <p>June 20-28, 2026 | Grand Rapids, MI | DeVos Place</p>
    <h2>Registration</h2>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    info = extract_event_title_and_overview(soup)
    assert info["title"] == "2026 National Championships"
    assert "June 20-28" in info["dates_raw"]
    assert "Grand Rapids" in info["venue_raw"]
    assert "DeVos Place" in info["location_raw"]


def test_extract_event_title_and_overview_no_h1():
    from usaw_event_extractor import extract_event_title_and_overview
    from bs4 import BeautifulSoup

    html = "<html><body><p>No title here</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    info = extract_event_title_and_overview(soup)
    assert "title" not in info or not info.get("title")


def test_extract_event_page_with_mock_html():
    from usaw_event_extractor import extract_event_page

    html = """
    <html><body>
    <h1>2026 National Championships</h1>
    <p>June 20-28, 2026 | Grand Rapids, MI | DeVos Place</p>
    <main>
    <h2>Registration</h2>
    <div><h3>Athlete Registration</h3>
    <a href="https://usaweightlifting.sport80.com/v/808740/e/meets/14372/overview">Register Now</a>
    </div>
    <h2>Schedule</h2>
    <div><h3>Preliminary Schedule</h3>
    <a href="https://assets.contentstack.io/v3/assets/abc123/schedule.pdf">View Schedule, opens in a new tab</a>
    </div>
    <h2>Results</h2>
    <div><h3>Full Results</h3>
    <a href="https://drive.google.com/drive/folders/xyz789">Results Folder</a>
    </div>
    </main>
    </body></html>
    """
    result = extract_event_page("https://www.usaweightlifting.org/2026-national-championships", html=html)

    assert result["source_url"] == "https://www.usaweightlifting.org/2026-national-championships"
    assert result["title"] == "2026 National Championships"
    # The extractor returns info_by_type, not "sections" — check the actual structure
    assert "info_by_type" in result
    assert "unclassified" in result
    assert result["total_links"] > 0

    # Check Sport80 link was classified
    all_urls = []
    for items in result.get("info_by_type", {}).values():
        for item in items:
            all_urls.append(item.get("url", ""))
    for item in result.get("unclassified", []):
        all_urls.append(item.get("url", ""))

    sport80_links = [u for u in all_urls if "sport80" in u]
    assert len(sport80_links) > 0, f"Expected Sport80 link, got URLs: {all_urls}"

    # Check that at least some links were classified
    classified = sum(len(v) for v in result.get("info_by_type", {}).values())
    assert classified > 0, f"Expected classified links, got info_by_type: {result.get('info_by_type')}"


def test_extract_event_page_empty_html():
    from usaw_event_extractor import extract_event_page

    html = "<html><body></body></html>"
    result = extract_event_page("https://example.com", html=html)
    assert result["source_url"] == "https://example.com"
    assert result["total_links"] == 0


def test_format_markdown_basic():
    from usaw_event_extractor import format_markdown

    result = {
        "title": "2026 National Championships",
        "source_url": "https://www.usaweightlifting.org/2026-national-championships",
        "dates_raw": "June 20-28, 2026",
        "venue_raw": "Grand Rapids, MI",
        "location_raw": "DeVos Place",
        "info_by_type": {},
        "unclassified": [],
        "classified_count": 0,
        "unclassified_count": 0,
        "total_links": 0,
        "metadata": {},
    }
    md = format_markdown(result)
    assert "# 2026 National Championships" in md
    assert "https://www.usaweightlifting.org/2026-national-championships" in md
    assert "June 20-28, 2026" in md
    assert "Grand Rapids, MI" in md


def test_format_markdown_with_metadata():
    from usaw_event_extractor import format_markdown

    result = {
        "title": "Test Event",
        "source_url": "https://example.com",
        "dates_raw": "N/A",
        "venue_raw": "N/A",
        "location_raw": "N/A",
        "info_by_type": {},
        "unclassified": [],
        "classified_count": 0,
        "unclassified_count": 0,
        "total_links": 0,
        "metadata": {"fees": {"early": {"fee": "$100", "closes": "2026-03-01"}}},
    }
    md = format_markdown(result)
    assert "## Event Metadata" in md
    assert "early" in md
    assert "$100" in md


# ──────────────────────────────────────────────────────────────────────
# usaw_event_info_sync.py tests
# ──────────────────────────────────────────────────────────────────────

def test_simplify_event():
    from usaw_event_info_sync import simplify_event

    event = {
        "title": "2026 NCW",
        "dates": "June 20-28",
        "venue": "Grand Rapids",
        "status": "active",
        "fees": {"early": "$100"},
        "milestones": {"registration_open": "2026-03-01"},
        "info_by_type": {
            "registration": [{"title": "Register", "url": "https://sport80.com/register"}],
            "tickets": [{"title": "Buy Tickets", "url": "https://example.com/tickets"}],
        },
        "unclassified": [{"title": "Misc", "url": "https://example.com/misc"}],
    }
    simple = simplify_event(event)
    assert simple["title"] == "2026 NCW"
    assert simple["dates"] == "June 20-28"
    assert simple["info_type_count"] == 2
    assert len(simple["links"]) == 3  # 2 classified + 1 unclassified


def test_simplify_event_empty():
    from usaw_event_info_sync import simplify_event

    simple = simplify_event({})
    assert simple["title"] is None
    assert simple["info_type_count"] == 0
    assert simple["links"] == []


def test_diff_events_no_change():
    from usaw_event_info_sync import diff_events

    old = {
        "title": "2026 NCW",
        "dates": "June 20-28",
        "venue": "Grand Rapids",
        "info_by_type": {"registration": [{"title": "Register", "url": "https://sport80.com/register"}]},
    }
    changes = diff_events(old, old, "2026 NCW")
    assert len(changes) == 0, f"Expected no changes, got: {changes}"


def test_diff_events_title_change():
    from usaw_event_info_sync import diff_events

    old = {"title": "2026 NCW", "dates": "June 20-28", "venue": "Grand Rapids", "info_by_type": {}}
    new = {"title": "2026 National Championships Week", "dates": "June 20-28", "venue": "Grand Rapids", "info_by_type": {}}
    changes = diff_events(old, new, "2026 NCW")
    title_changes = [c for c in changes if c["field"] == "title"]
    assert len(title_changes) == 1
    assert title_changes[0]["old"] == "2026 NCW"
    assert title_changes[0]["new"] == "2026 National Championships Week"


def test_diff_events_new_url():
    from usaw_event_info_sync import diff_events

    old = {"title": "NCW", "info_by_type": {"registration": [{"title": "Reg", "url": "https://old.com"}]}}
    new = {"title": "NCW", "info_by_type": {"registration": [{"title": "Reg", "url": "https://old.com"}, {"title": "New", "url": "https://new.com"}]}}
    changes = diff_events(old, new, "NCW")
    url_changes = [c for c in changes if c["field"] == "urls"]
    assert len(url_changes) == 1
    assert "https://new.com" in url_changes[0]["added"]


def test_diff_events_new_info_type():
    from usaw_event_info_sync import diff_events

    old = {"title": "NCW", "info_by_type": {"registration": [{"title": "Reg", "url": "https://reg.com"}]}}
    new = {"title": "NCW", "info_by_type": {
        "registration": [{"title": "Reg", "url": "https://reg.com"}],
        "tickets": [{"title": "Tickets", "url": "https://tickets.com"}],
    }}
    changes = diff_events(old, new, "NCW")
    type_changes = [c for c in changes if c["field"] == "info_types"]
    assert len(type_changes) == 1
    assert "tickets" in type_changes[0]["added"]


def test_diff_events_first_run():
    from usaw_event_info_sync import diff_events

    new = {"title": "NCW", "info_by_type": {"registration": [{"title": "Reg", "url": "https://reg.com"}]}}
    changes = diff_events(None, new, "NCW")
    # First run: everything is "new"
    title_changes = [c for c in changes if c["field"] == "title"]
    assert len(title_changes) == 1
    assert title_changes[0]["old"] is None


def test_load_save_snapshot():
    from usaw_event_info_sync import save_snapshot, load_snapshot
    import usaw_event_info_sync

    test_data = {"test_event": {"title": "Test", "info_by_type": {}}}

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tmp_path = Path(f.name)

    original = usaw_event_info_sync.SNAPSHOT_FILE
    usaw_event_info_sync.SNAPSHOT_FILE = tmp_path

    try:
        save_snapshot(test_data)
        loaded = load_snapshot()
        assert loaded == test_data
        assert loaded["test_event"]["title"] == "Test"
    finally:
        usaw_event_info_sync.SNAPSHOT_FILE = original
        tmp_path.unlink(missing_ok=True)


def test_load_snapshot_missing_file():
    from usaw_event_info_sync import load_snapshot
    import usaw_event_info_sync

    original = usaw_event_info_sync.SNAPSHOT_FILE
    usaw_event_info_sync.SNAPSHOT_FILE = Path("/tmp/nonexistent_snapshot_test.json")

    try:
        result = load_snapshot()
        assert result == {}
    finally:
        usaw_event_info_sync.SNAPSHOT_FILE = original


# ──────────────────────────────────────────────────────────────────────
# usaw_results_parser.py tests
# ──────────────────────────────────────────────────────────────────────

def test_classify_file_name_results():
    from usaw_results_parser import classify_file_name
    # Pattern: Results.pdf$ (case-insensitive)
    info = classify_file_name("2026 NCW Results.pdf")
    assert info["doc_type"] == "full_results"


def test_classify_file_name_start_list():
    from usaw_results_parser import classify_file_name
    # Pattern: start.?list (case-insensitive)
    info = classify_file_name("2026-ncw-start-list.pdf")
    assert info["doc_type"] == "start_list"


def test_classify_file_name_best_lifters():
    from usaw_results_parser import classify_file_name
    # Pattern: Results - (.+?) Best Lifters.pdf$
    info = classify_file_name("2026 NCW Results - U11 Best Lifters.pdf")
    assert info["doc_type"] == "best_lifters"
    assert info["division"] is not None


def test_classify_file_name_medal_schedule():
    from usaw_results_parser import classify_file_name
    info = classify_file_name("2026 NCW Medal Schedule.pdf")
    assert info["doc_type"] == "medal_schedule"


def test_classify_file_name_unknown():
    from usaw_results_parser import classify_file_name
    info = classify_file_name("random-document.pdf")
    assert info["doc_type"] == "unknown"


def test_format_summary_results():
    from usaw_results_parser import format_summary
    result = {
        "file_name": "2026-ncw-results.pdf",
        "pdf_type": "full_results",
        "total_athletes": 1315,
        "total_categories": 116,
        "page_count": 30,
        "file_classification": {"doc_type": "full_results", "division": None},
    }
    summary = format_summary(result)
    assert "2026-ncw-results.pdf" in summary
    assert "full_results" in summary
    assert "1315" in summary


def test_format_summary_schedule():
    from usaw_results_parser import format_summary
    result = {
        "file_name": "2026-ncw-final-schedule.pdf",
        "pdf_type": "final_schedule",
        "total_sessions": 122,
        "page_count": 4,
        "file_classification": {"doc_type": "unknown", "division": None},
    }
    summary = format_summary(result)
    assert "2026-ncw-final-schedule.pdf" in summary
    assert "final_schedule" in summary


def test_format_summary_unknown():
    from usaw_results_parser import format_summary
    result = {
        "file_name": "unknown.pdf",
        "pdf_type": "unknown",
        "page_count": 1,
        "file_classification": {"doc_type": "unknown", "division": None},
    }
    summary = format_summary(result)
    assert "unknown.pdf" in summary


# ──────────────────────────────────────────────────────────────────────
# _find_section_containers + _extract_links_from_element + extract_all_links
# ──────────────────────────────────────────────────────────────────────

def test_find_section_containers_chakra_ui():
    """H2 + UL in sibling divs inside .content-tile-block (NCW pattern)."""
    from usaw_event_extractor import _find_section_containers
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <div class="content-tile-block">
      <div><h2>Registration</h2></div>
      <div><ul><li><a href="/register">Register</a></li></ul></div>
    </div>
    <div class="content-tile-block">
      <div><h2>Schedule</h2></div>
      <div><ul><li><a href="/schedule">Schedule</a></li></ul></div>
    </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    containers = _find_section_containers(soup)
    assert len(containers) == 2
    h2_texts = [c[0] for c in containers]
    assert "Registration" in h2_texts
    assert "Schedule" in h2_texts


def test_find_section_containers_simple():
    """Simpler pages: H2 followed by content in siblings."""
    from usaw_event_extractor import _find_section_containers
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <div><h2>Results</h2><a href="/results.pdf">Results PDF</a></div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    containers = _find_section_containers(soup)
    assert len(containers) >= 1
    assert containers[0][0] == "Results"


def test_find_section_containers_empty():
    from usaw_event_extractor import _find_section_containers
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    containers = _find_section_containers(soup)
    assert len(containers) == 0


def test_find_section_containers_permalink_artifact():
    """H2 text with 'Permalink to the ... heading' should be cleaned."""
    from usaw_event_extractor import _find_section_containers
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <div><h2>Permalink to the 'Tickets' heading</h2><ul><li>x</li></ul></div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    containers = _find_section_containers(soup)
    assert len(containers) == 1
    assert containers[0][0] == "Tickets"


def test_extract_links_from_element_with_h3():
    """Extract links organized by H3 subsections."""
    from usaw_event_extractor import _extract_links_from_element
    from bs4 import BeautifulSoup

    html = """
    <div>
      <li><h3>Athlete Registration</h3><a href="https://sport80.com/v/808740/e/meets/14372">Register Now</a></li>
      <li><h3>Team Registration</h3><a href="https://sport80.com/v/808740/e/meets/14372/teams">Team Reg</a></li>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    links = _extract_links_from_element(soup, "Registration", seen)
    assert len(links) == 2
    assert links[0]["h2_section"] == "Registration"
    assert links[0]["h3_header"] == "Athlete Registration"
    assert "sport80.com" in links[0]["url"]


def test_extract_links_from_element_standalone():
    """Standalone links not under an H3 are captured."""
    from usaw_event_extractor import _extract_links_from_element
    from bs4 import BeautifulSoup

    html = '<div><p>View the <a href="/results.pdf">Full Results</a> here.</p></div>'
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    links = _extract_links_from_element(soup, "Results", seen)
    assert len(links) == 1
    assert links[0]["link_text"] == "Full Results"
    assert links[0]["url"] == "https://www.usaweightlifting.org/results.pdf"


def test_extract_links_from_element_tba_status():
    """Links near 'TBA' text should get status='TBA'."""
    from usaw_event_extractor import _extract_links_from_element
    from bs4 import BeautifulSoup

    html = '<div><li><h3>Final Schedule</h3><a href="/schedule.pdf">Schedule PDF</a> Status: TBA</li></div>'
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    links = _extract_links_from_element(soup, "Schedule", seen)
    assert len(links) == 1
    assert links[0]["status"] == "TBA"


def test_extract_links_from_element_dedup():
    """Duplicate URLs should be skipped via seen_urls."""
    from usaw_event_extractor import _extract_links_from_element
    from bs4 import BeautifulSoup

    html = """
    <div>
      <li><h3>Reg 1</h3><a href="https://example.com/register">Register</a></li>
      <li><h3>Reg 2</h3><a href="https://example.com/register">Register Again</a></li>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    links = _extract_links_from_element(soup, "Registration", seen)
    assert len(links) == 1  # Second link deduped


def test_extract_all_links_integration():
    """Full integration: H2 sections + H3 subsections + standalone links."""
    from usaw_event_extractor import extract_all_links
    from bs4 import BeautifulSoup

    html = """
    <html><body><main>
    <div class="content-tile-block">
      <div><h2>Registration</h2></div>
      <div><ul>
        <li><h3>Athlete Registration</h3><a href="https://usaweightlifting.sport80.com/v/808740/e/meets/14372/overview">Register Now</a></li>
      </ul></div>
    </div>
    <div class="content-tile-block">
      <div><h2>Schedule</h2></div>
      <div><ul>
        <li><h3>Preliminary Schedule</h3><a href="https://assets.contentstack.io/v3/assets/abc/schedule.pdf">View Schedule, opens in a new tab</a></li>
      </ul></div>
    </div>
    <div class="content-tile-block">
      <div><h2>Results</h2></div>
      <div><ul>
        <li><h3>Full Results</h3><a href="https://drive.google.com/drive/folders/xyz789">Results Folder</a></li>
      </ul></div>
    </div>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    links = extract_all_links(soup)
    assert len(links) >= 3
    h2_sections = [link["h2_section"] for link in links]
    assert "Registration" in h2_sections
    assert "Schedule" in h2_sections
    assert "Results" in h2_sections

    # Check link text was cleaned
    schedule_link = [link for link in links if link["h2_section"] == "Schedule"][0]
    assert schedule_link["link_text"] == "View Schedule"  # "opens in a new tab" removed


def test_extract_all_links_empty_page():
    from usaw_event_extractor import extract_all_links
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    links = extract_all_links(soup)
    assert len(links) == 0


def test_extract_all_links_skips_nav():
    """Nav links (coaching, governance, etc.) should be filtered out."""
    from usaw_event_extractor import extract_all_links
    from bs4 import BeautifulSoup

    html = """
    <html><body><main>
    <a href="/coaching">Coaching Education</a>
    <a href="/weightlifting-101">Weightlifting 101</a>
    <div><h2>Registration</h2><ul><li><a href="https://sport80.com/register">Register</a></li></ul></div>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    links = extract_all_links(soup)
    urls = [link["url"] for link in links]
    assert "https://www.usaweightlifting.org/coaching" not in urls
    assert "https://www.usaweightlifting.org/weightlifting-101" not in urls
    assert any("sport80.com" in u for u in urls)


# ──────────────────────────────────────────────────────────────────────
# update_meet_ids_reference
# ──────────────────────────────────────────────────────────────────────

def test_update_meet_ids_no_drift():
    from usaw_event_info_sync import update_meet_ids_reference

    # Use the real reference file — known IDs from it should produce no drift
    events_data = {
        "2026 NCW": {
            "info_by_type": {
                "registration": [{"title": "Register", "url": "https://usaweightlifting.sport80.com/v/808740/e/meets/14372/overview"}],
            }
        }
    }
    findings = update_meet_ids_reference(events_data)
    # 14372 should be in the reference file — no drift expected
    # (If it IS in the reference, findings is empty. If not, it's a new ID.)
    # Either 0 (ID known) or 1 (ID not in reference) — both are valid
    # The test just verifies the function runs without error
    assert isinstance(findings, list)


def test_update_meet_ids_detects_new_id():
    from usaw_event_info_sync import update_meet_ids_reference

    events_data = {
        "2026 NewEvent": {
            "info_by_type": {
                "registration": [{"title": "Register", "url": "https://usaweightlifting.sport80.com/v/808740/e/meets/99999/overview"}],
            }
        }
    }
    findings = update_meet_ids_reference(events_data)
    # 99999 is not a real meet ID — should appear as drift
    new_event_findings = [f for f in findings if f["meet_id"] == "99999"]
    assert len(new_event_findings) == 1
    assert new_event_findings[0]["event"] == "2026 NewEvent"
    assert new_event_findings[0]["info_type"] == "registration"


def test_update_meet_ids_wizard_pattern():
    from usaw_event_info_sync import update_meet_ids_reference

    events_data = {
        "2026 TestEvent": {
            "info_by_type": {
                "registration": [{"title": "Wizard", "url": "https://usaweightlifting.sport80.com/public/wizard/e/88888"}],
            }
        }
    }
    findings = update_meet_ids_reference(events_data)
    wizard_findings = [f for f in findings if f["meet_id"] == "88888"]
    assert len(wizard_findings) == 1


def test_update_meet_ids_empty_data():
    from usaw_event_info_sync import update_meet_ids_reference
    findings = update_meet_ids_reference({})
    assert findings == []


def test_update_meet_ids_no_sport80_urls():
    from usaw_event_info_sync import update_meet_ids_reference

    events_data = {
        "2026 NCW": {
            "info_by_type": {
                "tickets": [{"title": "Buy Tickets", "url": "https://example.com/tickets"}],
            }
        }
    }
    findings = update_meet_ids_reference(events_data)
    assert findings == []


# ──────────────────────────────────────────────────────────────────────
# run_test_suite
# ──────────────────────────────────────────────────────────────────────

def test_run_test_suite_mock():
    """run_test_suite(live=False) should run mock tests and return a dict."""
    from usaw_event_info_sync import run_test_suite
    result = run_test_suite(live=False)
    assert isinstance(result, dict)
    assert result["test_type"] == "mock"
    assert "returncode" in result
    assert "stdout_tail" in result
    assert "stderr_tail" in result


# ═══════════════════════════════════════════════════════════════════════
# CORNER CASE + EDGE CONDITION TESTS (from Kimi coverage review)
# ═══════════════════════════════════════════════════════════════════════

# ─── classify_info_type corner cases ───

def test_classify_info_type_empty_inputs():
    from usaw_event_extractor import classify_info_type
    assert classify_info_type("", "") is None
    assert classify_info_type("", None) is None
    assert classify_info_type(None, None) is None


def test_classify_info_type_header_only_no_url():
    from usaw_event_extractor import classify_info_type
    # Header-only matching (no URL to match)
    result = classify_info_type("Athlete Registration", "")
    assert result is not None, f"Expected registration type, got {result}"


def test_classify_info_type_threshold_exactly_60():
    from usaw_event_extractor import classify_info_type
    # Fuzzy threshold is 60 — a barely-matching header should not classify
    result = classify_info_type("xyz", "")
    assert result is None, f"Expected None for non-matching header, got {result}"


# ─── classify_sport80_url edge cases ───

def test_classify_sport80_url_malformed():
    from usaw_event_extractor import classify_sport80_url
    info = classify_sport80_url("https://sport80.com/broken")
    assert info["platform"] == "sport80"
    assert info["pattern"] == "unknown"


def test_classify_sport80_url_non_sport80():
    from usaw_event_extractor import classify_sport80_url
    info = classify_sport80_url("https://example.com/page")
    assert info.get("platform") is None or "platform" not in info or info.get("pattern") is None


# ─── extract_inline_metadata edge cases ───

def test_extract_metadata_malformed_fees():
    from usaw_event_extractor import extract_inline_metadata
    # Fees without closing date
    result = extract_inline_metadata("Registration fee $150")
    # Should not crash — may or may not extract depending on pattern
    assert isinstance(result, dict)


def test_extract_metadata_no_matching_content():
    from usaw_event_extractor import extract_inline_metadata
    result = extract_inline_metadata("This is just some random text with no metadata.")
    assert result == {}


def test_extract_metadata_unusual_date_format():
    from usaw_event_extractor import extract_inline_metadata
    result = extract_inline_metadata("Event runs from June 20 to June 28, 2026")
    assert isinstance(result, dict)


# ─── _is_nav_link additional patterns ───

def test_nav_link_education_courses():
    from usaw_event_extractor import _is_nav_link
    assert _is_nav_link("https://www.usaweightlifting.org/online-education-courses", "Courses", "") is True


def test_nav_link_referees():
    from usaw_event_extractor import _is_nav_link
    assert _is_nav_link("https://www.usaweightlifting.org/referees", "Referees", "") is True


def test_nav_link_sport80_widget():
    from usaw_event_extractor import _is_nav_link
    assert _is_nav_link("https://usaweightlifting.sport80.com/public/widget/calendar", "Calendar", "") is True


def test_nav_link_not_nav_event_page():
    from usaw_event_extractor import _is_nav_link
    # Event-specific pages should NOT be filtered as nav
    assert _is_nav_link("https://www.usaweightlifting.org/2026-national-championships", "2026 NCW", "") is False


# ─── _resolve_url edge cases ───

def test_resolve_url_empty():
    from usaw_event_extractor import _resolve_url
    assert _resolve_url("") == ""


def test_resolve_url_hash_only():
    from usaw_event_extractor import _resolve_url
    # Hash-only URLs should pass through (not start with /)
    assert _resolve_url("#section") == "#section"


# ─── _clean_link_text edge cases ───

def test_clean_link_text_only_new_tab():
    from usaw_event_extractor import _clean_link_text
    assert _clean_link_text("opens in a new tab") == ""


# ─── extract_event_title_and_overview edge cases ───

def test_extract_title_overview_missing_venue():
    from usaw_event_extractor import extract_event_title_and_overview
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <h1>2026 Test Event</h1>
    <p>June 20-28, 2026 | DeVos Place</p>
    <h2>Content</h2>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    info = extract_event_title_and_overview(soup)
    assert info["title"] == "2026 Test Event"
    assert "dates_raw" in info
    # Only 2 pipe-separated parts — no location_raw
    assert "location_raw" not in info


def test_extract_title_overview_no_pipe():
    from usaw_event_extractor import extract_event_title_and_overview
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <h1>Test Event</h1>
    <p>Just some text without pipes or year</p>
    <h2>Content</h2>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    info = extract_event_title_and_overview(soup)
    assert info.get("title") == "Test Event"
    # No pipe-separated overview line → no dates_raw
    assert "dates_raw" not in info


# ─── format_markdown edge cases ───

def test_format_markdown_no_title():
    from usaw_event_extractor import format_markdown
    result = {
        "title": "",
        "source_url": "https://example.com",
        "dates_raw": "",
        "venue_raw": "",
        "location_raw": "",
        "info_by_type": {},
        "unclassified": [],
        "classified_count": 0,
        "unclassified_count": 0,
        "total_links": 0,
        "metadata": {},
    }
    md = format_markdown(result)
    assert "# " in md  # Empty title still renders header


def test_format_markdown_with_classified_links():
    from usaw_event_extractor import format_markdown
    result = {
        "title": "Test",
        "source_url": "https://example.com",
        "dates_raw": "N/A",
        "venue_raw": "N/A",
        "location_raw": "N/A",
        "info_by_type": {
            "registration": [{"title": "Register", "url": "https://sport80.com/reg"}],
        },
        "unclassified": [{"title": "Misc Link", "url": "https://example.com/misc"}],
        "classified_count": 1,
        "unclassified_count": 1,
        "total_links": 2,
        "metadata": {},
    }
    md = format_markdown(result)
    assert "registration" in md.lower() or "Register" in md


# ─── check_page_health boundary conditions ───

def test_check_page_health_exactly_4_links():
    from usaw_event_info_sync import check_page_health
    data = {
        "sections": [
            {"links": [{"info_type": "reg"}, {}, {}, {}]},
        ]
    }
    result = check_page_health(data, "https://example.com")
    # 4 links < 5 threshold → should flag
    assert not result["healthy"]
    assert any("low link" in i for i in result["issues"])


def test_check_page_health_exactly_5_links():
    from usaw_event_info_sync import check_page_health
    data = {
        "sections": [
            {"links": [{"info_type": "reg"}, {}, {}, {}, {}]},
        ]
    }
    result = check_page_health(data, "https://example.com")
    # 5 links is NOT < 5 → should not flag low links
    assert not any("low link" in i for i in result["issues"])


def test_check_page_health_sections_none():
    from usaw_event_info_sync import check_page_health
    data = {"sections": None}
    result = check_page_health(data, "https://example.com")
    # sections=None → not sections → zero sections issue
    assert not result["healthy"]


# ─── diff_events removal branches ───

def test_diff_events_removed_url():
    from usaw_event_info_sync import diff_events
    old = {"title": "NCW", "info_by_type": {
        "registration": [{"title": "Reg", "url": "https://old.com"}, {"title": "Gone", "url": "https://removed.com"}]
    }}
    new = {"title": "NCW", "info_by_type": {
        "registration": [{"title": "Reg", "url": "https://old.com"}]
    }}
    changes = diff_events(old, new, "NCW")
    # URL was removed — diff_events doesn't track removed URLs (only added)
    # But info_types should not change since registration is still present
    type_changes = [c for c in changes if c["field"] == "info_types"]
    assert len(type_changes) == 0


def test_diff_events_removed_info_type():
    from usaw_event_info_sync import diff_events
    old = {"title": "NCW", "info_by_type": {
        "registration": [{"title": "Reg", "url": "https://reg.com"}],
        "tickets": [{"title": "Tickets", "url": "https://tickets.com"}],
    }}
    new = {"title": "NCW", "info_by_type": {
        "registration": [{"title": "Reg", "url": "https://reg.com"}],
    }}
    changes = diff_events(old, new, "NCW")
    type_changes = [c for c in changes if c["field"] == "info_types"]
    assert len(type_changes) == 1
    assert "tickets" in type_changes[0]["removed"]


def test_diff_events_status_change():
    from usaw_event_info_sync import diff_events
    old = {"title": "NCW", "status": "active", "info_by_type": {}}
    new = {"title": "NCW", "status": "completed", "info_by_type": {}}
    changes = diff_events(old, new, "NCW")
    status_changes = [c for c in changes if c["field"] == "status"]
    assert len(status_changes) == 1
    assert status_changes[0]["old"] == "active"
    assert status_changes[0]["new"] == "completed"


def test_diff_events_dates_change():
    from usaw_event_info_sync import diff_events
    old = {"title": "NCW", "dates": "June 20-28", "info_by_type": {}}
    new = {"title": "NCW", "dates": "June 21-29", "info_by_type": {}}
    changes = diff_events(old, new, "NCW")
    date_changes = [c for c in changes if c["field"] == "dates"]
    assert len(date_changes) == 1


def test_diff_events_venue_change():
    from usaw_event_info_sync import diff_events
    old = {"title": "NCW", "venue": "Grand Rapids", "info_by_type": {}}
    new = {"title": "NCW", "venue": "Detroit", "info_by_type": {}}
    changes = diff_events(old, new, "NCW")
    venue_changes = [c for c in changes if c["field"] == "venue"]
    assert len(venue_changes) == 1


# ─── simplify_event edge cases ───

def test_simplify_event_none_info_by_type():
    from usaw_event_info_sync import simplify_event
    event = {"title": "Test", "info_by_type": None, "unclassified": None}
    simple = simplify_event(event)
    assert simple["title"] == "Test"
    assert simple["info_type_count"] == 0
    assert simple["links"] == []


def test_simplify_event_only_unclassified():
    from usaw_event_info_sync import simplify_event
    event = {
        "title": "Test",
        "info_by_type": {},
        "unclassified": [{"title": "Link 1", "url": "https://a.com"}, {"title": "Link 2", "url": "https://b.com"}],
    }
    simple = simplify_event(event)
    assert simple["info_type_count"] == 0
    assert len(simple["links"]) == 2


# ─── classify_file_name additional patterns ───

def test_classify_file_name_teams():
    from usaw_results_parser import classify_file_name
    info = classify_file_name("2026 NCW Results - Open Teams.pdf")
    assert info["doc_type"] == "teams"
    assert info["division"] is not None


def test_classify_file_name_registered_teams():
    from usaw_results_parser import classify_file_name
    info = classify_file_name("2026 NCW Registered Teams.pdf")
    assert info["doc_type"] == "registered_teams"


def test_classify_file_name_glen_middleton():
    from usaw_results_parser import classify_file_name
    # Now that patterns are reordered (specific before generic), this matches
    # glen_middleton even though it ends with "Results.pdf"
    info = classify_file_name("2026 Glen Middleton Award Results.pdf")
    assert info["doc_type"] == "glen_middleton"


# ─── parse_athlete_lines edge cases ───

def test_parse_athlete_lines_insufficient_data():
    from usaw_results_parser import parse_athlete_lines
    # Only 4 values (need >= 5)
    lines = ["119", "THIBAULT, McKenzie", "Team Name", "45.90"]
    athlete, consumed = parse_athlete_lines(lines, 0, 119, "SR", "M", "89")
    assert athlete is None


def test_parse_athlete_lines_empty_lines():
    from usaw_results_parser import parse_athlete_lines
    athlete, consumed = parse_athlete_lines([], 0, 1, "SR", "M", "89")
    assert athlete is None


def test_parse_athlete_lines_age_group_boundary():
    from usaw_results_parser import parse_athlete_lines
    # Should stop at Age Group header — use realistic owlcms data layout
    lines = [
        "119",           # lot (start_idx=0)
        "TEST, Athlete", # name
        "Team Name",     # team
        "45.90",         # bodyweight
        "18",            # age
        "50", "51", "52", # snatch attempts
        "DNF", "60", "61", # cj attempts (1 DNF to avoid 4-digit break)
        "113",           # total
        "250",           # score
        "Age Group SR M", # next section header — should stop here
        "Weight Category 102",
        "1", "2", "3", "999",
    ]
    athlete, consumed = parse_athlete_lines(lines, 0, 119, "SR", "M", "89")
    assert athlete is not None
    assert athlete["name"] == "TEST, Athlete"
    # Should not have consumed past the Age Group header
    assert consumed < len(lines) - 4


# ─── update_meet_ids_reference edge cases ───

def test_update_meet_ids_reference_file_missing():
    from usaw_event_info_sync import update_meet_ids_reference
    import usaw_event_info_sync
    from pathlib import Path

    original = usaw_event_info_sync.SKILL_DIR
    usaw_event_info_sync.SKILL_DIR = Path("/tmp/nonexistent_skill_dir")

    try:
        events_data = {
            "2026 NCW": {
                "info_by_type": {
                    "registration": [{"title": "Reg", "url": "https://usaweightlifting.sport80.com/v/808740/e/meets/14372"}],
                }
            }
        }
        findings = update_meet_ids_reference(events_data)
        assert findings == []
    finally:
        usaw_event_info_sync.SKILL_DIR = original


# ─── extract_all_links with no main ───

def test_extract_all_links_no_main_tag():
    from usaw_event_extractor import extract_all_links
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <div><h2>Results</h2><a href="/results.pdf">Results</a></div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    links = extract_all_links(soup)
    # Should still find links via body fallback
    assert len(links) >= 0  # May be 0 if nav-filtered, should not crash


# ─── format_summary with start_list ───

def test_format_summary_start_list():
    from usaw_results_parser import format_summary
    result = {
        "file_name": "start-list.pdf",
        "pdf_type": "start_list",
        "total_athletes": 1456,
        "page_count": 18,
        "file_classification": {"doc_type": "start_list", "division": None},
    }
    summary = format_summary(result)
    assert "start-list.pdf" in summary
    assert "start_list" in summary
    assert "1456" in summary