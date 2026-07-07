"""project.py — the project OUTER loop.

Drives a master-TODO of "purposes" through the per-task devloop (runner.run_task): pick a pending
purpose -> read the lessons log into the plan -> attempt -> append a lesson -> update the TODO
(mark the attempt done; enqueue a re-attempt, up to a cap, for any purpose that wasn't achieved).

Autonomous bounded drain: drains the whole backlog unattended, bounded at <= purposes*max_attempts
inner runs. Fail-closed: a purpose is "achieved" ONLY on a real COMPLETE terminal; an ambiguity-
blocked purpose ESCALATES to a human immediately (a re-run reproduces the same block, so it would
just burn the cap); re-attempts are bounded (no infinite enqueue — the termination guard).

─── Two journals, two scopes ─────────────────────────────────────────────────
  LEARNINGS.jsonl  (under <write-safe>/devloop-traces/)
    Bridge-level, repo-wide journal written by devloop_bridge._append_run_learning.
    One entry per devloop RUN. Carries the rich commit-message sections
    (learnings_text, references, failure_conditions) plus mechanical fields.
    Consumed by:
      - devloop_bridge._build_rich_commit_message (prior runs inform the next commit)
      - dispatch._mechanical_learnings_fallback (consolidated design guidance)
      - humans / the consolidator reviewing devloop-traces/

  LESSONS.jsonl  (under <project_dir>/.devloop/)
    Project-local journal written by project.run_project. One entry per project
    ATTEMPT. Same schema as LEARNINGS.jsonl so the same readers can consume it.
    Consumed by:
      - project.run_project itself (folded into the next attempt's request under
        config.LESSONS_HEADER, deduplicated via _add_part/seen_parts)
      - project._render_report (human project summary)

  Shared entry schema:
    {
      "ts": ISO-8601 UTC,
      "purpose_id"/"run": identifier,
      "terminal": "COMPLETE" | "HUMAN_REVIEW" | "NO_TERMINATION" | ...,
      "achieved": bool,
      "changed_files": [str],
      "reason": str,
      "lesson": str,             # design-oriented one-liner (back-compat)
      "learnings_text": str,     # rich LEARNINGS section content
      "references": str,         # rich REFERENCES section content
      "failure_conditions": [str]  # AVOID:/DO NOT lines for planning
    }

Artifacts under <project_dir>/.devloop/ (default project_dir = root):
  PLAN.json     — the master-TODO, source of truth (state.atomic_write_json)
  LESSONS.jsonl — append-only lessons (state.append_learning; read by state.read_learnings)
Resume validates the PLAN schema and root purposes, refusing foreign or corrupt state.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import config
import runner
import state
import worktree

_PLAN = "PLAN.json"
_LESSONS = "LESSONS.jsonl"


def _plan_path(pdir):
    return os.path.join(pdir, ".devloop", _PLAN)


def _lessons_path(pdir):
    return os.path.join(pdir, ".devloop", _LESSONS)


def _seed_plan(purposes):
    return {"schema_version": 1,
            "items": [{"id": f"p{i}", "purpose": p, "status": "pending", "attempt_n": 1,
                       "parent_id": None, "attempts": []} for i, p in enumerate(purposes, 1)]}


def _load_plan(pdir):
    """Fail-safe load (mirrors state.load_checkpoint): None on missing/corrupt/wrong-shape."""
    p = _plan_path(pdir)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return None
    sv = d.get("schema_version")
    if type(sv) is not int or sv != 1:
        return None
    return d


def _refused_plan_summary(pdir, lessons_path, reason, items=None):
    """Return a fail-closed summary without persisting or attempting foreign/corrupt state."""
    if items is None:
        try:
            with open(_plan_path(pdir), encoding="utf-8") as f:
                raw = json.load(f)
            items = raw.get("items") if isinstance(raw, dict) else None
        except (OSError, json.JSONDecodeError):
            items = None
    recovered = []
    if isinstance(items, list):
        for i, item in enumerate(items, 1):
            item = dict(item) if isinstance(item, dict) else {}
            item.setdefault("id", f"refused-{i}")
            item.setdefault("purpose", "(invalid PLAN.json item)")
            item.setdefault("attempts", [])
            item["status"] = "blocked"
            item["blocked_reason"] = reason
            recovered.append(item)
    if not recovered:
        recovered = [{"id": "refused", "purpose": "(unreadable PLAN.json)",
                      "status": "blocked", "blocked_reason": reason, "attempts": []}]
    path = _plan_path(pdir)
    report = f"Drain state at {path} {reason}; inspect it or re-run with --fresh."
    return {"plan_path": path, "lessons_path": lessons_path, "achieved": [],
            "blocked": [it["id"] for it in recovered], "items": recovered, "report": report}


def _save_plan(pdir, plan):
    state.atomic_write_json(_plan_path(pdir), plan)


def _next_pending(plan):
    return next((it for it in plan["items"] if it["status"] == "pending"), None)


def _branch_exists(repo, branch):
    return worktree._git(repo, "rev-parse", "--verify", "--quiet",
                         f"refs/heads/{branch}", check=False).returncode == 0


def _attempt_name(item, repo):
    """Fresh per attempt (create_worktree collides otherwise) AND probed against branches that
    already exist in `repo`: a re-run of the same project over leftovers from a prior run (a
    kept-for-review devloop/* branch, a crash) must suffix -r2, -r3, … instead of aborting the
    whole drain on create_worktree's 'branch already exists'."""
    base = f"{item['id']}-a{len(item['attempts']) + 1}"
    name, n = base, 2
    while _branch_exists(repo, f"devloop/{name}"):
        name, n = f"{base}-r{n}", n + 1
    return name


def _new_id(plan):
    return f"p{len(plan['items']) + 1}"


def _blocked_on_ambiguity(charter):
    return any(q.get("blocking") for q in (charter.get("open_questions") or []))


def classify_outcome(terminal, charter, result=None):
    """achieved | escalate | reattempt — the fail-closed heart of the outer loop."""
    if terminal == "COMPLETE":
        return "achieved"
    # Escalate (human, never re-attempt) when re-running would just reproduce the block: the
    # runner marked the HUMAN_REVIEW non-retryable (a deterministic gate on the request text,
    # e.g. vague_goal_gate), a blocking open_question, OR an empty/invalid DoD (the planner
    # couldn't produce a checkable spec at all).
    if terminal == "HUMAN_REVIEW" and (result or {}).get("retryable") is False:
        return "escalate"
    if terminal == "HUMAN_REVIEW" and (_blocked_on_ambiguity(charter) or not charter.get("dod")):
        return "escalate"
    return "reattempt"                                          # NO_TERMINATION / back-off / coverage -> lessons can help


def _default_lesson(item, terminal, changed_files, reason):
    """Deterministic lesson text (no LLM). Design-oriented, NOT a status line.

    The lesson field is an EDUCATIONAL record: what was attempted, whether the
    thesis held, and what was learned. P1-5 fix: status metrics (file counts)
    are stripped — they live in the changed_files field, not the lesson.
    Injectable via make_lesson for an ask-backed synth later.
    """
    purpose = item['purpose'][:90]
    if terminal == "COMPLETE":
        return f"Confirmed approach: {purpose}"
    elif reason:
        return f"REFUTED THESIS: {purpose} — {reason[:200]}"
    else:
        return f"Unresolved: {purpose} — terminal {terminal}"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_changed(res):
    """Changed files for the attempt, best-effort (telemetry, never a loop-killer).
    Prefers the bridge-reported devloop_result.changed_files — pipeline steps arrive with
    the worktree already finalized/REMOVED, so the path diff below would always be [] and
    lessons/reports would claim "changed 0 file(s)" (information loss, review 2026-07-03).
    Falls back to diffing the worktree path (the direct runner path); a non-git path — e.g.
    an injected fake — yields [] instead of raising."""
    bridged = ((res or {}).get("devloop_result") or {}).get("changed_files")
    if bridged:
        return list(bridged)
    path = ((res or {}).get("worktree") or {}).get("path")
    if not path or not os.path.isdir(path):
        return []
    try:
        return worktree.changed_files(path)
    except Exception:   # noqa: BLE001 — diff is best-effort; never abort the project loop on it
        return []


def run_project(repo, root, purposes, *, project_dir=None, run_task=runner.run_task,
                make_lesson=None, max_attempts=config.PROJECT_MAX_ATTEMPTS,
                read_window=config.LEARNINGS_READ_WINDOW, **run_task_kwargs):
    """Drain the master-TODO of `purposes`, one inner run_task per pending item, re-reading lessons
    into each plan and appending a lesson after each attempt. Returns a summary dict incl. a
    human-readable `report`. `run_task` and `make_lesson` are injectable (deterministic tests)."""
    pdir = project_dir or root
    lessons_path = _lessons_path(pdir)
    make_lesson = make_lesson or _default_lesson

    plan_path = _plan_path(pdir)
    if not os.path.exists(plan_path):
        plan = _seed_plan(purposes)
    else:
        plan = _load_plan(pdir)
        if plan is None:
            return _refused_plan_summary(
                pdir, lessons_path, "is unreadable or has an unsupported schema")
        roots = [it.get("purpose") for it in plan["items"]
                 if isinstance(it, dict) and it.get("parent_id") is None]
        if (plan["items"] and not roots) or roots != purposes:
            return _refused_plan_summary(
                pdir, lessons_path, "belongs to a different purpose set", plan["items"])
    for it in plan["items"]:
        if it["status"] == "in_progress":                      # crash recovery: a half-run attempt -> retry it
            it["status"] = "pending"
    _save_plan(pdir, plan)

    # bounded drain: total attempts <= purposes*max_attempts (termination proof); +8 slack as a
    # bug-sentinel backstop (the outer analogue of loop.py's max_passes) so a broken cap can't hang.
    for _ in range(len(plan["items"]) * max_attempts + 8):
        item = _next_pending(plan)
        if item is None:
            break

        # 1. PLAN: read the lessons log, fold into the request (reaches BOTH charter and refine)
        lessons = state.read_learnings(lessons_path, read_window)
        request = item["purpose"]
        if lessons:
            # folded under the shared header so runner.py can strip lessons before the
            # vague_goal_gate (lesson text carries outcome markers/numbers that would otherwise
            # trip the marker screen on every re-attempt)
            # Prefer learnings_text (rich design content); fall back to the design-oriented
            # lesson field. Include failure_conditions as AVOID: lines.
            # P1-4 fix: dedup between learnings_text and failure_conditions — the same
            # AVOID: line may appear in both (learnings_text contains the full LEARNINGS
            # section including AVOID: lines, failure_conditions re-extracts them).
            # Track a normalized lowercased set and skip duplicates.
            parts = []
            seen_parts = set()
            def _add_part(text):
                """Add a part if not already seen (normalized lowercased dedup)."""
                key = " ".join(text.lower().strip().lstrip("-•* ").split())
                if key and key not in seen_parts:
                    seen_parts.add(key)
                    parts.append(text)
            for l in lessons:
                lt = l.get("learnings_text", "")
                if lt:
                    # Strip leading bullet markers from learnings_text (the commit
                    # message uses "- " bullets, but we add our own "- " prefix)
                    lt = lt.lstrip().lstrip("-•* ").lstrip()
                    if len(lt) > 300:
                        lt = lt[:300].rsplit("\n", 1)[0]
                    _add_part(f"- {lt}")
                elif l.get("lesson"):
                    les = l["lesson"]
                    if len(les) > 300:
                        les = les[:300].rsplit("\n", 1)[0]
                    _add_part(f"- {les}")
                fcs = l.get("failure_conditions") or []
                if isinstance(fcs, list):
                    for fc in fcs:
                        # Avoid double-prefixing: if the fc already starts with
                        # AVOID: or DO NOT, don't add another AVOID: prefix
                        fc_stripped = fc.strip()
                        if fc_stripped.startswith(("AVOID:", "DO NOT")):
                            _add_part(f"- {fc_stripped[:200]}")
                        else:
                            _add_part(f"- AVOID: {fc_stripped[:200]}")
            request += ("\n\n" + config.LESSONS_HEADER + "\n" + "\n".join(parts))

        # 2. record the attempt + mark in_progress, persisted BEFORE running (crash-safe; fresh name)
        name = _attempt_name(item, repo)
        item["attempts"].append({"name": name, "terminal": "in_progress", "changed_files": []})
        item["status"] = "in_progress"
        _save_plan(pdir, plan)

        # 3. ATTEMPT the inner devloop
        res = run_task(repo, request, root, name, **run_task_kwargs)
        result = res.get("result") or {}
        terminal = result.get("terminal")
        charter = res.get("charter") or {}
        reason = result.get("reason", "") or ""
        changed = _safe_changed(res)

        # 4a. append a lesson to the journal — RICH fields (P0-1 fix, advisor review 2026-07-05)
        # The bridge (_append_run_learning) writes rich fields to LEARNINGS.jsonl; the project
        # loop writes to LESSONS.jsonl. Both journals are read by the same readers, so the
        # project loop MUST write the same structured shape. Extract rich fields from the
        # run result (the bridge puts them in devloop_result) and from the commit message
        # if available.
        item["attempts"][-1].update(terminal=terminal, changed_files=changed)
        devloop_result = (res or {}).get("devloop_result") or {}
        # N2: the bridge now exposes extracted rich fields directly in devloop_result.
        # Consume them directly instead of re-extracting from commit_message.
        learnings_text = devloop_result.get("learnings_text") or ""
        references_text = devloop_result.get("references") or ""
        failure_conditions = list(devloop_result.get("failure_conditions") or [])
        if not learnings_text and not references_text:
            # DIRECT RUNNER PATH (Fix P9): runner.run_task returns only
            # {"result": res, "worktree": wt, "charter": charter} — no bridge-level
            # devloop_result with rich fields. Synthesize rich fields from the run
            # result so LESSONS.jsonl carries the same design content whether the
            # run went through the bridge or the direct runner path.
            # N3: single import at the top of the synthesis block (was duplicate in if/else).
            try:
                import devloop_bridge as _br
                synthetic = _br._build_rich_commit_message(
                    name, item["purpose"], result, charter, terminal, reason, None)
                learnings_text = _br._extract_commit_section(synthetic, "LEARNINGS")
                references_text = _br._extract_commit_section(synthetic, "REFERENCES")
                failure_conditions = _br._extract_failure_conditions(
                    learnings_text, terminal or "RUN", reason)
            except Exception:
                pass  # best-effort: mechanical fallback is still recorded
        # Also extract failure conditions from reason even without commit message or synthesis
        if not failure_conditions and terminal != "COMPLETE" and reason:
            failure_conditions = [f"DO NOT repeat: {reason[:200]}"]

        state.append_learning(lessons_path, {
            "ts": _now(), "purpose_id": item["id"], "purpose": item["purpose"],
            "attempt_n": item["attempt_n"], "name": name, "terminal": terminal,
            "achieved": terminal == "COMPLETE", "changed_files": changed, "reason": reason,
            "lesson": make_lesson(item, terminal, changed, reason),
            # --- Rich journaling fields (P0-1, advisor review 2026-07-05) ---
            "learnings_text": learnings_text[:2000] if learnings_text else "",
            "references": references_text[:1000] if references_text else "",
            "failure_conditions": failure_conditions,
        })

        # 4b. update the TODO (fail-closed classifier + cap)
        outcome = classify_outcome(terminal, charter, result)
        if outcome == "achieved":
            item["status"] = "completed"
        elif outcome == "escalate":
            item["status"] = "blocked"
            qs = "; ".join(q.get("text", "") for q in (charter.get("open_questions") or []) if q.get("blocking"))
            item["blocked_reason"] = "ambiguity — " + (reason or qs or "blocking open question")[:160]
        else:  # reattempt
            if item["attempt_n"] < max_attempts:               # <-- TERMINATION GUARD (mutant #1)
                item["status"] = "completed"
                plan["items"].append({
                    "id": _new_id(plan), "parent_id": item["id"], "attempt_n": item["attempt_n"] + 1,
                    "purpose": f"investigate and re-attempt: {item['purpose']} (given lessons learned)",
                    "status": "pending", "attempts": []})
            else:
                item["status"] = "blocked"
                item["blocked_reason"] = f"re-attempt cap ({max_attempts}) exhausted; not achieved"
        _save_plan(pdir, plan)

    return _summarize(plan, pdir, lessons_path, read_window)


def _summarize(plan, pdir, lessons_path, read_window):
    items = plan["items"]
    achieved = [it for it in items if it["attempts"] and it["attempts"][-1].get("terminal") == "COMPLETE"]
    blocked = [it for it in items if it["status"] == "blocked"]
    lessons = state.read_learnings(lessons_path, read_window)
    return {"plan_path": _plan_path(pdir), "lessons_path": lessons_path,
            "achieved": [it["id"] for it in achieved], "blocked": [it["id"] for it in blocked],
            "items": items, "report": _render_report(items, achieved, blocked, lessons)}


def _render_report(items, achieved, blocked, lessons):
    """Human-facing project report: what was done, lessons learned, where we stand (task #21)."""
    out = [f"# Project report — {len(achieved)} achieved, {len(blocked)} blocked, {len(items)} purposes attempted", ""]
    out.append("## What was done")
    out += [f"- ✓ {it['purpose']}  ({len(it['attempts'][-1].get('changed_files') or [])} file(s): "
            f"{', '.join((it['attempts'][-1].get('changed_files') or [])[:6]) or '—'})" for it in achieved] \
        or ["- (nothing achieved)"]
    out += ["", "## Lessons learned"]
    # Prefer learnings_text (rich design content); fall back to lesson field.
    lesson_lines = []
    for l in lessons[-12:]:
        lt = l.get("learnings_text", "")
        if lt:
            lt = lt.lstrip().lstrip("-•* ").lstrip()
            if len(lt) > 300:
                lt = lt[:300].rsplit("\n", 1)[0]
            lesson_lines.append(f"- {lt}")
        elif l.get("lesson"):
            les = l["lesson"]
            if len(les) > 300:
                les = les[:300].rsplit("\n", 1)[0]
            lesson_lines.append(f"- {les}")
    out += lesson_lines or ["- (none recorded)"]
    out += ["", "## Where we stand"]
    for it in blocked:
        out.append(f"- ✗ BLOCKED: {it['purpose']}  — {it.get('blocked_reason', 'needs human review')}")
    pending = [it for it in items if it["status"] == "pending"]
    if pending:
        out.append(f"- ⚠ {len(pending)} purpose(s) still pending (loop did not fully drain)")
    if not blocked and not pending:
        out.append("- all purposes resolved; nothing outstanding")
    return "\n".join(out)
