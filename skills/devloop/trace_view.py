#!/usr/bin/env python3
"""trace_view.py — render a devloop run trace human-readably.

The real-run analog of the spike's probe.py: turn a JSONL trace
(<run_dir>/trace.jsonl, e.g. .devloop/runs/<id>/trace.jsonl) into the phase-by-phase
story — what the gates decided, where it iterated, why it stopped.

    python3 trace_view.py .devloop/runs/<id>/trace.jsonl

Renders EVERY event type; an unknown step falls through to a compact-JSON line instead of
being silently dropped (deep review 2026-07-01 — the old renderer dropped the judge/coverage/
stop_check/attribution/lint events, i.e. every v1 verification step was invisible).

(Named trace_view, NOT inspect — `inspect` would shadow Python's stdlib module on sys.path.)
"""
import json
import sys
from pathlib import Path


def _fmt_elapsed(e, t0):
    ts = e.get("ts")
    if ts is None or t0 is None:
        return ""
    return f"+{ts - t0:7.1f}s "


def render(trace_path) -> str:
    out = []
    t0 = None
    for line in Path(trace_path).read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if t0 is None and e.get("ts") is not None:
            t0 = e["ts"]
        p = _fmt_elapsed(e, t0)
        s = e.get("step")
        if s == "charter":
            out.append(f"{p}CHARTER  «{e.get('intent', '')[:160]}»  ({e.get('n_criteria')} criteria)")
            for c in e.get("dod") or []:
                out.append(f"      - {c.get('id')}: {c.get('criterion', '')[:120]}")
            for q in e.get("open_questions") or []:
                if isinstance(q, dict) and q.get("blocking"):
                    out.append(f"      ? BLOCKING: {q.get('text', '')[:120]}")
        elif s == "ambiguity_gate":
            out.append(f"{p}  gate.ambiguity_gate -> {e['decision']}  ({e['reason']})")
        elif s == "coverage":
            mark = "ok" if e.get("ok") else f"UNCOVERED {e.get('uncovered')}"
            out.append(f"{p}  dod_oracle.coverage -> {mark}")
        elif s == "judge":
            for v in e.get("verdicts") or []:
                mark = "trusted" if v.get("encodes") else ("ESCALATE" if v.get("escalate") else "REJECT")
                ab = f" a={v.get('judge_a')} b={v.get('judge_b')}" if "judge_a" in v else ""
                out.append(f"{p}  judge {v.get('criterion')}: {mark}{ab}")
        elif s == "attribution":
            out.append(f"{p}  ATTRIBUTION: {e.get('fault')} fault -> {e.get('criteria')}")
        elif s == "lint_discovery":
            cov = e.get("coverage") or {}
            have = [k for k, v in cov.items() if v] if isinstance(cov, dict) else cov
            out.append(f"{p}  lint discovery: {have}")
        elif s == "lint":
            mark = "ok" if e.get("ok") else f"FAIL ({len(e.get('failures') or [])} file(s))"
            out.append(f"{p}  lint attempt={e.get('attempt')}: {mark} "
                       f"(checked={e.get('checked')} skipped={e.get('skipped')})")
        elif s == "backoff":
            out.append(f"{p}  gate.backoff_exhausted -> {e['action']}  "
                       f"(rebuild={e['rebuild']} replan={e['replan']})")
        elif s == "replan":
            out.append(f"{p}  RE-PLAN  (replan={e['replan']})")
        elif s == "implement":
            dur = f" dur={e['dur_s']}s" if e.get("dur_s") is not None else ""
            line_ = f"{p}  IMPLEMENT  attempt={e['attempt']}{dur}"
            if e.get("summary"):
                line_ += "\n      coder: " + " ".join(e["summary"].split())[:180]
            out.append(line_)
        elif s == "evidence":
            mark = "PASS" if e["passed"] else "FAIL"
            l2 = f"{p}    evidence.run {e['criterion']}: exit={e['exit']} [{mark}]  $ {' '.join(e['cmd'])}"
            tail = (e.get("stderr_tail") or "").strip()
            if not e["passed"] and tail:
                l2 += f"\n        stderr: {tail.splitlines()[-1][:120]}"
            out.append(l2)
        elif s == "stop_check":
            out.append(f"{p}  gate.stop_condition -> {'COMPLETE-able' if e.get('complete') else 'not yet'}"
                       f"  ({e.get('reason', '')[:140]})")
        elif s == "regression":
            mark = "PASS" if e.get("passed") else "FAIL"
            out.append(f"{p}  REGRESSION (whole suite): exit={e.get('exit')} [{mark}]  ({e.get('reason', '')})")
        elif s == "rebuild_fail":
            cause = f" cause={e['cause']}" if e.get("cause") else ""
            out.append(f"{p}  -> red; rebuild_count={e['rebuild']}{cause}")
        elif s == "dispatch_error":
            out.append(f"{p}  DISPATCH ERROR: {e.get('reason', '')[:140]}")
        elif s == "terminal":
            tail = f"  ({e['reason']})" if e.get("reason") else ""
            out.append(f"{p}== {e['terminal']} =={tail}")
        else:
            # NEVER silently drop an event: unknown steps render as compact JSON.
            compact = json.dumps({k: v for k, v in e.items() if k != "ts"})[:200]
            out.append(f"{p}  {s or '?'}: {compact}")
    return "\n".join(out)


def chain(trace_path) -> str:
    """--chain: the per-criterion TDD chain (user ask 2026-07-03 — 'were the right intentions
    done?'): promise -> intention -> judge votes -> covering tests -> evidence per attempt ->
    terminal. `render` stays the chronological log; this is the same trace pivoted by
    criterion. Never drops a criterion: every DoD id from the charter event gets a block."""
    events = [json.loads(ln) for ln in Path(trace_path).read_text().splitlines() if ln.strip()]
    dod, tests, judges, evidence_by, terminal = [], {}, {}, {}, ""
    audits, repairs = {}, []
    for e in events:
        s = e.get("step")
        if s == "charter":
            dod = e.get("dod") or []
        elif s == "judge":
            for v in e.get("verdicts") or []:
                judges[v.get("criterion")] = v
        elif s == "evidence":
            evidence_by.setdefault(e.get("criterion"), []).append(e)
        elif s == "test_audit":
            for d in e.get("details") or []:
                if isinstance(d, dict) and d.get("criterion"):
                    audits[d["criterion"]] = d
        elif s == "test_repair" and e.get("ok"):
            repairs = e.get("criteria") or []
        elif s == "grounding":
            for it in e.get("criteria") or []:
                tests[it.get("criterion_id")] = it.get("tests") or []
        elif s == "terminal":
            terminal = f"{e.get('terminal')}" + (
                f" ({e.get('reason', '')[:120]})" if e.get("reason") else "")
    out = [f"TDD chain — terminal: {terminal or '?'}"]
    for c in dod:
        cid = c.get("id")
        out.append(f"\n{cid} [{c.get('tier') or 'unit'}]: {c.get('criterion', '')[:120]}")
        out.append(f"  intention: {c.get('verify_intent', '')[:120]}")
        v = judges.get(cid) or {}
        out.append(f"  judges: a={v.get('judge_a')} b={v.get('judge_b')} "
                   f"({'trusted' if v.get('encodes') else 'NOT trusted'})")
        if tests.get(cid):
            out.append(f"  tests: {', '.join(tests[cid])}")
        if cid in audits:
            out.append(f"  audit: judged test-wrong={audits[cid].get('wrong')}")
        if cid in repairs:
            out.append("  oracle REGENERATED (judged test repair)")
        evs = evidence_by.get(cid) or []
        if not evs:
            out.append("  evidence: (never ran)")
        for i, ev in enumerate(evs):
            out.append(f"  evidence[{i}]: exit={ev.get('exit')} "
                       f"[{'PASS' if ev.get('passed') else 'FAIL'}]")
    return "\n".join(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--chain"]
    if len(args) != 1:
        print("usage: python3 trace_view.py [--chain] <run_dir>/trace.jsonl", file=sys.stderr)
        raise SystemExit(2)
    print(chain(args[0]) if "--chain" in sys.argv[1:] else render(args[0]))
