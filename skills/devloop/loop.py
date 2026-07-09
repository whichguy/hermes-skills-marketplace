"""loop.py — the devloop inner-loop orchestrator (run_v1).

Composes the kernel into:
    ambiguity gate -> DESIGN (tests FROM the DoD) -> coverage -> judge-once ->
    [ IMPLEMENT -> lint -> frozen-tests -> evidence -> stop_condition -> regression ]*
    -> COMPLETE | HUMAN_REVIEW    (NO_TERMINATION = bug sentinel)
COMPLETE is decided by `gate.stop_condition` (coverage + distinct-model judges + REAL
`evidence.run` exit codes) AND `gate.regression_gate` (whole suite green); the code-enforced
back-off guarantees termination. On back-off exhaustion with RED evidence, ONE judged
mid-run TEST REPAIR may replace a wrong oracle through the trusted design path
(_attempt_test_repair, user decision 2026-07-02) before the run surrenders to a human.

Dispatchers are INJECTED, so this is testable with fakes (no LLM) and runnable for real
(the runner wires the `ask`-backed defaults):
  implement(charter, attempt, last_failure) -> {exit_code, files_changed, ...}
  verify_cmd_for(criterion_id) -> list[str]              # the command that checks that criterion

Every step appends to a JSONL run trace under <run_dir>/trace.jsonl (point run_dir at
.devloop/runs/<id>/) — the kernel-call audit + the debug log. Render it with trace_view.py.

(The v0 `run` was DELETED 2026-07-02: its evidence-only COMPLETE had no coverage/judge/
regression gate — a latent fail-open entry point — and it had zero production callers.)
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import config
import state
import evidence
import gate
import dod_oracle
import lint
import worktree

# Whole-suite regression command (run at the worktree root on a would-be-COMPLETE).
# Same interpreter choice as testgen's per-criterion commands.
_REGRESSION_CMD = (sys.executable, "-m", "pytest", "-q")

_SNAPSHOT_SKIP_DIRS = {".devloop", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"}

# Progress stream state: reset per run in run_v1 for accurate elapsed timing.
_PROGRESS_START: float | None = None
_PROGRESS_RUN_DIR: str | None = None  # set by run_v1 so _progress_event can write progress.jsonl
_PROGRESS_RUN_ID: str | None = None   # short correlation ID for this run (e.g. "a3f1")
_TYPICAL_PHASE_S = {
    "judge": 60,
    "implement": 240,
    "overfit_audit": 360,
    "commit_scope": 30,
    "lint": 10,
    "design": 120,
    "regression": 30,
}

# ── Progress levels ────────────────────────────────────────────────────────
# verbose: all stderr + progress.jsonl (default)
# compact: loop-phase markers only (no planning announcements), progress.jsonl still written
# quiet:   no stderr at all, progress.jsonl still written (for CI / cron)
# Levels are integers: 2=verbose, 1=compact, 0=quiet.
_LEVEL_VERBOSE = 2
_LEVEL_COMPACT = 1
_LEVEL_QUIET = 0


def _progress_level():
    """Read DEVLOOP_PROGRESS env var → integer level. Unknown → verbose (safe default)."""
    v = os.environ.get("DEVLOOP_PROGRESS", "verbose").strip().lower()
    if v in ("quiet", "0", "false", "no", "off"):
        return _LEVEL_QUIET
    if v in ("compact", "1"):
        return _LEVEL_COMPACT
    return _LEVEL_VERBOSE  # verbose, 2, true, on, or unknown


def _safe_bool(fn, *args):
    """Call fn(*args), return bool(result), or False on any exception.
    Used by parallel auditor calls — a crashed auditor never indicts."""
    try:
        return bool(fn(*args))
    except Exception:  # noqa: BLE101
        return False


def _progress_event(run_dir, step, **data):
    """Write a structured progress event to progress.jsonl AND emit human-readable stderr.
    This is the unified progress channel — both machine-parseable and human-visible.
    run_dir: the run directory (progress.jsonl lives alongside trace.jsonl).
    step:   the phase name (charter, design, judge, evidence, terminal, etc.).
    data:   event-specific fields (ok, detail, verdicts, attempt, passed, reason, etc.).
    Every record carries the current run_id for cross-log correlation.
    """
    ts = round(time.time(), 3)
    record = {"ts": ts, "step": step, "run_id": _PROGRESS_RUN_ID, **data}
    # Write to progress.jsonl (always — machine channel is independent of stderr level)
    if run_dir:
        try:
            p = Path(str(run_dir)) / "progress.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass
    return record


def _progress(step, detail="", ok=None, *, run_dir=None, **event_data):
    """One-line progress to stderr — real-time visibility without breaking stdout JSON.
    ok=None: ⏳ (in progress), ok=True: ✅, ok=False: ❌. Includes elapsed wall-clock since
    the first progress call and a coarse ETA for known long phases.

    Also writes a structured event to progress.jsonl via _progress_event when run_dir
    is available (set via _PROGRESS_RUN_DIR or passed explicitly)."""
    marker = "✅" if ok else "⏳" if ok is None else "❌"
    global _PROGRESS_START
    if _PROGRESS_START is None:
        _PROGRESS_START = time.monotonic()
    elapsed = time.monotonic() - _PROGRESS_START
    elapsed_s = f"{elapsed:.0f}s"
    eta = ""
    if ok is None:
        typical = _TYPICAL_PHASE_S.get(step)
        if typical:
            eta = f" ~{typical}s"

    # Determine the run_dir for progress.jsonl
    rd = run_dir or _PROGRESS_RUN_DIR

    # Write structured event to progress.jsonl (always, regardless of stderr level)
    if rd is not None:
        event = {"ok": ok, "detail": detail, **event_data}
        _progress_event(rd, step, **event)

    # Emit stderr only if the progress level allows it
    level = _progress_level()
    if level >= _LEVEL_QUIET + 1:  # any level above quiet
        _rid = f"[{_PROGRESS_RUN_ID}] " if _PROGRESS_RUN_ID else ""
        print(f"[devloop] {_rid}{marker} {step} ({elapsed_s}{eta}): {detail}", file=sys.stderr, flush=True)


def _progress_crash(run_dir, step, exc, *, run_id=None):
    """Emit a crash marker when a phase exits with an unhandled exception.
    Writes a ❌ marker with the exception type + a truncated traceback to both
    progress.jsonl and stderr. This is the failure-mode observability the control
    channel needs — without it, a mid-phase crash leaves the last marker as ⏳
    (in-progress), which is indistinguishable from a hung run.
    """
    _rid = run_id or _PROGRESS_RUN_ID
    exc_str = f"{type(exc).__name__}: {exc}"
    tb = traceback.format_exc()
    # truncate traceback to last 800 chars (the relevant frames)
    tb = tb[-800:] if len(tb) > 800 else tb
    _progress_event(run_dir, "crash", ok=False,
                    detail=exc_str, traceback=tb, crash_step=step, run_id=_rid)
    if _progress_level() >= _LEVEL_QUIET + 1:
        _rid_str = f"[{_rid}] " if _rid else ""
        print(f"[devloop] {_rid_str}❌ crash ({step}): {exc_str}", file=sys.stderr, flush=True)


def _progress_roadmap(run_dir=None):
    """Emit the planned phase sequence once at the start of a run so the user sees what's ahead.
    Writes to progress.jsonl always; emits to stderr only in verbose mode (compact suppresses).
    Note: pre_clarify (if it fires) happens in runner.run_task BEFORE run_v1 is called,
    so it's not in this roadmap — its ⏳/✅ markers appear before the roadmap is emitted."""
    phases = [
        "charter", "ambiguity_gate", "design", "coverage", "quality_lint", "judge",
        "implement", "evidence", "stop_check", "regression", "overfit_audit",
        "commit_scope", "complete", "summary",
    ]
    if run_dir is not None:
        _progress_event(run_dir, "roadmap", phases=phases)
    if _progress_level() >= _LEVEL_VERBOSE:
        print("[devloop] roadmap: " + " → ".join(phases), file=sys.stderr, flush=True)


def _return_human_review(run_dir, st, trace, reason, *, grounding=None, charter=None,
                        test_to_criterion=None, **extra):
    """Centralized HUMAN_REVIEW exit — emits terminal progress event, writes stderr (bypasses
    compact mode: blocking questions are critical info that must never be suppressed), and
    returns the standard HUMAN_REVIEW result dict. All HUMAN_REVIEW exits in run_v1 should
    go through this helper to ensure consistent progress output."""
    pg = grounding or _partial_grounding_from_state(run_dir, st)
    _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=reason, **extra)
    # HUMAN_REVIEW always shows on stderr regardless of compact/quiet — it's critical info
    print(f"[devloop] ❌ HUMAN_REVIEW: {reason}", file=sys.stderr, flush=True)
    if charter is not None:
        _summary_rollup = _run_summary(
            charter if charter else {}, st, test_to_criterion,
            terminal="HUMAN_REVIEW")
        _progress("summary", "rollup...", ok=None)
        _progress("summary", _summary_rollup, ok=False)
    state.save_checkpoint(run_dir, st)
    _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=reason, **extra)
    result = {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": trace, "reason": reason}
    if grounding is not None:
        result["grounding"] = grounding
    result.update({k: v for k, v in extra.items() if k not in ("terminal", "reason", "state", "trace_path")})
    return result


def _partial_grounding_from_state(run_dir, st):
    """Best-effort partial grounding placeholder when not explicitly provided."""
    return {}


def _run_summary(charter, st, test_to_criterion, overfit_advisory=None, scope_dropped=None,
                 *, branch=None, terminal=None):
    """Build a one-line rollup of what the run accomplished (or why it stopped).

    Used by the `complete` and `HUMAN_REVIEW` stderr markers so the user gets the
    takeaway without opening trace.jsonl."""
    _n_evidence = len(st.get("evidence_ledger", {}))
    _n_criteria = len(charter.get("dod", []))
    _n_rebuilds = st.get("rebuild_count", 0)
    _n_replans = st.get("replan_count", 0)
    _n_tests = len(test_to_criterion) if test_to_criterion else 0
    _split_votes = st.get("split_votes", 0)
    parts = [f"criteria={_n_criteria}/{_n_criteria}", f"tests={_n_tests}", f"evidence={_n_evidence}"]
    if _n_rebuilds:
        parts.append(f"rebuilds={_n_rebuilds}")
    if _n_replans:
        parts.append(f"replans={_n_replans}")
    if _split_votes:
        parts.append(f"splits={_split_votes}")
    if overfit_advisory:
        parts.append(f"advisory={len(overfit_advisory)}")
    if scope_dropped:
        parts.append(f"scope_dropped={len(scope_dropped)}")
    if branch:
        parts.append(f"branch={branch}")
    base = f"[{terminal}]" if terminal else "[summary]"
    return f"{base} {', '.join(parts)}"


def _test_snapshot(cwd):
    """{relpath: CONTENT-bytes} of every test file under cwd (test_*.py / *_test.py; junk dirs
    skipped). The FROZEN-TESTS invariant (deep review 2026-07-01, caught LIVE twice by the
    extended spike): judge verdicts are cached from DESIGN-time source and evidence runs whatever
    is on disk NOW — so a coder that edits/deletes ANY test file could pass evidence against
    rewritten tests (forged green) or turn the whole-suite regression gate green by DELETING a
    red pre-existing test. "Do NOT modify tests" was prose-only; this makes it a gate.
    CONTENTS (not just hashes) are kept so the loop can SELF-HEAL: a coder cannot restore a file
    it never saw (q1 spike run: kimi deleted test_devloop_dod.py, then ground exit-4 evidence to
    a wasted HUMAN_REVIEW because nothing could put the oracle back)."""
    out = {}
    if not cwd or not os.path.isdir(cwd):
        return out
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in _SNAPSHOT_SKIP_DIRS]
        for f in files:
            if f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")):
                fp = os.path.join(root, f)
                try:
                    out[os.path.relpath(fp, cwd)] = open(fp, "rb").read()
                except OSError:
                    out[os.path.relpath(fp, cwd)] = b"__UNREADABLE__"
    return out


def _frozen_violation(cwd, frozen):
    """Reason string if any frozen test file is missing or content-changed, else None.
    New test files appearing is NOT a violation (only the designer/repo's frozen set is pinned)."""
    now = _test_snapshot(cwd)
    missing = [p for p in frozen if p not in now]
    changed = [p for p in frozen if p in now and now[p] != frozen[p]]
    if missing or changed:
        return f"frozen test files violated: missing={missing[:5]} changed={changed[:5]}"
    return None


def _frozen_restore(cwd, frozen):
    """SELF-HEAL: rewrite every missing/changed frozen test file from the snapshot. Returns the
    restored relpaths. Best-effort per file (an unrestorable file resurfaces as a violation on
    the next pass and the back-off caps still bound the run)."""
    restored = []
    now = _test_snapshot(cwd)
    for rel, content in frozen.items():
        if now.get(rel) == content or content == b"__UNREADABLE__":
            continue
        fp = os.path.join(cwd, rel)
        try:
            os.makedirs(os.path.dirname(fp) or cwd, exist_ok=True)
            with open(fp, "wb") as f:
                f.write(content)
            restored.append(rel)
        except OSError:
            pass
    return restored


def _emit(run_dir, **event):
    p = Path(run_dir) / "trace.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    # ts (epoch, seconds) on every event so the trace carries phase durations for free.
    with open(p, "a") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), **event}) + "\n")


def _persist(run_dir, fname, obj):
    """Best-effort JSON stage artifact under run_dir — the post-run inspection bundle (user ask
    2026-07-03: every loop stage diagnosable after the run; the bridge copies the whole dir to
    devloop-traces/<name>/). Never a failure path: diagnosis must not be able to kill a run."""
    try:
        with open(Path(str(run_dir)) / fname, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, default=str)
    except OSError:
        pass


def _attempt_note(run_dir, **note):
    """One line per pass-gate outcome into attempts.jsonl — the per-attempt inspection record
    (which gate decided, what the evidence said) without re-reading the whole trace."""
    try:
        with open(Path(str(run_dir)) / "attempts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(note, default=str) + "\n")
    except OSError:
        pass


def _design_spec(charter, test_to_criterion, judge_verdicts):
    """The explicit TDD-chain artifact (user ask 2026-07-03: 'scope test intentions relative to
    the code, then map the intentions to actual tests'): per criterion — the promise, the
    functional intention (verify_intent), the rendered test node(s) proving it, and both judge
    votes + reasons on whether the tests encode the intention."""
    inv = {}
    for tid, cid in test_to_criterion.items():
        inv.setdefault(cid, []).append(tid)
    jv = {v.get("criterion_id"): v for v in judge_verdicts if isinstance(v, dict)}
    return {"criteria": [
        {"criterion_id": c["id"], "criterion": c.get("criterion", ""),
         "verify_intent": c.get("verify_intent", ""),
         "tier": c.get("tier", "unit"),
         "tests": sorted(inv.get(c["id"], [])),
         "judges": {"judge_a": jv.get(c["id"], {}).get("judge_a"),
                    "judge_b": jv.get(c["id"], {}).get("judge_b"),
                    "judge_a_reason": jv.get(c["id"], {}).get("judge_a_reason", ""),
                    "judge_b_reason": jv.get(c["id"], {}).get("judge_b_reason", ""),
                    "encodes": jv.get(c["id"], {}).get("encodes")}}
        for c in charter.get("dod", []) if isinstance(c, dict)]}


def _persist_oracle(run_dir, frozen_tests):
    """rendered_tests.json: the frozen oracle EXACTLY as judged (relpath -> source) — what the
    coder was held to, inspectable after the worktree is gone."""
    _persist(run_dir, "rendered_tests.json",
             {rel: (content.decode("utf-8", errors="replace")
                    if isinstance(content, bytes) else str(content))
              for rel, content in (frozen_tests or {}).items()})


def _charter_event(charter):
    """The FULL charter payload for the trace: without the DoD text + assumptions/open_questions
    a false-complete could not be diagnosed post-hoc (deep review 2026-07-01 — the old event
    carried only intent[:160] + a count)."""
    return dict(
        step="charter", intent=charter.get("interpreted_intent", ""),
        n_criteria=len(charter.get("dod", [])),
        dod=[{k: c.get(k) for k in ("id", "criterion", "verify_intent", "tier")}
             for c in charter.get("dod", []) if isinstance(c, dict)],
        assumptions=charter.get("assumptions", []),
        open_questions=charter.get("open_questions", []))


def _do_implement(implement, charter, attempt, last_failure, run_dir):
    """Call implement, emit its trace event, return (exit_code, files_changed, changed_paths). The
    first two are None for a legacy implement that just writes files and returns None (e.g. test
    fakes); a real dispatcher returns {exit_code, files_changed, summary, changed_paths}.
    changed_paths defaults to [] (an implement that doesn't report paths just skips the lint gate).

    If implement raises, emit a crash marker and return a dispatch-error-shaped result so the
    loop fail-closes to HUMAN_REVIEW rather than propagating an unhandled exception."""
    t0 = time.monotonic()
    _progress("implement", f"coder attempt {attempt}{' for ' + str(len(charter.get('dod', []))) + ' criteria' if charter.get('dod') else ''}...")
    try:
        result = implement(charter, attempt, last_failure)
    except Exception as e:  # noqa: BLE001 — a crashed implementer is a dispatch failure, not fatal
        _progress_crash(run_dir, "implement", e)
        _emit(run_dir, step="implement", attempt=attempt, exit_code=1, files_changed=0,
              dur_s=round(time.monotonic() - t0, 2), summary=f"{type(e).__name__}: {e}"[-800:])
        return 1, 0, []
    dur = round(time.monotonic() - t0, 2)
    if isinstance(result, dict):
        ec, fc, summ = result.get("exit_code"), result.get("files_changed"), result.get("summary", "")
        paths = result.get("changed_paths") or []
    else:
        ec, fc, summ, paths = None, None, (str(result) if result else ""), []
    _emit(run_dir, step="implement", attempt=attempt, exit_code=ec, files_changed=fc,
          dur_s=dur, summary=(summ[-800:] if summ else ""))
    _imp_detail = f"attempt {attempt}, {fc or 0} file(s) changed"
    if paths:
        _imp_detail += f": {', '.join(os.path.basename(p) for p in paths[:10])}"
        if len(paths) > 10:
            _imp_detail += f" (+{len(paths)-10} more)"
    if summ:
        _imp_detail += f" — {str(summ).strip()[:120]}"
    if ec not in (0, None):
        _imp_detail += f", exit {ec}"
    _progress("implement", _imp_detail, ok=(ec in (0, None)),
              attempt=attempt, files_changed=fc or 0, exit_code=ec, dur_s=dur)
    return ec, fc, paths


def _lint_gate(changed_paths, cwd, run_dir, attempt):
    """Syntactic gate on the coder's changed files. Returns (ok, feedback): feedback is a per-file
    map of lint errors to hand back to the coder on a rebuild, or None when clean / nothing to
    lint. A missing linter / unmapped type is a skip, never a failure (see lint.py)."""
    if not changed_paths:
        return True, None
    _lint_names = ', '.join(os.path.basename(p) for p in changed_paths[:5])
    if len(changed_paths) > 5:
        _lint_names += f" (+{len(changed_paths)-5} more)"
    _progress("lint", f"checking {len(changed_paths)} file(s) [{_lint_names}], attempt {attempt}")
    ok, results = lint.lint_paths(changed_paths, cwd=cwd)
    fails = lint.failures(results)
    _emit(run_dir, step="lint", attempt=attempt, ok=ok,
          checked=sum(1 for r in results if "skipped" not in r),
          skipped=sum(1 for r in results if "skipped" in r),
          failures=[{"path": r["path"], "linter": r.get("linter"),
                     "out": (r.get("output") or r.get("error") or "")[-300:]} for r in fails[:8]])
    _n_checked = sum(1 for r in results if "skipped" not in r)
    _n_skipped = sum(1 for r in results if "skipped" in r)
    _detail = f"{_n_checked} checked, {_n_skipped} skipped"
    if fails:
        _fail_names = ', '.join(os.path.basename(r["path"]) for r in fails[:5])
        _detail += f", {len(fails)} FAIL [{_fail_names}]"
    _progress("lint", _detail, ok=ok, attempt=attempt,
              checked=_n_checked, skipped=_n_skipped, failed=len(fails))
    if ok:
        return True, None
    return False, {os.path.basename(r["path"]): (r.get("output") or r.get("error") or "")[-300:]
                   for r in fails}


def _dispatch_error(run_dir, st, reason):
    """A model/dispatch ERROR (coder errored or made no progress) is NOT a code red — route
    straight to HUMAN_REVIEW without burning the rebuild/replan budget. Still fail-closed:
    a broken coder routes to a human, never to COMPLETE."""
    _emit(run_dir, step="dispatch_error", reason=reason)
    _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=reason)
    print(f"[devloop] ❌ HUMAN_REVIEW (dispatch error): {reason}", file=sys.stderr, flush=True)
    state.save_checkpoint(run_dir, st)
    _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=reason)
    return {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": str(Path(run_dir) / "trace.jsonl"),
            "reason": reason}


def _grounding_report(charter, ledger, judge_verdicts, test_to_criterion, reg):
    """END-OF-RUN GROUNDING (user ask 2026-07-02): tie the original promise to its proof. For
    every DoD criterion: the criterion text, the tests that encode it, both judge votes, and
    whether its evidence passed — plus the whole-suite regression exit. Deterministic accounting
    over the gates that ALREADY passed (each is fail-closed upstream); this makes the proof
    chain VISIBLE in the trace and the user-facing summary, so a COMPLETE always ships with the
    evidence that the implementation delivers what the prompt promised."""
    by_crit_tests = {}
    for tid, cid in (test_to_criterion or {}).items():
        by_crit_tests.setdefault(cid, []).append(tid)
    jv = {v.get("criterion_id"): v for v in (judge_verdicts or [])}
    items = []
    for c in charter.get("dod", []):
        cid = c.get("id")
        v = jv.get(cid, {})
        items.append({
            "criterion_id": cid,
            "criterion": c.get("criterion", ""),
            "tier": c.get("tier", "unit"),   # unit|integration — the small/larger validate split
            "tests": sorted(by_crit_tests.get(cid, [])),
            "judges": {"a": v.get("judge_a"), "b": v.get("judge_b")},
            "evidence_passed": evidence._passed(ledger.get(cid)),
        })
    return {"intent": charter.get("interpreted_intent", ""),
            "criteria": items,
            "regression_exit": getattr(reg, "exit_code", None),
            "grounded": bool(items) and all(i["evidence_passed"] and i["tests"] for i in items)}


def _partial_grounding(charter, st, judge_verdicts, test_to_criterion):
    """Grounding chain for a NON-COMPLETE terminal (user ask 2026-07-03): which promises were
    proven and which weren't, with the same per-criterion shape as the COMPLETE report — failed
    runs used to ship the LEAST diagnosis exactly when the most was needed. `grounded` is False
    by definition: only the full gate ladder grounds a run."""
    g = _grounding_report(charter, (st or {}).get("evidence_ledger") or {},
                          judge_verdicts, test_to_criterion, None)
    g["grounded"] = False
    return g


def _attempt_test_repair(charter, st, test_to_criterion, by_id, audit_a, audit_b,
                         redesign, judge_a, judge_b, run_dir, cwd, tiebreaker=None):
    """JUDGED MID-RUN TEST REPAIR (user decision 2026-07-02): the back-off is exhausted with RED
    evidence — before surrendering to a human, audit whether the ORACLE itself asserts the wrong
    output. The coder NEVER touches tests: the only repair path is the same trusted machinery
    that admitted the originals (designer -> coverage gate -> two judges -> re-frozen snapshot).
    AT MOST ONCE per run: st['repair_used'] is burned BEFORE the redesign (a crashed repair can
    never re-arm), and max_passes stays the absolute cap. Returns the replacement oracle bundle
    {test_map, verify, verdicts, frozen, wrong} on success, else None (-> HUMAN_REVIEW, with the
    audit verdicts in st['test_audit'] for the terminal reason / post-mortem)."""
    ledger = st.get("evidence_ledger") or {}
    tests_by_crit = {}
    for tid, cid in (test_to_criterion or {}).items():
        tests_by_crit.setdefault(cid, []).append(tid)
    wrong, details = gate.audit_tests(charter, ledger, tests_by_crit, audit_a, audit_b)
    st["test_audit"] = details
    _emit(run_dir, step="test_audit", wrong=wrong, details=details)
    if not wrong:
        return None                       # oracle affirmed (or no red evidence) -> human review
    st["repair_used"] = True              # burned BEFORE the attempt: one repair, ever
    try:
        new_map, new_verify = redesign(charter, wrong, details)
    except Exception as e:  # noqa: BLE001 — a failed redesign falls back to human review
        _emit(run_dir, step="test_repair", ok=False,
              reason=f"redesign failed: {type(e).__name__}: {e}")
        return None
    cov_ok, uncovered = dod_oracle.check_structural_coverage(charter["dod"], new_map)
    _emit(run_dir, step="coverage", ok=cov_ok, uncovered=uncovered, repair=True)
    if not cov_ok:
        _emit(run_dir, step="test_repair", ok=False,
              reason=f"repaired tests leave criteria uncovered: {uncovered}")
        return None
    tests = [{"test_id": tid, "criterion_id": cid} for tid, cid in new_map.items()]
    verdicts = dod_oracle.judge_assertions(tests, by_id, judge_a, judge_b, run_dir=run_dir,
                            judge_a_model=getattr(__import__('dispatch'), "JUDGE_A", ""),
                            judge_b_model=getattr(__import__('dispatch'), "JUDGE_B", ""),
                            tiebreaker=tiebreaker,
                            tiebreaker_model=getattr(__import__('dispatch'), "TIEBREAKER", ""))
    _emit(run_dir, step="judge", repair=True,
          verdicts=[{"criterion": v["criterion_id"], "encodes": v["encodes"],
                     "escalate": v["escalate"], "judge_a": v.get("judge_a"),
                     "judge_b": v.get("judge_b")} for v in verdicts])
    untrusted = gate.untrusted_criteria(charter, verdicts)
    if untrusted:
        _emit(run_dir, step="test_repair", ok=False,
              reason=f"repaired tests not judge-trusted: {untrusted}")
        return None
    return {"test_map": new_map, "verify": new_verify, "verdicts": verdicts,
            "frozen": _test_snapshot(cwd), "wrong": wrong}


def run_v1(charter, *, design, implement, judge_a, judge_b, verify_cmd_for, run_dir,
           cwd=None, max_passes=64, regression_cmd=None,
           redesign=None, audit_a=None, audit_b=None, overfit_a=None, overfit_b=None,
           scope_audit=None, tiebreaker=None):
    """v1 loop = v0 + the DoD oracle. After the ambiguity gate, DESIGN generates tests FROM the
    DoD (`design(charter) -> {test_id: criterion_id}`, writing the test files); structural
    coverage must hold (fail-closed -> HUMAN_REVIEW); then each pass IMPLEMENTs, runs evidence,
    and the assertion judge confirms each test encodes its criterion. COMPLETE is decided by
    `gate.stop_condition` (coverage + distinct-model judge + real evidence). A final advisors
    council is NOT wired (gate.council_gate exists but is unused); wire it only if needed.

    JUDGED MID-RUN TEST REPAIR (user decision 2026-07-02): when the back-off exhausts with red
    evidence and `redesign`/`audit_a`/`audit_b` are provided, ONE bounded repair cycle may
    replace a wrong oracle through the trusted design path (see _attempt_test_repair); with any
    of the three absent the exhaustion routes straight to HUMAN_REVIEW exactly as before.
    `redesign(charter, wrong_ids, details) -> (test_map, verify_cmd_for)`;
    `audit(criterion, test_ids, evidence_tail) -> bool` (True = test wrong).

    GREEN-SIDE OVERFIT AUDIT (user decision 2026-07-03): with `overfit_a`/`overfit_b`
    (`overfit(criterion, test_ids) -> bool`) provided, the FIRST would-be-COMPLETE is audited
    once for coded-around wrong oracles (the run-3 specimen); unanimous indictment spends the
    same one regeneration budget, a split vote is a grounding advisory, and an indicted oracle
    that cannot be regenerated routes HUMAN_REVIEW (never a false-complete).
    """
    run_dir = str(run_dir)
    global _PROGRESS_START, _PROGRESS_RUN_DIR, _PROGRESS_RUN_ID
    _PROGRESS_START = time.monotonic()
    _PROGRESS_RUN_DIR = run_dir  # so _progress() can write to progress.jsonl
    _PROGRESS_RUN_ID = uuid.uuid4().hex[:8]  # short correlation ID for this run
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    trace = str(Path(run_dir) / "trace.jsonl")
    _progress_roadmap(run_dir)
    _emit(run_dir, **_charter_event(charter))
    _progress("charter", "decomposing request...")
    _persist(run_dir, "charter.json", charter)
    _progress("charter", f"{len(charter['dod'])} criteria, {len(charter.get('assumptions', []))} assumptions",
              ok=True)
    decision, reason = gate.ambiguity_gate(charter)
    _emit(run_dir, step="ambiguity_gate", decision=decision, reason=reason)
    _progress("ambiguity_gate", reason[:60] if reason else "passed", ok=(decision == config.DECISION_PROCEED))
    if decision != config.DECISION_PROCEED:
        st = state.new_run_state(charter)
        return _return_human_review(run_dir, st, trace, reason, charter=charter)

    # Every invoke is FRESH — loop-level resume was DELETED (deep review 2026-07-01): both real
    # entrypoints (devloop_bridge._name pid+time_ns, project._attempt_name) mint a unique run_dir,
    # so a checkpoint never pre-exists; and if one ever did, runner re-drafts the charter each call,
    # so resumed counters would bind to a DIFFERENT DoD's criterion ids. Checkpoints remain written
    # (save_checkpoint) as the HUMAN_REVIEW/post-mortem artifact — they are just never re-ingested.
    st = state.new_run_state(charter)
    ids = [c["id"] for c in charter["dod"]]
    by_id = {c["id"]: c for c in charter["dod"]}

    # DESIGN: generate tests FROM the DoD; coverage must hold before any code is trusted.
    _progress("design", f"generating tests for {len(charter['dod'])} criteria...",
              n_criteria=len(charter['dod']))
    test_to_criterion = design(charter)
    n_tests = len(test_to_criterion)
    cov_ok, uncovered = dod_oracle.check_structural_coverage(charter["dod"], test_to_criterion)
    _emit(run_dir, step="coverage", ok=cov_ok, uncovered=uncovered)
    _progress("design", f"{n_tests} test(s) rendered for {len(by_id)} criteria",
              ok=True, n_tests=n_tests, n_criteria=len(by_id))
    _progress("coverage", f"{n_tests} tests covering {len(by_id)} criteria", ok=cov_ok,
              n_tests=n_tests, n_criteria=len(by_id), uncovered=uncovered)
    if not cov_ok:
        cov_reason = f"DoD criteria with no covering test: {uncovered}"
        return _return_human_review(run_dir, st, trace, cov_reason,
                                     charter=charter, test_to_criterion=test_to_criterion)

    # PRE-JUDGE QUALITY GATE (Layer 1): fast static check for known-rejected test patterns.
    # Runs before the 2-model judges to avoid burning ~6 minutes on tests the designer can
    # fix immediately (e.g. string-literal datetimes, module-level patch). Findings are saved
    # so the next project attempt can feed them back to the designer as ANSWERS.
    import quality_lint
    quality_ok, quality_findings = quality_lint.lint_rendered_tests(cwd or run_dir)
    _emit(run_dir, step="quality_lint", ok=quality_ok, findings=quality_findings)
    _progress("quality_lint", f"{'passed' if quality_ok else str(len(quality_findings)) + ' findings'}", ok=quality_ok)
    if not quality_ok:
        # QUALITY LINT REDESIGN (2026-07-05): instead of going straight to HUMAN_REVIEW,
        # spend the ONE oracle regeneration budget to fix the tests — same as judge-distrust.
        # The designer gets the quality_lint findings as feedback so it knows what patterns
        # to avoid (module_level_patch, mock_without_call_inspection, etc.).
        if redesign is not None and not st.get("repair_used"):
            st["repair_used"] = True
            all_cids = sorted(set(test_to_criterion.values()))
            _emit(run_dir, step="test_redesign", criteria=all_cids, cause="quality_lint")
            _progress("redesign", "quality_lint findings -> redesign", ok=False)
            # Build feedback from quality findings (same shape as judge verdicts)
            quality_feedback = [
                {"criterion_id": test_to_criterion.get(tid, ""),
                 "judge_a": False, "judge_b": False,
                 "judge_a_reason": f"quality_lint: {f['category']}: {f['message'][:200]}",
                 "judge_b_reason": ""}
                for tid, f in zip(
                    # Map findings to test files — each finding has a path, we need the
                    # criterion ids affected. All criteria are affected since the patterns
                    # are file-wide.
                    [k for k in test_to_criterion for _ in quality_findings],
                    quality_findings,
                )
            ]
            try:
                new_map, new_verify = redesign(charter, all_cids, quality_feedback)
            except Exception as e:  # noqa: BLE001
                _progress_crash(run_dir, "quality_lint_redesign", e)
                _emit(run_dir, step="test_repair", ok=False,
                      reason=f"quality_lint redesign failed: {type(e).__name__}: {e}")
            else:
                # Re-run quality lint on the redesigned tests
                # Re-render: the redesign already wrote the new tests to disk
                quality_ok2, quality_findings2 = quality_lint.lint_rendered_tests(cwd or run_dir)
                _emit(run_dir, step="quality_lint", ok=quality_ok2, findings=quality_findings2, repair=True)
                if quality_ok2:
                    test_to_criterion = new_map
                    verify_cmd_for = new_verify
                    tests = [{"test_id": tid, "criterion_id": cid} for tid, cid in new_map.items()]
                    _progress("quality_lint", "redesign fixed patterns", ok=True)
                else:
                    # Redesign didn't fix it — fall through to HUMAN_REVIEW
                    ql_reason = ("test quality gate failed (redesign could not fix): "
                                 + quality_lint.feedback_for_redesigner(quality_findings2))
                    _emit(run_dir, step="attribution", fault="test",
                          criteria=sorted(set(test_to_criterion.values())))
                    pg = _partial_grounding(charter, st, [], test_to_criterion)
                    pg["quality_findings"] = quality_findings2
                    _emit(run_dir, step="grounding", **pg)
                    _persist(run_dir, "grounding.json", pg)
                    _persist(run_dir, "quality_findings.json", quality_findings2)
                    state.save_checkpoint(run_dir, st)
                    _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=ql_reason)
                    print(f"[devloop] ❌ HUMAN_REVIEW: {ql_reason}", file=sys.stderr, flush=True)
                    _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=ql_reason)
                    return {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": trace,
                            "reason": ql_reason, "grounding": pg, "quality_findings": quality_findings2}
        else:
            # No redesign available or budget already spent — go to HUMAN_REVIEW
            ql_reason = "test quality gate failed: " + quality_lint.feedback_for_redesigner(quality_findings)
            _emit(run_dir, step="attribution", fault="test",
                  criteria=sorted(set(test_to_criterion.values())))
            pg = _partial_grounding(charter, st, [], test_to_criterion)
            pg["quality_findings"] = quality_findings
            _emit(run_dir, step="grounding", **pg)
            _persist(run_dir, "grounding.json", pg)
            _persist(run_dir, "quality_findings.json", quality_findings)
            state.save_checkpoint(run_dir, st)
            _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=ql_reason)
            print(f"[devloop] ❌ HUMAN_REVIEW: {ql_reason}", file=sys.stderr, flush=True)
            _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=ql_reason)
            return {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": trace, "reason": ql_reason,
                    "grounding": pg, "quality_findings": quality_findings}

    tests = [{"test_id": tid, "criterion_id": cid} for tid, cid in test_to_criterion.items()]

    # JUDGE ONCE (spike fix): the designer's tests are FIXED after DESIGN — the coder never edits them —
    # so the encoding judgment is stable across rebuilds. Re-judging every pass only re-rolls the
    # non-deterministic judges and can flip a recoverable code-fault into a fatal "test fault". Judge
    # once here, reuse the verdicts in every stop_condition below.
    _progress("judge", f"judging {len(tests)} test(s) for {len(by_id)} criteria...")
    judge_verdicts = dod_oracle.judge_assertions(tests, by_id, judge_a, judge_b, run_dir=run_dir,
                            judge_a_model=getattr(__import__('dispatch'), "JUDGE_A", ""),
                            judge_b_model=getattr(__import__('dispatch'), "JUDGE_B", ""),
                            tiebreaker=tiebreaker,
                            tiebreaker_model=getattr(__import__('dispatch'), "TIEBREAKER", ""))
    _emit(run_dir, step="judge",
          verdicts=[{"criterion": v["criterion_id"], "encodes": v["encodes"], "escalate": v["escalate"],
                     "judge_a": v.get("judge_a"), "judge_b": v.get("judge_b"),
                     "judge_a_reason": v.get("judge_a_reason", ""), "judge_b_reason": v.get("judge_b_reason", "")}
                    for v in judge_verdicts])
    _trusted = sum(1 for v in judge_verdicts if v.get("encodes"))
    # Per-criterion verdict detail in progress.jsonl + verbose stderr
    _verdicts_summary = [
        {"criterion": v["criterion_id"], "encodes": v.get("encodes"),
         "judge_a": v.get("judge_a"), "judge_b": v.get("judge_b"),
         "judge_a_reason": v.get("judge_a_reason", ""),
         "judge_b_reason": v.get("judge_b_reason", "")}
        for v in judge_verdicts
    ]
    _untrusted_ids = [v["criterion_id"] for v in judge_verdicts if not v.get("encodes")]
    _judge_detail = f"{_trusted}/{len(judge_verdicts)} criteria trusted"
    if _untrusted_ids:
        _judge_detail += f" ({', '.join(_untrusted_ids[:5])}{'...' if len(_untrusted_ids) > 5 else ''} UNTRUSTED)"
        # Surface why the first untrusted criterion was distrusted so the user sees the learning live.
        _first = next((v for v in judge_verdicts if not v.get("encodes")), None)
        if _first:
            _reasons = []
            for key, label in [("judge_a_reason", "A"), ("judge_b_reason", "B")]:
                r = _first.get(key, "")
                if isinstance(r, str) and r.strip():
                    _reasons.append(f"{label}: {r.strip()[:60]}")
            if _reasons:
                _judge_detail += f" — {' | '.join(_reasons)}"
    _progress("judge", _judge_detail,
              ok=_trusted == len(judge_verdicts),
              trusted=_trusted, total=len(judge_verdicts),
              verdicts=_verdicts_summary)
    untrusted = gate.untrusted_criteria(charter, judge_verdicts)
    if untrusted and redesign is not None and not st.get("repair_used"):
        # UP-FRONT ORACLE RETRY (2026-07-02, spends the same ONE regeneration budget as the
        # mid-run repair): a judge-distrusted test is a TEST fault the coder can never fix — but
        # judges are non-deterministic (live quick-spike catch: one dissent on a fine criterion
        # wasted the whole run). Regenerate once through the full trusted path (designer ->
        # coverage -> both judges); still-untrusted -> HUMAN_REVIEW exactly as before.
        st["repair_used"] = True          # the one oracle regeneration, up-front or mid-run
        _emit(run_dir, step="test_redesign", criteria=untrusted, cause="judge_distrust")
        # Pass judge feedback so the redesigner knows WHY the tests were distrusted.
        # Without this, the redesigner is blind and repeats the same mistake (the root
        # cause of 5/5 calendar-quick-add failures — the up-front redesign path passed []).
        untrusted_verdicts = [v for v in judge_verdicts if v.get("criterion_id") in set(untrusted)]
        try:
            new_map, new_verify = redesign(charter, untrusted, untrusted_verdicts)
        except Exception as e:  # noqa: BLE001 — a failed regeneration keeps the original verdicts
            _progress_crash(run_dir, "upfront_redesign", e)
            _emit(run_dir, step="test_repair", ok=False,
                  reason=f"up-front redesign failed: {type(e).__name__}: {e}")
        else:
            cov2, unc2 = dod_oracle.check_structural_coverage(charter["dod"], new_map)
            _emit(run_dir, step="coverage", ok=cov2, uncovered=unc2, repair=True)
            if cov2:
                test_to_criterion = new_map
                verify_cmd_for = new_verify
                tests = [{"test_id": tid, "criterion_id": cid} for tid, cid in new_map.items()]
                judge_verdicts = dod_oracle.judge_assertions(tests, by_id, judge_a, judge_b, run_dir=run_dir,
                            judge_a_model=getattr(__import__('dispatch'), "JUDGE_A", ""),
                            judge_b_model=getattr(__import__('dispatch'), "JUDGE_B", ""),
                            tiebreaker=tiebreaker,
                            tiebreaker_model=getattr(__import__('dispatch'), "TIEBREAKER", ""))
                _emit(run_dir, step="judge", repair=True,
                      verdicts=[{"criterion": v["criterion_id"], "encodes": v["encodes"],
                                 "escalate": v["escalate"], "judge_a": v.get("judge_a"),
                                 "judge_b": v.get("judge_b")} for v in judge_verdicts])
                untrusted = gate.untrusted_criteria(charter, judge_verdicts)
    # Inspection bundle: the intent -> test mapping + verdicts as they stand entering the loop.
    _persist(run_dir, "design_spec.json", _design_spec(charter, test_to_criterion, judge_verdicts))
    _persist(run_dir, "judge_verdicts.json", judge_verdicts)
    if untrusted:
        # TEST fault caught UP FRONT, before any coder call: a criterion's test isn't judge-trusted,
        # which re-IMPLEMENT cannot fix (#18). Route to a human / project re-attempt (which re-DESIGNs).
        tf_reason = f"test fault: criteria {untrusted} have no judge-trusted test; re-IMPLEMENT cannot fix it"
        _emit(run_dir, step="attribution", fault="test", criteria=untrusted)
        pg = _partial_grounding(charter, st, judge_verdicts, test_to_criterion)
        _emit(run_dir, step="grounding", **pg)
        _persist(run_dir, "grounding.json", pg)
        state.save_checkpoint(run_dir, st)
        _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=tf_reason)
        print(f"[devloop] ❌ HUMAN_REVIEW: {tf_reason}", file=sys.stderr, flush=True)
        _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=tf_reason)
        return {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": trace, "reason": tf_reason,
                "grounding": pg}

    # FREEZE the test files (DoD tests are on disk after DESIGN; the repo's pre-existing suite
    # too). The regression step requires this snapshot intact before any COMPLETE.
    frozen_tests = _test_snapshot(cwd)
    _emit(run_dir, step="frozen_tests", n=len(frozen_tests))
    _persist_oracle(run_dir, frozen_tests)

    # LINTER DISCOVERY: report which linters are runnable in this environment.
    # Fast path: probe only linters for file types present in the frozen test set
    # (the coder's output isn't known yet, but the test files are already on disk).
    _discovery_paths = list(frozen_tests)
    _progress("lint_discovery", "discovering available linters...")
    _discovery = lint.discover(_discovery_paths)
    _emit(run_dir, step="lint_discovery", coverage=_discovery)
    _n_linters = sum(len(r.get("available", [])) for r in _discovery if isinstance(r, dict) and r.get("covered"))
    _progress("lint_discovery", f"{_n_linters} linter(s) available for {len(_discovery_paths)} file(s)", ok=True)
    last_failure = None
    last_sreason = ""        # last stop-condition reason (carries which criteria/judges blocked) -> the
    #                          informative 'why' for the back-off / no-termination terminal lessons
    for _ in range(max_passes):
        action, areason = gate.backoff_exhausted(st)
        _emit(run_dir, step="backoff", action=action,
              rebuild=st["rebuild_count"], replan=st["replan_count"], reason=areason)
        if action == "HUMAN_REVIEW":
            # JUDGED MID-RUN TEST REPAIR (user decision 2026-07-02): before surrendering the run,
            # audit whether the ORACLE is wrong — once, on red evidence only, and only through
            # the trusted designer+judges path. Declined/failed repair -> human, as before.
            rep = None
            if redesign is not None and audit_a is not None and audit_b is not None \
                    and not st.get("repair_used"):
                rep = _attempt_test_repair(charter, st, test_to_criterion, by_id,
                                           audit_a, audit_b, redesign, judge_a, judge_b,
                                           run_dir, cwd, tiebreaker=tiebreaker)
            if rep is not None:
                test_to_criterion = rep["test_map"]
                verify_cmd_for = rep["verify"]
                judge_verdicts = rep["verdicts"]
                cov_ok = True                              # re-gated above, on the NEW tests
                frozen_tests = rep["frozen"]               # the repaired oracle is re-frozen
                # the bundle must reflect the REPAIRED oracle, not the one it replaced
                _persist(run_dir, "design_spec.json",
                         _design_spec(charter, test_to_criterion, judge_verdicts))
                _persist(run_dir, "judge_verdicts.json", judge_verdicts)
                _persist_oracle(run_dir, frozen_tests)
                state.on_repair(st)                        # ONE fresh budget; repair_used pins it
                state.save_checkpoint(run_dir, st)
                _emit(run_dir, step="test_repair", ok=True, criteria=rep["wrong"])
                _progress("test_repair", f"oracle regenerated for {rep['wrong']}", ok=True,
                          criteria=rep["wrong"])
                last_failure = {"test_repair": "the tests for criteria "
                                               f"{rep['wrong']} were REGENERATED (the previous "
                                               "ones asserted the wrong output). Re-read the "
                                               "test files and satisfy the new oracle."}
                last_sreason = ""
                continue
            bo_reason = areason + (f"; last failure: {last_sreason}" if last_sreason else "")
            aud = st.get("test_audit")
            if aud is not None:
                n_wrong = sum(1 for x in aud if x.get("wrong"))
                bo_reason += f"; test audit: {n_wrong}/{len(aud)} red criteria judged test-wrong"
            pg = _partial_grounding(charter, st, judge_verdicts, test_to_criterion)
            _emit(run_dir, step="grounding", **pg)
            _persist(run_dir, "grounding.json", pg)
            state.save_checkpoint(run_dir, st)
            _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=bo_reason)
            print(f"[devloop] ❌ HUMAN_REVIEW: {bo_reason}", file=sys.stderr, flush=True)
            _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=bo_reason)
            return {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": trace,
                    "reason": bo_reason, "grounding": pg}
        if action == "REPLAN":
            state.on_replan(st)
            _emit(run_dir, step="replan", replan=st["replan_count"])
            _progress("replan", f"replan {st['replan_count']} triggered", ok=False,
                      replan=st["replan_count"])
            continue

        attempt = st["rebuild_count"]
        exit_code, files_changed, changed_paths = _do_implement(implement, charter, attempt, last_failure, run_dir)
        if exit_code not in (0, None):     # coder process errored -> dispatch error, fail fast
            return _dispatch_error(run_dir, st, f"coder dispatch error (exit {exit_code})")

        lint_ok, lint_fb = _lint_gate(changed_paths, cwd, run_dir, attempt)
        if not lint_ok:     # syntactic breakage -> feed back + rebuild, skip the test/judge passes
            last_failure = {"lint": lint_fb}
            state.on_rebuild_fail(st)
            _emit(run_dir, step="rebuild_fail", rebuild=st["rebuild_count"], cause="lint")
            _progress("rebuild", f"attempt {attempt} failed lint → rebuild {st['rebuild_count']}",
                      ok=False, cause="lint", attempt=attempt, rebuild=st["rebuild_count"])
            _attempt_note(run_dir, attempt=attempt, gate="lint", ok=False,
                          detail=str(lint_fb)[:300])
            continue

        # FROZEN-TESTS GATE, checked EVERY pass (not only at would-be-COMPLETE): a missing/
        # rewritten test file invalidates the cached judge verdicts, the per-criterion evidence,
        # AND the whole-suite result. SELF-HEAL: the loop restores the originals from the
        # snapshot (the coder cannot — it never saw them) and re-IMPLEMENTs with an explicit
        # "fix the CODE, not the tests" instruction, under the same back-off budget.
        viol = _frozen_violation(cwd, frozen_tests)
        if viol:
            restored = _frozen_restore(cwd, frozen_tests)
            _emit(run_dir, step="frozen_tests", ok=False, reason=viol, restored=restored)
            _progress("frozen_tests", f"violation detected, {len(restored)} file(s) restored",
                      ok=False, violation=viol, restored=len(restored))
            last_failure = {"frozen_tests": viol + " — the original test files were RESTORED by the "
                                                   "loop. Tests are the ORACLE: never edit, move, or "
                                                   "delete them; change the CODE to satisfy them."}
            last_sreason = viol
            state.on_rebuild_fail(st)
            _emit(run_dir, step="rebuild_fail", rebuild=st["rebuild_count"], cause="frozen_tests")
            _progress("rebuild", f"attempt {attempt} violated frozen tests → rebuild {st['rebuild_count']}",
                      ok=False, cause="frozen_tests", attempt=attempt, rebuild=st["rebuild_count"])
            _attempt_note(run_dir, attempt=attempt, gate="frozen_tests", ok=False,
                          detail=str(viol)[:300])
            state.save_checkpoint(run_dir, st)
            continue

        ledger = {}
        _progress("evidence", f"running {len(ids)} test command(s) for {len(ids)} criteria [{', '.join(ids[:5])}{'...' if len(ids) > 5 else ''}], attempt {attempt}...")
        for cid in ids:
            ev = evidence.run(cid, verify_cmd_for(cid), cwd=cwd)
            ledger[cid] = ev
            _emit(run_dir, step="evidence", criterion=cid, cmd=list(ev.cmd),
                  exit=ev.exit_code, passed=ev.passed, stderr_tail=(ev.stderr_tail or "")[-400:])
        # Progress: per-criterion evidence results with attempt number
        _n_passed = sum(1 for cid in ids if ledger[cid].passed)
        _n_total = len(ids)
        _red = [cid for cid in ids if not ledger[cid].passed]
        _detail = f"attempt {attempt}, {_n_passed}/{_n_total} passed"
        if _red:
            _detail += f" ({', '.join(_red)} RED)"
        _progress("evidence", _detail, ok=_n_passed == _n_total,
                  attempt=attempt, passed=_n_passed, total=_n_total,
                  red=_red, per_criterion={cid: ledger[cid].passed for cid in ids})
        st["evidence_ledger"] = ledger
        state.save_checkpoint(run_dir, st)

        # stop_condition reuses the judge verdicts computed ONCE above (the tests didn't change —
        # the frozen gate above just verified that on THIS pass).
        complete, sreason = gate.stop_condition(charter, ledger, cov_ok, judge_verdicts)
        _emit(run_dir, step="stop_check", complete=complete, reason=sreason)
        _progress("stop_check", sreason[:60], ok=complete)
        _attempt_note(run_dir, attempt=attempt, gate="evidence", ok=complete,
                      files_changed=files_changed,
                      evidence={cid: ledger[cid].passed for cid in ids},
                      detail=str(sreason)[:300])
        last_sreason = sreason            # remember why this pass did/didn't complete (for the lesson)
        if complete:
            # WHOLE-SUITE REGRESSION GATE: the per-criterion commands run only the DoD's own test
            # nodes, so a modify task could break PRE-EXISTING tests and still reach here. A
            # would-be-COMPLETE must also leave the whole repo suite green (pytest exit 5 = no
            # tests collected = vacuous pass; see gate.regression_gate). Red = a CODE fault the
            # coder can act on -> feed the failing output back and re-IMPLEMENT under the same
            # back-off budget (bounded -> HUMAN_REVIEW), never COMPLETE.
            _progress("regression", "running whole-suite regression...")
            reg = evidence.run("__suite__", list(regression_cmd or _REGRESSION_CMD), cwd=cwd)
            reg_ok, rreason = gate.regression_gate(reg)
            st["evidence_ledger"]["__suite__"] = reg     # ledger keys are c1..cN; no collision
            _emit(run_dir, step="regression", exit=reg.exit_code, passed=reg_ok, reason=rreason)
            _progress("regression", f"whole-suite exit {reg.exit_code}", ok=reg_ok)
            state.save_checkpoint(run_dir, st)
            if not reg_ok:
                last_failure = {"regression": (reg.stdout_tail or reg.stderr_tail or "")[-800:]}
                last_sreason = rreason
                state.on_rebuild_fail(st)
                _emit(run_dir, step="rebuild_fail", rebuild=st["rebuild_count"], cause="regression")
                _progress("rebuild", f"attempt {attempt} failed regression → rebuild {st['rebuild_count']}",
                          ok=False, cause="regression", attempt=attempt, rebuild=st["rebuild_count"])
                _attempt_note(run_dir, attempt=attempt, gate="regression", ok=False,
                              detail=str(rreason)[:300])
                continue
            # GREEN-SIDE OVERFIT AUDIT (user decision 2026-07-03, run-3 live specimen): a wrong
            # oracle the coder OVERFIT never goes red, so the red-side repair can't reach it.
            # Once per run, at the first would-be-COMPLETE: both overfit auditors judge every
            # criterion (test values vs semantics; implementation special-casing). UNANIMOUS
            # indictment spends the same ONE regeneration budget as the other repairs; a split
            # vote is an ADVISORY in the grounding (flaky-over-block), never a block.
            #
            # PARALLELIZED (2026-07-05): fire all 2×N auditor calls concurrently via
            # ThreadPoolExecutor — same pattern as dod_oracle.judge_assertions. Cuts overfit
            # audit from ~360s (8 sequential calls) to ~60s (one round-trip) for 4 criteria.
            overfit_advisory = []
            if (overfit_a is not None and overfit_b is not None and redesign is not None
                    and not st.get("repair_used") and not st.get("overfit_checked")):
                _progress("overfit_audit", f"auditing {len(ids)} criteria x 2 auditors...")
                st["overfit_checked"] = True
                inv = {}
                for tid, cid in test_to_criterion.items():
                    inv.setdefault(cid, []).append(tid)
                suspect, details = [], []
                # Fire all auditor calls concurrently (2 auditors × N criteria)
                import concurrent.futures as _cf
                _futs = {}
                with _cf.ThreadPoolExecutor(max_workers=min(8, 2 * len(ids))) as _ex:
                    for cid in ids:
                        _futs[(cid, "a")] = _ex.submit(
                            lambda c=cid: _safe_bool(overfit_a, by_id[c], inv.get(c, [])))
                        _futs[(cid, "b")] = _ex.submit(
                            lambda c=cid: _safe_bool(overfit_b, by_id[c], inv.get(c, [])))
                    for cid in ids:
                        votes = [_futs[(cid, "a")].result(), _futs[(cid, "b")].result()]
                        is_overfit = len(votes) == 2 and all(votes)
                        details.append({"criterion": cid, "votes": votes, "overfit": is_overfit})
                        if is_overfit:
                            suspect.append(cid)
                _emit(run_dir, step="overfit_audit", suspect=suspect, details=details)
                _progress("overfit_audit", f"{len(ids)} criteria x 2 auditors, {len(suspect)} suspect", ok=not suspect)
                _persist(run_dir, "overfit_audit.json", {"suspect": suspect, "details": details})
                overfit_advisory = [d["criterion"] for d in details
                                    if any(d["votes"]) and not d["overfit"]]
                if suspect:
                    st["repair_used"] = True   # the one regeneration, spent on the green-side indictment
                    _emit(run_dir, step="test_redesign", criteria=suspect, cause="overfit_audit")
                    ok_rep, new_map, new_verify, jv2 = False, None, None, None
                    try:
                        new_map, new_verify = redesign(charter, suspect, details)
                        cov3, unc3 = dod_oracle.check_structural_coverage(charter["dod"], new_map)
                        _emit(run_dir, step="coverage", ok=cov3, uncovered=unc3, repair=True)
                        if cov3:
                            tests2 = [{"test_id": t, "criterion_id": c} for t, c in new_map.items()]
                            jv2 = dod_oracle.judge_assertions(tests2, by_id, judge_a, judge_b, run_dir=run_dir,
                                judge_a_model=getattr(__import__('dispatch'), "JUDGE_A", ""),
                                judge_b_model=getattr(__import__('dispatch'), "JUDGE_B", ""),
                                tiebreaker=tiebreaker,
                                tiebreaker_model=getattr(__import__('dispatch'), "TIEBREAKER", ""))
                            _emit(run_dir, step="judge", repair=True,
                                  verdicts=[{"criterion": v["criterion_id"], "encodes": v["encodes"],
                                             "escalate": v["escalate"], "judge_a": v.get("judge_a"),
                                             "judge_b": v.get("judge_b")} for v in jv2])
                            ok_rep = not gate.untrusted_criteria(charter, jv2)
                    except Exception as e:  # noqa: BLE001 — a crashed regeneration fails the re-gate
                        _emit(run_dir, step="test_repair", ok=False,
                              reason=f"overfit redesign failed: {type(e).__name__}: {e}")
                    if not ok_rep:
                        # The oracle stands UNANIMOUSLY indicted and could not be regenerated
                        # through the trusted path — completing on it would be a false-complete.
                        of_reason = (f"overfit audit indicted criteria {suspect} (test/implementation "
                                     "mismatch with the criterion's semantics) and the oracle "
                                     "regeneration failed its re-gate")
                        pg = _partial_grounding(charter, st, judge_verdicts, test_to_criterion)
                        _emit(run_dir, step="grounding", **pg)
                        _persist(run_dir, "grounding.json", pg)
                        state.save_checkpoint(run_dir, st)
                        _progress_event(run_dir, "terminal", terminal="HUMAN_REVIEW", reason=of_reason)
                        print(f"[devloop] ❌ HUMAN_REVIEW: {of_reason}", file=sys.stderr, flush=True)
                        _emit(run_dir, step="terminal", terminal="HUMAN_REVIEW", reason=of_reason)
                        return {"terminal": "HUMAN_REVIEW", "state": st, "trace_path": trace,
                                "reason": of_reason, "grounding": pg}
                    test_to_criterion, verify_cmd_for, judge_verdicts = new_map, new_verify, jv2
                    cov_ok = True
                    frozen_tests = _test_snapshot(cwd)          # the honest oracle is re-frozen
                    _persist(run_dir, "design_spec.json",
                             _design_spec(charter, test_to_criterion, judge_verdicts))
                    _persist(run_dir, "judge_verdicts.json", judge_verdicts)
                    _persist_oracle(run_dir, frozen_tests)
                    state.on_repair(st)
                    state.save_checkpoint(run_dir, st)
                    _emit(run_dir, step="test_repair", ok=True, criteria=suspect)
                    _progress("test_repair", f"overfit audit regenerated tests for {suspect}",
                              ok=True, criteria=suspect, cause="overfit")
                    last_failure = {"test_repair": f"the tests for criteria {suspect} were "
                                                   "REGENERATED (the previous ones asserted values "
                                                   "their criterion's semantics do not produce). "
                                                   "Satisfy the NEW oracle honestly and REMOVE any "
                                                   "special-case logic that only mirrored the old "
                                                   "tests."}
                    last_sreason = ""
                    continue
            # COMMIT-SCOPE GATE (user ask 2026-07-03: only intended items reach the commit).
            # Once, at COMPLETE: an auditor classifies each changed non-PROTECTED file as
            # deliverable|scratch; scratch is deleted and the FULL verification re-runs on the
            # pruned tree — red restores everything (over-inclusion is cosmetic, a wrong
            # exclusion destroys work). The model classifies; the gate decides.
            scope_dropped = []
            if scope_audit is not None and not st.get("scope_checked"):
                _progress("commit_scope", "classifying changed files...")
                st["scope_checked"] = True
                protected = {".gitignore"}
                for tid in test_to_criterion:                     # the oracle files, always
                    protected.add(str(tid).split("::")[0])
                for cid in ids:                                   # anything evidence executes
                    for tok in (verify_cmd_for(cid) or []):
                        if "::" in str(tok):
                            protected.add(str(tok).split("::")[0])
                changed = worktree.changed_files(cwd)
                verdicts, scratch = {}, []
                # Classify changed files in parallel; each call is an independent read+audit.
                import concurrent.futures as _scope_cf

                def _audit_one(path):
                    try:
                        head = open(os.path.join(cwd or "", path), errors="replace").read()[:1500]
                    except OSError:
                        head = ""
                    try:
                        return scope_audit(charter, path, head)
                    except Exception:  # noqa: BLE001
                        return "deliverable"   # fail-closed: wrong exclusion is destructive

                _scope_inputs = [p for p in changed if p not in protected]
                with _scope_cf.ThreadPoolExecutor(max_workers=min(8, len(_scope_inputs) or 1)) as _scope_ex:
                    _scope_futs = {p: _scope_ex.submit(_audit_one, p) for p in _scope_inputs}
                for p, fut in _scope_futs.items():
                    v = fut.result()
                    verdicts[p] = v
                    if v == "scratch":
                        scratch.append(p)
                note = ""
                if scratch:
                    snap = {}
                    for p in scratch:
                        fp = os.path.join(cwd, p)
                        try:
                            with open(fp, "rb") as f:
                                snap[p] = f.read()
                            os.remove(fp)
                        except OSError:
                            pass
                    pruned_ok, why_red = True, ""
                    for cid in ids:            # the pruned tree must STILL prove every criterion
                        ev2 = evidence.run(cid, verify_cmd_for(cid), cwd=cwd)
                        if not ev2.passed:
                            pruned_ok, why_red = False, f"evidence {cid} red after prune"
                            break
                    if pruned_ok:
                        reg2 = evidence.run("__scope__", list(regression_cmd or _REGRESSION_CMD),
                                            cwd=cwd)
                        pruned_ok, why_red = gate.regression_gate(reg2)
                    if pruned_ok:
                        scope_dropped = sorted(snap)
                    else:                      # RESTORE every pruned file, commit everything
                        for p, content in snap.items():
                            fp = os.path.join(cwd, p)
                            try:
                                os.makedirs(os.path.dirname(fp) or str(cwd), exist_ok=True)
                                with open(fp, "wb") as f:
                                    f.write(content)
                            except OSError:
                                pass
                        note = f"prune broke verification ({why_red}); all files restored"
                _emit(run_dir, step="commit_scope", dropped=scope_dropped,
                      verdicts=verdicts, note=note)
                _progress("commit_scope",
                          f"{len(scope_dropped)} file(s) dropped as scratch" if scope_dropped
                          else "all files are deliverable",
                          ok=True, dropped=len(scope_dropped), note=note)
                _persist(run_dir, "commit_scope.json",
                         {"dropped": scope_dropped, "verdicts": verdicts, "note": note})
            grounding = _grounding_report(charter, st["evidence_ledger"], judge_verdicts,
                                          test_to_criterion, reg)
            if overfit_advisory:
                # split-vote flags never block; they ride the proof chain as a visible caveat
                grounding["overfit_advisory"] = overfit_advisory
            _emit(run_dir, step="grounding", **grounding)
            _persist(run_dir, "grounding.json", grounding)
            _progress("complete", "all gates passed, merging...", ok=None)
            _progress_event(run_dir, "terminal", terminal="COMPLETE",
                            grounding_summary={c["criterion_id"]: c for c in grounding.get("criteria", [])})
            _emit(run_dir, step="terminal", terminal="COMPLETE")
            # Learnings summary: what this run accomplished
            _n_evidence = len(st.get("evidence_ledger", {}))
            _n_criteria = len(charter.get("dod", []))
            _n_rebuilds = st.get("rebuild_count", 0)
            _n_replans = st.get("replan_count", 0)
            _n_tests = len(test_to_criterion) if test_to_criterion else 0
            _summary = (f"merged: {_n_criteria} criteria met, {_n_tests} tests passed, "
                        f"{_n_evidence} evidence entries"
                        f"{f', {_n_rebuilds} rebuild(s)' if _n_rebuilds else ''}"
                        f"{f', {_n_replans} replan(s)' if _n_replans else ''}")
            _progress("complete", _summary, ok=True)
            _summary_rollup = _run_summary(
                charter, st, test_to_criterion,
                overfit_advisory=overfit_advisory,
                scope_dropped=scope_dropped,
                terminal="COMPLETE")
            _progress("summary", "rollup...", ok=None)
            _progress("summary", _summary_rollup, ok=True)
            return {"terminal": "COMPLETE", "state": st, "trace_path": trace, "reason": sreason,
                    "grounding": grounding, "scope_dropped": scope_dropped}

        if files_changed == 0:     # coder changed nothing AND not complete -> dispatch error
            return _dispatch_error(run_dir, st, "coder made no file change and verification failed")

        # CODE fault: the tests are judge-trusted (a TEST fault was caught up-front before the loop),
        # so red evidence means the CODE is wrong -> feed the failing evidence back and re-IMPLEMENT.
        last_failure = {cid: (ledger[cid].stderr_tail or "")[-400:]
                        for cid in ids if not ledger[cid].passed} or {"oracle": sreason}
        state.on_rebuild_fail(st)
        _emit(run_dir, step="rebuild_fail", rebuild=st["rebuild_count"])
        _progress("rebuild",
                  f"attempt {attempt} evidence failed ({_n_passed}/{_n_total}) → rebuild {st['rebuild_count']}",
                  ok=False, cause="evidence", attempt=attempt, rebuild=st["rebuild_count"],
                  passed=_n_passed, total=_n_total)

    nt_reason = "max_passes exhausted without a terminal decision (bug sentinel)" + (
        f"; last failure: {last_sreason}" if last_sreason else "")
    _progress_event(run_dir, "terminal", terminal="NO_TERMINATION", reason=nt_reason)
    print(f"[devloop] ❌ NO_TERMINATION: {nt_reason}", file=sys.stderr, flush=True)
    _emit(run_dir, step="terminal", terminal="NO_TERMINATION", reason=nt_reason)
    return {"terminal": "NO_TERMINATION", "state": st, "trace_path": trace, "reason": nt_reason}
