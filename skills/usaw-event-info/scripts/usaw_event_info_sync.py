#!/usr/bin/env python3
"""
USAW Event Info Sync — daily refresh script.

Re-runs the extractor on all known 2026 USAW national event pages, compares
to the previous snapshot, updates reference files if needed, runs the test
suite, and reports any new/changed information.

This script is intentionally conservative:
- Only updates reference files if a change is detected.
- Reports new/changed info_types, URLs, dates, venues, and Sport80 meet IDs.
- Does NOT post to external platforms unless --notify is passed.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 2026 national event pages to monitor
EVENTS_2026 = [
    ("2026 National Championships", "https://www.usaweightlifting.org/2026-national-championships"),
    ("2026 VIRUS Weightlifting Series 1", "https://www.usaweightlifting.org/2026-virus-weightlifting-series-1"),
    ("2026 Masters + University Nationals", "https://www.usaweightlifting.org/2026-masters-national-championships-national-university-championships"),
    ("2026 VIRUS Weightlifting Series 2", "https://www.usaweightlifting.org/2026-virus-weightlifting-series-2-championships"),
    ("2026 VIRUS Weightlifting Finals", "https://www.usaweightlifting.org/2026-virus-weightlifting-finals"),
    ("2026 Wodapalooza SoCal", "https://www.usaweightlifting.org/2026-usaw-x-gymreapers-wodapalooza-socal"),
]

SKILL_DIR = Path("/opt/data/skills/sports/usaw-event-info")
SNAPSHOT_FILE = SKILL_DIR / "scripts" / "last_snapshot.json"
REPORT_FILE = SKILL_DIR / "scripts" / "sync_report.json"


def run_extractor(url: str) -> dict:
    cmd = [
        "uv", "run", "--with", "beautifulsoup4", "--with", "requests", "--with", "rapidfuzz",
        "python", str(SKILL_DIR / "scripts" / "usaw_event_extractor.py"), "--json", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Extractor failed for {url}: {result.stderr}")
    data = json.loads(result.stdout)
    # Page-health check: verify the extracted page has expected content
    health = check_page_health(data, url)
    if not health["healthy"]:
        data["_health_warnings"] = health["issues"]
    return data


def check_page_health(event_data: dict, url: str) -> dict:
    """Check if an extracted event page has expected content.

    Returns {'healthy': bool, 'issues': [str]}.
    Advisory only — does not block sync, but issues are surfaced in the report.
    """
    issues = []
    sections = event_data.get("sections") or []
    if not sections:
        issues.append("zero sections extracted")
    total_links = sum(len(s.get("links", [])) for s in sections)
    if total_links < 5:
        issues.append(f"low link count ({total_links})")
    # Check for at least one classified info type
    classified = [s for s in sections for link in s.get("links", []) if link.get("info_type")]
    if not classified:
        issues.append("zero classified links")
    return {"healthy": len(issues) == 0, "issues": issues}


def load_snapshot() -> dict:
    if SNAPSHOT_FILE.exists():
        return json.loads(SNAPSHOT_FILE.read_text())
    return {}


def save_snapshot(data: dict) -> None:
    SNAPSHOT_FILE.write_text(json.dumps(data, indent=2, default=str))


def simplify_event(event: dict) -> dict:
    """Create a comparable snapshot with the fields most likely to change.

    L1 fix: The extractor returns info_by_type (dict of lists) and unclassified
    (list), not a flat 'links' key. Flatten both into a comparable link list.
    """
    # Flatten info_by_type + unclassified into a single link list
    all_links = []
    for info_type, items in (event.get("info_by_type") or {}).items():
        for item in items:
            all_links.append((info_type, item.get("title", ""), item.get("url", "")))
    for item in event.get("unclassified") or []:
        all_links.append((None, item.get("title", ""), item.get("url", "")))

    links = sorted(all_links, key=lambda x: x[0] or "")
    return {
        "title": event.get("title"),
        "dates": event.get("dates"),
        "venue": event.get("venue"),
        "status": event.get("status"),
        "fees": event.get("fees"),
        "milestones": event.get("milestones"),
        "info_type_count": len(set(link[0] for link in links if link[0])),
        "links": links,
    }


def diff_events(old: dict | None, new: dict, name: str) -> list:
    changes = []
    old_simple = simplify_event(old) if old else {}
    new_simple = simplify_event(new)

    for key in ["title", "dates", "venue", "status"]:
        if old_simple.get(key) != new_simple.get(key):
            changes.append({
                "event": name,
                "field": key,
                "old": old_simple.get(key),
                "new": new_simple.get(key),
            })

    old_types = {link[0] for link in old_simple.get("links", []) if link[0]}
    new_types = {link[0] for link in new_simple.get("links", []) if link[0]}
    added_types = new_types - old_types
    removed_types = old_types - new_types
    if added_types:
        changes.append({"event": name, "field": "info_types", "added": sorted(added_types)})
    if removed_types:
        changes.append({"event": name, "field": "info_types", "removed": sorted(removed_types)})

    old_urls = {link[2] for link in old_simple.get("links", []) if link[2]}
    new_urls = {link[2] for link in new_simple.get("links", []) if link[2]}
    added_urls = new_urls - old_urls
    if added_urls:
        changes.append({"event": name, "field": "urls", "added": sorted(added_urls)[:20]})

    return changes


def run_test_suite(live: bool = False) -> dict:
    """Run test suite. Defaults to mock (offline, <1s) to avoid network flakiness.

    L4 fix: Previously ran live tests (11 network fetches) on every daily run.
    Now uses mock tests by default. Pass live=True or --with-live-tests for live.
    """
    test_file = "test_extractor.py" if live else "test_extractor_mock.py"
    cmd = [
        "uv", "run", "--with", "beautifulsoup4", "--with", "requests", "--with", "rapidfuzz",
        "python", str(SKILL_DIR / "scripts" / test_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return {
        "test_type": "live" if live else "mock",
        "returncode": result.returncode,
        "stdout_tail": "\n".join(result.stdout.strip().split("\n")[-10:]),
        "stderr_tail": "\n".join(result.stderr.strip().split("\n")[-10:]),
    }


def update_meet_ids_reference(events_data: dict) -> list:
    """L5 fix: Detect Sport80 meet ID drift by comparing extracted IDs to reference file.

    Returns a list of drift findings (empty = no drift). Does NOT auto-update
    the reference file — just reports so a human can verify and update.
    """
    ref_path = SKILL_DIR / "references" / "usaw-sport80-meet-ids.md"
    if not ref_path.exists():
        return []

    ref_text = ref_path.read_text()
    import re
    # Extract all known meet IDs from the reference file (4-5 digit numbers in backticks)
    known_ids = set(re.findall(r'`(\d{4,6})`', ref_text))

    findings = []
    for event_name, event_data in events_data.items():
        info_by_type = event_data.get("info_by_type", {})
        for info_type, items in info_by_type.items():
            for item in items:
                url = item.get("url", "")
                # Extract meet ID from Sport80 URLs
                meet_match = re.search(r'meets/(\d{4,6})', url)
                if not meet_match:
                    meet_match = re.search(r'wizard/e/(\d{4,6})', url)
                if meet_match:
                    meet_id = meet_match.group(1)
                    if meet_id not in known_ids:
                        findings.append({
                            "event": event_name,
                            "info_type": info_type,
                            "meet_id": meet_id,
                            "url": url,
                            "title": item.get("title", ""),
                        })

    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip writing snapshot")
    parser.add_argument("--with-live-tests", action="store_true", help="Run live network tests instead of mock")
    args = parser.parse_args()

    snapshot = load_snapshot()
    new_snapshot = {}
    all_changes = []
    errors = []

    for name, url in EVENTS_2026:
        try:
            event_data = run_extractor(url)
            new_snapshot[name] = event_data
            changes = diff_events(snapshot.get(name), event_data, name)
            all_changes.extend(changes)
        except Exception as e:
            errors.append({"event": name, "error": str(e)})
            # L13 fix: Carry forward old snapshot to avoid spurious diffs on next run.
            # Without this, the failed event is absent from new_snapshot, so next run
            # treats it as a new event and reports every link as "added".
            if snapshot.get(name):
                new_snapshot[name] = snapshot[name]

    test_result = run_test_suite(live=args.with_live_tests)

    # L5: Check for Sport80 meet ID drift
    meet_id_drift = update_meet_ids_reference(new_snapshot)

    # Collect health warnings from all events
    health_warnings = {}
    for name, data in new_snapshot.items():
        if isinstance(data, dict) and data.get("_health_warnings"):
            health_warnings[name] = data["_health_warnings"]
            del data["_health_warnings"]  # Don't persist in snapshot

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "events_checked": len(EVENTS_2026),
        "events_with_errors": len(errors),
        "events_with_health_warnings": len(health_warnings),
        "health_warnings": health_warnings,
        "errors": errors,
        "changes": all_changes,
        "meet_id_drift": meet_id_drift,
        "test_result": test_result,
    }

    if not args.dry_run:
        save_snapshot(new_snapshot)
        REPORT_FILE.write_text(json.dumps(report, indent=2, default=str))

    # Human-readable summary
    summary_lines = [f"USAW Event Info Sync — {report['run_at']}"]
    summary_lines.append(f"Events checked: {report['events_checked']}")
    if errors:
        summary_lines.append(f"Errors: {len(errors)}")
        for err in errors:
            summary_lines.append(f"  ❌ {err['event']}: {err['error']}")

    if all_changes:
        summary_lines.append(f"Changes detected: {len(all_changes)}")
        for c in all_changes:
            if "added" in c:
                summary_lines.append(f"  📌 {c['event']}: +{c['field']} {c.get('added') or c.get('new')}")
            elif "removed" in c:
                summary_lines.append(f"  🗑️ {c['event']}: -{c['field']} {c.get('removed')}")
            else:
                summary_lines.append(f"  📝 {c['event']}: {c['field']} {c.get('old')} → {c.get('new')}")
    else:
        summary_lines.append("No changes detected.")

    if meet_id_drift:
        summary_lines.append(f"⚠️  Meet ID drift: {len(meet_id_drift)} new/unrecognized ID(s)")
        for d in meet_id_drift:
            summary_lines.append(f"  🔑 {d['event']}: {d['meet_id']} ({d['info_type']}) — {d['title']}")

    if test_result["returncode"] == 0:
        summary_lines.append(f"✅ Test suite passed ({test_result.get('test_type', 'mock')})")
    else:
        summary_lines.append(f"❌ Test suite failed ({test_result.get('test_type', 'mock')})")
        summary_lines.append(test_result["stdout_tail"])

    summary = "\n".join(summary_lines)
    print(summary)

    # Summary is printed to stdout; cron delivery handles notification.
    # Exit code: 0 = clean, 1 = errors or test failures
    return 0 if not errors and test_result["returncode"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
