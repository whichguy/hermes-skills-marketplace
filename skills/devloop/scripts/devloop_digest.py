#!/usr/bin/env python3
"""devloop_digest.py — script-first daily digest of devloop runs.

Scans devloop-traces/ for runs in the last 24h, parses trace.jsonl + grounding.json
from each, and emits a markdown summary: run count, terminal breakdown (COMPLETE vs
HUMAN_REVIEW vs failure), avg/p95 wall-clock, failure-mode buckets, and learning
themes from LEARNINGS.jsonl.

Design principles:
  - Script-first, no LLM calls (Jim's cron preference: silent on empty, no-agent).
  - Silent on empty: zero stdout when no runs found in the window.
  - Schema-version check: exit with a visible warning on trace schema mismatch.
  - Works with existing trace.jsonl (does NOT require progress.jsonl — that's the
    integration follow-up after Piece A lands).

Usage:
  python3 scripts/devloop_digest.py [--traces-dir DIR] [--hours N] [--json]
  python3 scripts/devloop_digest.py --traces-dir /opt/data/devloop-traces --hours 24

Exit codes:
  0 = digest emitted (or silent on empty)
  1 = error (bad traces dir, schema mismatch)
"""

from __future__ import annotations
from collections import Counter, defaultdict


import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Schema version for trace.jsonl events.
# Bump this when the trace schema changes. The digest script validates
# that events have the expected "step" field before parsing.
TRACE_SCHEMA_VERSION = 1
EXPECTED_STEPS = {
    "charter", "ambiguity_gate", "coverage", "quality_lint", "judge",
    "frozen_tests", "lint_discovery", "backoff", "test_redesign", "test_repair",
    "implement", "lint", "evidence", "stop_check", "regression",
    "rebuild_fail", "replan", "overfit_audit", "commit_scope",
    "grounding", "terminal", "attribution",
}

# ── Terminal categories for the breakdown
TERMINAL_CATEGORIES = ("COMPLETE", "HUMAN_REVIEW", "NO_TERMINATION")


def _parse_progress(progress_path: Path) -> dict | None:
    """Parse a progress.jsonl file into a run summary dict.

    Returns None on corrupt/empty traces. Does NOT raise — one bad trace
    should not poison the digest.
    
    Progress.jsonl format (from loop.py):
        {"ts": timestamp, "step": phase-name, "detail": "", "ok": bool|null, "elapsed_s": float}
    """
    if not progress_path.exists() or progress_path.stat().st_size == 0:
        return None

    events = []
    try:
        with open(progress_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                events.append(event)
    except (json.JSONDecodeError, OSError):
        return None

    if not events:
        return None

    # Extract terminal from last progress step or "complete" ending
    terminal = "COMPLETE"
    reason = ""
    
    # Find the last step to determine terminal status
    for ev in reversed(events):
        step = ev.get("step", "")
        ok = ev.get("ok")
        if step == "complete":
            terminal = "COMPLETE"
            break
        elif ok is False:
            # A failed step indicates HUMAN_REVIEW or failure
            terminal = "HUMAN_REVIEW"
            reason = f"failed at {step}"
            break
    
    # Wall-clock duration from progress data
    durations = [e.get("elapsed_s") for e in events if e.get("elapsed_s") is not None]
    duration_s = durations[-1] if durations else None

    # First timestamp as run_dt
    ts_first = None
    run_dt = None
    for ev in events:
        ts = ev.get("ts")
        if ts is not None:
            ts_first = ts
            break
    if ts_first is not None:
        try:
            run_dt = datetime.fromtimestamp(ts_first, tz=timezone.utc)
        except (OSError, ValueError):
            pass

    # Fill in defaults since progress.jsonl doesn't have all fields
    return {
        "terminal": terminal,
        "reason": reason or "",
        "intent": "",
        "n_criteria": 0,
        "duration_s": round(duration_s, 1) if duration_s else None,
        "rebuilds": 0,
        "overfit_suspects": [],
        "judge_verdicts": None,
        "evidence_results": [],
        "run_dt": run_dt,
        "_schema_mismatch": False,
    }


def _parse_trace(trace_path: Path) -> dict | None:
    """Parse a trace.jsonl file into a run summary dict.

    Returns None on corrupt/empty traces. Does NOT raise — one bad trace
    should not poison the digest.
    """
    if not trace_path.exists() or trace_path.stat().st_size == 0:
        return None

    events = []
    schema_ok = True
    try:
        with open(trace_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                step = event.get("step", "")
                if step and step not in EXPECTED_STEPS:
                    schema_ok = False
                events.append(event)
    except (json.JSONDecodeError, OSError):
        return None

    if not events:
        return None

    if not schema_ok:
        # Schema mismatch — return a marker so the digest can warn
        return {"_schema_mismatch": True, "_path": str(trace_path)}

    # Extract terminal
    terminal = None
    reason = None
    intent = None
    n_criteria = 0
    judge_verdicts = None
    evidence_results = []
    ts_first = None
    ts_last = None
    rebuilds = 0
    overfit_suspects = []

    for ev in events:
        step = ev.get("step", "")
        ts = ev.get("ts")

        if ts is not None:
            if ts_first is None or ts < ts_first:
                ts_first = ts
            if ts_last is None or ts > ts_last:
                ts_last = ts

        if step == "charter":
            intent = ev.get("intent", "")
            n_criteria = ev.get("n_criteria", 0)
        elif step == "judge":
            judge_verdicts = ev.get("verdicts", [])
        elif step == "evidence":
            evidence_results.append({
                "criterion": ev.get("criterion", ""),
                "passed": ev.get("passed", False),
                "exit": ev.get("exit", None),
            })
        elif step == "rebuild_fail":
            rebuilds += 1
        elif step == "overfit_audit":
            overfit_suspects = ev.get("suspect", [])
        elif step == "terminal":
            terminal = ev.get("terminal", "")
            reason = ev.get("reason", "")

    if terminal is None:
        # No terminal event — run was interrupted
        terminal = "INTERRUPTED"

    # Wall-clock duration
    duration_s = None
    if ts_first is not None and ts_last is not None:
        duration_s = round(ts_last - ts_first, 1)

    # Parse timestamp for the run
    run_dt = None
    if ts_first is not None:
        try:
            run_dt = datetime.fromtimestamp(ts_first, tz=timezone.utc)
        except (OSError, ValueError):
            pass

    return {
        "terminal": terminal,
        "reason": reason or "",
        "intent": intent or "",
        "n_criteria": n_criteria,
        "duration_s": duration_s,
        "rebuilds": rebuilds,
        "overfit_suspects": overfit_suspects,
        "judge_verdicts": judge_verdicts,
        "evidence_results": evidence_results,
        "run_dt": run_dt,
        "_schema_mismatch": False,
    }


def _parse_grounding(grounding_path: Path) -> dict | None:
    """Parse grounding.json if it exists."""
    if not grounding_path.exists() or grounding_path.stat().st_size == 0:
        return None
    try:
        with open(grounding_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _parse_learnings(learnings_path: Path, hours: int, now: datetime) -> list[dict]:
    """Parse LEARNINGS.jsonl for entries in the last N hours."""
    if not learnings_path.exists() or learnings_path.stat().st_size == 0:
        return []

    entries = []
    cutoff = now - timedelta(hours=hours)
    try:
        with open(learnings_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Parse the timestamp
                ts_str = entry.get("ts", "")
                entry_dt = None
                if ts_str:
                    try:
                        # ISO 8601 format: 2026-07-07T13:06:20.050511+00:00
                        entry_dt = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        pass
                if entry_dt and entry_dt >= cutoff:
                    entries.append(entry)
    except OSError:
        pass
    return entries


def _scan_traces(traces_dir: Path, hours: int, now: datetime) -> list[dict]:
    """Scan the traces directory for runs in the last N hours."""
    cutoff = now - timedelta(hours=hours)
    runs = []

    if not traces_dir.exists() or not traces_dir.is_dir():
        return runs

    for entry in traces_dir.iterdir():
        if not entry.is_dir():
            continue
        # Skip the LEARNINGS.jsonl file (it's a file, not a dir, but be safe)
        if entry.name.startswith("LEARNINGS"):
            continue

        # Prefer progress.jsonl if available (richer data), fallback to trace.jsonl
        progress_path = entry / "progress.jsonl"
        trace_path = entry / "trace.jsonl"

        run_data = None
        if progress_path.exists():
            run_data = _parse_progress(progress_path)
        elif trace_path.exists():
            # Some trace dirs may not have trace.jsonl (e.g. scout-only runs)
            run_data = _parse_trace(trace_path)

        if run_data is None:
            continue
        run_data["trace_dir"] = entry.name

        # Filter by time window
        run_dt = run_data.get("run_dt")
        if run_dt and run_dt < cutoff:
            continue

        # Enrich with grounding (only available with trace.jsonl fallback path)
        grounding = _parse_grounding(entry / "grounding.json")
        if grounding:
            run_data["grounding"] = grounding

        runs.append(run_data)

    return runs


def _format_duration(seconds: float | None) -> str:
    """Format seconds into a human-readable duration."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m{secs}s"


def _percentile(data: list[float], pct: float) -> float | None:
    """Simple percentile calculation."""
    if not data:
        return None
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def generate_digest(runs: list[dict], learnings: list[dict], hours: int) -> str:
    """Generate the markdown digest from parsed runs + learnings."""
    if not runs and not learnings:
        return ""  # Silent on empty

    lines = []
    lines.append(f"## devloop digest — last {hours}h\n")

    # ── Run summary
    if runs:
        total = len(runs)
        terminals = Counter(r["terminal"] for r in runs)
        durations = [r["duration_s"] for r in runs if r["duration_s"] is not None]
        total_rebuilds = sum(r.get("rebuilds", 0) for r in runs)

        # Build terminal breakdown
        terminal_parts = []
        for cat in TERMINAL_CATEGORIES:
            count = terminals.get(cat, 0)
            if count:
                terminal_parts.append(f"{count} {cat}")
        for cat, count in terminals.items():
            if cat not in TERMINAL_CATEGORIES:
                terminal_parts.append(f"{count} {cat}")
        lines.append(f"**{total} run(s)**: " + ", ".join(terminal_parts) + "\n")

        # Timing
        if durations:
            avg = statistics.mean(durations)
            p95 = _percentile(durations, 95)
            lines.append(
                f"⏱ Wall-clock: avg {_format_duration(avg)}, p95 {_format_duration(p95)}\n"
            )

        if total_rebuilds:
            lines.append(f"🔧 Total rebuilds: {total_rebuilds}\n")

        # ── Per-run details
        lines.append("\n### Runs\n")
        for r in sorted(runs, key=lambda x: x.get("run_dt") or datetime.min.replace(tzinfo=timezone.utc)):
            dt = r.get("run_dt")
            dt_str = dt.strftime("%H:%M") if dt else "??"
            terminal = r["terminal"]
            icon = "✅" if terminal == "COMPLETE" else "🟡" if terminal == "HUMAN_REVIEW" else "❌"
            duration = _format_duration(r.get("duration_s"))
            intent = (r.get("intent", "") or "")[:80]
            lines.append(f"- {icon} `{dt_str}` {terminal} ({duration}) — {intent}")

            # Failure details
            if terminal == "HUMAN_REVIEW" and r.get("reason"):
                reason = r["reason"][:120]
                lines.append(f"  └ reason: {reason}")

            # Evidence failures
            failed_ev = [e for e in r.get("evidence_results", []) if not e.get("passed")]
            if failed_ev:
                failed_cids = [e["criterion"] for e in failed_ev if e.get("criterion")]
                if failed_cids:
                    lines.append(f"  └ failed: {', '.join(failed_cids)}")

            # Overfit suspects
            if r.get("overfit_suspects"):
                lines.append(f"  └ overfit: {', '.join(r['overfit_suspects'])}")

        # ── Failure mode buckets
        hr_runs = [r for r in runs if r["terminal"] == "HUMAN_REVIEW"]
        if hr_runs:
            lines.append("\n### Failure modes (HUMAN_REVIEW)\n")
            mode_counts = Counter()
            for r in hr_runs:
                reason = r.get("reason", "")
                if "test fault" in reason or "judge" in reason.lower():
                    mode_counts["test_fault"] += 1
                elif "quality" in reason.lower() or "lint" in reason.lower():
                    mode_counts["quality_lint"] += 1
                elif "overfit" in reason.lower():
                    mode_counts["overfit"] += 1
                elif "back-off" in reason.lower() or "exhausted" in reason.lower():
                    mode_counts["backoff_exhausted"] += 1
                elif "vague" in reason.lower():
                    mode_counts["vague_goal"] += 1
                elif "ambigu" in reason.lower():
                    mode_counts["ambiguity"] += 1
                else:
                    mode_counts["other"] += 1
            for mode, count in mode_counts.most_common():
                lines.append(f"- {mode}: {count}")

    # ── Learning themes
    if learnings:
        lines.append("\n### Learning themes\n")
        # Extract lesson topics from learnings entries
        lessons_text = []
        for entry in learnings:
            lesson = entry.get("lesson", "") or entry.get("learnings_text", "")
            if lesson:
                lessons_text.append(lesson.strip())
        if lessons_text:
            # Show up to 5 recent learnings (truncated)
            for i, lesson in enumerate(lessons_text[-5:]):
                one_line = lesson.split("\n")[0][:120]
                lines.append(f"- {one_line}")
            if len(lessons_text) > 5:
                lines.append(f"_...and {len(lessons_text) - 5} more_")

    # ── Schema warnings
    schema_mismatches = [r for r in runs if r.get("_schema_mismatch")]
    if schema_mismatches:
        lines.append("\n### ⚠️ Schema warnings\n")
        for r in schema_mismatches:
            lines.append(f"- `{r.get('trace_dir', '?')}`: trace schema mismatch (may need digest update)")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="devloop digest — script-first daily summary of devloop runs"
    )
    parser.add_argument(
        "--traces-dir",
        default=os.environ.get("DEVLOOP_TRACES_DIR",
                               os.path.join(os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data"),
                                            "devloop-traces")),
        help="Path to devloop-traces/ directory",
    )
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back (default: 24)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    args = parser.parse_args()

    traces_dir = Path(args.traces_dir)
    now = datetime.now(timezone.utc)

    runs = _scan_traces(traces_dir, args.hours, now)
    learnings_path = traces_dir / "LEARNINGS.jsonl"
    learnings = _parse_learnings(learnings_path, args.hours, now)

    # Check for schema mismatches
    schema_mismatches = [r for r in runs if r.get("_schema_mismatch")]
    if schema_mismatches:
        for r in schema_mismatches:
            print(f"⚠️  Schema mismatch in {r.get('trace_dir', '?')}", file=sys.stderr)

    if args.json:
        output = json.dumps({
            "runs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in runs],
            "learnings_count": len(learnings),
            "hours": args.hours,
            "generated_at": now.isoformat(),
        }, indent=2, default=str)
        print(output)
    else:
        digest = generate_digest(runs, learnings, args.hours)
        if digest:
            print(digest)
        # Silent on empty — no output at all

    # Exit 0 always (schema warnings go to stderr but don't fail)
    sys.exit(0)


if __name__ == "__main__":
    main()