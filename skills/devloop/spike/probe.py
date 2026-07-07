#!/usr/bin/env python3
"""Ad-hoc single-task spike runner for INCREMENTAL iteration.

Run one task against the real native loop, SAVE a full transcript, and surface fidelity
issues for fast learn/debug. This is the experimentation tool; run_spike.py is the formal
acceptance bar. Distilled learnings go in spike/ITERATIONS.md.

Examples (inside the container, or with HERMES_BIN set):
  python3 spike/probe.py --request "add cursor pagination to /orders and /invoices" --touches api/orders.py,api/invoices.py
  python3 spike/probe.py --request "make it faster" --expect-human-review     # negative path
  python3 spike/probe.py --task-file mytask.json
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_spike  # noqa: E402

TDIR = Path(__file__).resolve().parent.parent / ".devloop" / "transcripts"


def fidelity_flags(raw: str, verdict: dict) -> list[str]:
    """Cheap anomaly surface so we don't have to eyeball every transcript."""
    flags = []
    if verdict["phase_skips"]:
        flags.append(f"phase_skips={verdict['phase_skips']}")
    if verdict["wandered"]:
        flags.append("wandered (phases out of order)")
    if not verdict["gated_stop_ok"]:
        flags.append("forged COMPLETE (reported done without green evidence)")
    if not verdict["human_review_ok"]:
        flags.append("human-review expectation mismatch")
    if "[DEVLOOP-SPIKE]" not in raw:
        flags.append("NO protocol markers — model ignored the skill prose")
    if raw.count("STOP=COMPLETE") > 1:
        flags.append(f"multiple STOP markers ({raw.count('STOP=COMPLETE')})")
    if "SUGGESTION:" in raw:
        flags.append("runtime SUGGESTION trailer present (benign)")
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description="incremental spike probe")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--request", help="the fuzzy task request")
    g.add_argument("--task-file", help="JSON file with a task object")
    ap.add_argument("--touches", default="", help="comma-separated likely files")
    ap.add_argument("--repo", default="")
    ap.add_argument("--model", default=run_spike.SPIKE_MODEL)
    ap.add_argument("--expect-human-review", action="store_true")
    ap.add_argument("--label", default="probe", help="short id for the transcript filename")
    args = ap.parse_args()

    if args.task_file:
        task = json.loads(Path(args.task_file).read_text())
    else:
        task = {"id": args.label, "request": args.request, "repo": args.repo,
                "touches": [t for t in args.touches.split(",") if t],
                "expect_human_review": args.expect_human_review}

    s = time.time()
    out = run_spike.run_one(task, model=args.model)
    elapsed = round(time.time() - s, 1)

    verdict = run_spike.analyze({**out, "task_id": task.get("id", "probe"), "run_idx": 0,
                                 "expect_human_review": task.get("expect_human_review", False)})
    raw = out.get("raw", "")
    vslim = {k: verdict[k] for k in ("phase_skips", "wandered", "gated_stop_ok", "human_review_ok", "verdict")}
    flags = fidelity_flags(raw, verdict)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    TDIR.mkdir(exist_ok=True)
    rec = {"ts": ts, "task": task, "model": args.model, "elapsed_sec": elapsed,
           "exit_note": out.get("notes"),
           "parsed": {k: out.get(k) for k in
                      ("phase_trace", "reported_complete", "evidence_all_green", "entered_human_review")},
           "verdict": vslim, "fidelity_flags": flags, "raw": raw}
    path = TDIR / f"{ts}_{task.get('id', 'probe')}.json"
    path.write_text(json.dumps(rec, indent=2))

    print("=" * 60, "\nRAW OUTPUT\n" + "=" * 60)
    print(raw or "(empty)")
    print("=" * 60, f"\nVERDICT ({elapsed}s, {out.get('notes')})\n" + "=" * 60)
    print(json.dumps(vslim, indent=2))
    print("=" * 60, "\nFIDELITY FLAGS\n" + "=" * 60)
    print("\n".join(f"  - {f}" for f in flags) if flags else "  (none — clean run)")
    print(f"\nsaved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
