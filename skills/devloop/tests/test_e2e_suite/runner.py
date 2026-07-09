"""E2E Suite Runner — runs each E2E scenario one at a time and evaluates results.

Usage:
    # Run all non-quarantined scenarios:
    python3 tests/test_e2e_suite/runner.py

    # Run a specific scenario:
    python3 tests/test_e2e_suite/runner.py test_simple_add

    # Run all including quarantined:
    DEVLOOP_RUN_MULTIFILE=1 python3 tests/test_e2e_suite/runner.py

    # Run with a specific number of repeats for diagnostic:
    python3 tests/test_e2e_suite/runner.py test_simple_add --repeat 3

The runner:
1. Runs each scenario as a subprocess (one at a time, isolated)
2. Captures the control channel (stderr markers) and data channel (stdout)
3. Parses the control channel for correlation IDs, marker pairing, crash markers
4. Checks judge_verdicts.jsonl for split votes and tiebreaker resolution
5. Produces a structured summary report

Output is written to /opt/data/devloop-diagnostics/e2e-suite-report.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_DIR = Path(__file__).parent
_DEVLOOP_DIR = _DIR.parent.parent
_DIAG_DIR = Path(os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data")) / "devloop-diagnostics"

# All scenarios in the suite — (name, file, quarantined)
SCENARIOS = [
    ("test_simple_add",      "test_simple_add.py",      False),
    ("test_string_reverse_words", "test_string_manip.py",  False),
    ("test_multi_function_calc",  "test_multi_function.py", False),
    ("test_fizzbuzz",        "test_conditional.py",     False),
    ("test_error_handling",  "test_error_handling.py",  False),
    ("test_class_stack",     "test_class_based.py",     False),
    ("test_flatten",         "test_data_transform.py",  False),
    ("test_json_config",     "test_json_config.py",     False),
    ("test_multifile",       "test_multifile.py",       True),
]


def run_scenario(scenario_name: str, scenario_file: str, quarantined: bool) -> dict:
    """Run one scenario as a pytest subprocess. Returns a result dict."""
    env = dict(os.environ)
    env["DEVLOOP_RUN_REAL"] = "1"
    env["DEVLOOP_PROGRESS"] = "verbose"
    if "HERMES_HOME" not in env:
        env["HERMES_HOME"] = "/opt/data"
    env["PATH"] = f"/opt/data/.local/bin:/opt/data/.venv/bin:{env.get('PATH', '')}"

    if quarantined and env.get("DEVLOOP_RUN_MULTIFILE") != "1":
        return {
            "scenario": scenario_name,
            "status": "skipped",
            "reason": "QUARANTINED — set DEVLOOP_RUN_MULTIFILE=1 to run",
            "duration_s": 0,
        }

    test_path = f"tests/test_e2e_suite/{scenario_file}::{scenario_name}"
    cmd = [
        "uv", "run", "--with", "pytest", "--with", "pyyaml",
        "--with", "sqlparse", "--with", "mypy",
        "python3", "-m", "pytest", test_path, "-v", "-s",
    ]

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(_DEVLOOP_DIR), env=env,
            capture_output=True, text=True, timeout=600,
        )
        elapsed = time.time() - t0
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - t0
        return {
            "scenario": scenario_name,
            "status": "timeout",
            "duration_s": round(elapsed, 1),
            "stdout": (e.stdout or "")[-2000:],
            "stderr": (e.stderr or "")[-2000:],
        }

    stdout = proc.stdout
    stderr = proc.stderr
    passed = proc.returncode == 0

    # Parse control channel markers from stderr
    markers = parse_markers(stderr)

    # Parse judge verdicts from the diagnostic log
    judge_verdicts = parse_recent_judge_verdicts(elapsed)

    return {
        "scenario": scenario_name,
        "status": "passed" if passed else "failed",
        "duration_s": round(elapsed, 1),
        "exit_code": proc.returncode,
        "markers": markers,
        "judge_verdicts": judge_verdicts,
        "stdout_tail": stdout[-2000:] if len(stdout) > 2000 else stdout,
        "stderr_tail": stderr[-2000:] if len(stderr) > 2000 else stderr,
    }


def parse_markers(stderr: str) -> dict:
    """Parse devloop control channel markers from stderr."""
    lines = [l.strip() for l in stderr.split("\n") if "[devloop]" in l]
    run_ids = set()
    begins = []
    ends = []
    crashes = []
    terminals = []
    enriched_details = []

    for line in lines:
        # Extract run ID
        m = re.search(r"\[devloop\] \[([0-9a-f]{8})\]", line)
        if m:
            run_ids.add(m.group(1))

        if "⏳" in line:
            begins.append(line)
        elif "✅" in line:
            ends.append(line)
        elif "❌" in line:
            if "HUMAN_REVIEW" in line or "crash" in line.lower():
                terminals.append(line)
            else:
                crashes.append(line)

        # Capture enriched details
        if any(k in line for k in ["file(s) changed:", "criteria trusted", "UNTRUSTED",
                                    "exit", "suspect", "merged:"]):
            enriched_details.append(line)

    return {
        "total_markers": len(lines),
        "run_ids": list(run_ids),
        "begin_count": len(begins),
        "end_count": len(ends),
        "crash_count": len(crashes),
        "terminals": terminals,
        "enriched_details": enriched_details[:10],  # cap for readability
    }


def parse_recent_judge_verdicts(within_seconds: float) -> list[dict]:
    """Read the persistent judge_verdicts.jsonl and return records from the last run."""
    path = _DIAG_DIR / "judge_verdicts.jsonl"
    if not path.exists():
        return []

    cutoff = time.time() - within_seconds - 5  # small buffer
    records = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("ts", 0) >= cutoff:
                        records.append(r)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    # Summarize
    if not records:
        return []

    split_votes = [r for r in records if r.get("split_vote")]
    tiebreaker_resolved = [r for r in records if r.get("tiebreaker") and r["tiebreaker"].get("vote") is not None]

    return {
        "total_verdicts": len(records),
        "split_votes": len(split_votes),
        "tiebreaker_resolved": len(tiebreaker_resolved),
        "criteria": list(set(r.get("criterion_id") for r in records)),
        "details": [
            {
                "criterion": r.get("criterion_id"),
                "judge_a": r.get("judge_a", {}).get("vote"),
                "judge_b": r.get("judge_b", {}).get("vote"),
                "split": r.get("split_vote"),
                "tiebreaker": r["tiebreaker"].get("vote") if r.get("tiebreaker") else None,
                "encodes": r.get("encodes"),
            }
            for r in records
        ][:20],  # cap
    }


def run_suite(scenarios: list[tuple[str, str, bool]], repeat: int = 1) -> list[dict]:
    """Run the full suite, one scenario at a time."""
    results = []
    for i in range(repeat):
        for name, file, quarantined in scenarios:
            print(f"\n{'='*60}")
            print(f"  RUNNING: {name}" + (f" (repeat {i+1}/{repeat})" if repeat > 1 else ""))
            print(f"  {'='*60}")
            result = run_scenario(name, file, quarantined)
            results.append(result)

            status_icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "timeout": "⏱️"}[result["status"]]
            duration = result.get("duration_s", 0)
            print(f"  {status_icon} {name}: {result['status']} ({duration}s)")

            if result["status"] == "passed":
                markers = result.get("markers", {})
                jv = result.get("judge_verdicts", {})
                if isinstance(jv, dict):
                    print(f"     Markers: {markers.get('total_markers', 0)} total, "
                          f"{markers.get('begin_count', 0)} begin, {markers.get('end_count', 0)} end")
                    print(f"     Judge: {jv.get('total_verdicts', 0)} verdicts, "
                          f"{jv.get('split_votes', 0)} splits, "
                          f"{jv.get('tiebreaker_resolved', 0)} tiebroken")
                enriched = markers.get("enriched_details", [])
                if enriched:
                    for d in enriched[:3]:
                        print(f"     {d}")
            elif result["status"] == "failed":
                print(f"     Exit code: {result.get('exit_code')}")
                stderr_tail = result.get("stderr_tail", "")
                if "HUMAN_REVIEW" in stderr_tail:
                    # Extract the reason
                    for line in stderr_tail.split("\n"):
                        if "HUMAN_REVIEW" in line:
                            print(f"     {line.strip()}")
                            break

    return results


def print_summary(results: list[dict]):
    """Print a summary table of all results."""
    print(f"\n{'='*60}")
    print("  E2E SUITE SUMMARY")
    print(f"  {'='*60}")
    print(f"  {'Scenario':<30} {'Status':<10} {'Duration':<10} {'Markers':<10} {'Splits':<8}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

    passed = failed = skipped = timeout = 0
    total_duration = 0
    total_splits = 0

    for r in results:
        status = r["status"]
        duration = r.get("duration_s", 0)
        total_duration += duration

        markers = r.get("markers", {})
        jv = r.get("judge_verdicts", {})
        splits = jv.get("split_votes", 0) if isinstance(jv, dict) else 0
        total_splits += splits

        icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "timeout": "⏱️"}[status]
        marker_count = markers.get("total_markers", 0) if isinstance(markers, dict) else 0

        print(f"  {r['scenario']:<30} {icon} {status:<8} {duration:<10.1f} {marker_count:<10} {splits:<8}")

        if status == "passed":
            passed += 1
        elif status == "failed":
            failed += 1
        elif status == "skipped":
            skipped += 1
        elif status == "timeout":
            timeout += 1

    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
    print(f"  TOTAL: {len(results)} | ✅ {passed} | ❌ {failed} | ⏭️ {skipped} | ⏱️ {timeout}")
    print(f"  Duration: {total_duration:.1f}s | Split votes: {total_splits}")

    # Write structured report
    _DIAG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _DIAG_DIR / "e2e-suite-report.json"
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": time.time(),
            "results": results,
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "timeout": timeout,
                "total_duration_s": round(total_duration, 1),
                "total_split_votes": total_splits,
            },
        }, f, indent=2, default=str)
    print(f"\n  Report: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Run the E2E suite one scenario at a time")
    parser.add_argument("scenario", nargs="?", help="Run a specific scenario by name")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat all scenarios N times")
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.scenario:
        scenarios = [(n, f, q) for n, f, q in SCENARIOS if n == args.scenario]
        if not scenarios:
            print(f"Unknown scenario: {args.scenario}")
            print(f"Available: {', '.join(n for n, _, _ in SCENARIOS)}")
            sys.exit(1)

    results = run_suite(scenarios, repeat=args.repeat)
    print_summary(results)

    # Exit non-zero if any failed
    if any(r["status"] == "failed" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()