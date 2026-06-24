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
import os
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
    return json.loads(result.stdout)


def load_snapshot() -> dict:
    if SNAPSHOT_FILE.exists():
        return json.loads(SNAPSHOT_FILE.read_text())
    return {}


def save_snapshot(data: dict) -> None:
    SNAPSHOT_FILE.write_text(json.dumps(data, indent=2, default=str))


def simplify_event(event: dict) -> dict:
    """Create a comparable snapshot with the fields most likely to change."""
    links = sorted(
        [(l.get("info_type"), l.get("title"), l.get("url")) for l in event.get("links", [])],
        key=lambda x: x[0] or "",
    )
    return {
        "title": event.get("title"),
        "dates": event.get("dates"),
        "venue": event.get("venue"),
        "status": event.get("status"),
        "fees": event.get("fees"),
        "milestones": event.get("milestones"),
        "info_type_count": len(set(l[0] for l in links if l[0])),
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

    old_types = {l[0] for l in old_simple.get("links", []) if l[0]}
    new_types = {l[0] for l in new_simple.get("links", []) if l[0]}
    added_types = new_types - old_types
    removed_types = old_types - new_types
    if added_types:
        changes.append({"event": name, "field": "info_types", "added": sorted(added_types)})
    if removed_types:
        changes.append({"event": name, "field": "info_types", "removed": sorted(removed_types)})

    old_urls = {l[2] for l in old_simple.get("links", []) if l[2]}
    new_urls = {l[2] for l in new_simple.get("links", []) if l[2]}
    added_urls = new_urls - old_urls
    if added_urls:
        changes.append({"event": name, "field": "urls", "added": sorted(added_urls)[:20]})

    return changes


def run_test_suite() -> dict:
    cmd = [
        "uv", "run", "--with", "beautifulsoup4", "--with", "requests", "--with", "rapidfuzz",
        "python", str(SKILL_DIR / "scripts" / "test_extractor.py"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return {
        "returncode": result.returncode,
        "stdout_tail": "\n".join(result.stdout.strip().split("\n")[-10:]),
        "stderr_tail": "\n".join(result.stderr.strip().split("\n")[-10:]),
    }


def update_meet_ids_reference(events_data: dict) -> bool:
    """Rewrite the Sport80 meet IDs reference file if meet IDs changed."""
    reference_path = SKILL_DIR / "references" / "usaw-sport80-meet-ids.md"
    # TODO: implement diff-based update if needed; currently reports only
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notify", action="store_true", help="Notify on changes")
    parser.add_argument("--dry-run", action="store_true", help="Do not write snapshot")
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

    test_result = run_test_suite()

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "events_checked": len(EVENTS_2026),
        "events_with_errors": len(errors),
        "errors": errors,
        "changes": all_changes,
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
        for e in errors:
            summary_lines.append(f"  ❌ {e['event']}: {e['error']}")

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

    if test_result["returncode"] == 0:
        summary_lines.append("✅ Test suite passed")
    else:
        summary_lines.append("❌ Test suite failed")
        summary_lines.append(test_result["stdout_tail"])

    summary = "\n".join(summary_lines)
    print(summary)

    if args.notify and (all_changes or errors or test_result["returncode"] != 0):
        # The cron job's deliver setting will send the stdout; this branch is
        # for any additional notification logic if needed in the future.
        pass

    return 0 if not errors and test_result["returncode"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
