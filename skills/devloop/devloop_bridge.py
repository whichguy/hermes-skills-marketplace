"""devloop_bridge — the seam between ask/scripts/pipeline.py and the devloop engine.

pipeline.py's build_code/debug_cascade modes call devloop's runner.run_task through this bridge
(the legacy sdlc.* engine was retired 2026-07-01 after the go/no-go spike). DEVLOOP_ENABLED is a
kill-switch that DEFAULTS ON; 0 falls back to a single model dispatch (pipeline seam only).

Two design decisions are baked in (user-chosen):
  - AUTO-MERGE on COMPLETE: every gate passed, so the branch merges into the target's current
    branch; any merge failure degrades to a branch-for-review pointer. See _summary().
  - SCRATCH BY DEFAULT: with no explicit repo, work happens in a fresh git-init'd scratch
    workspace under the write-safe root — NEVER the caller's cwd (the old cwd-if-git fallback
    walked UP and could target the ~/.hermes DATA repo itself; verified hazard, deleted 2026-07-02).

─── Two journals, two scopes ─────────────────────────────────────────────────
  LEARNINGS.jsonl  (under <write-safe>/devloop-traces/)
    Bridge-level, repo-wide journal written by _append_run_learning. One entry per
    devloop RUN. Carries rich commit-message sections (learnings_text, references,
    failure_conditions) plus mechanical fields. Consumed by:
      - _build_rich_commit_message (prior runs inform the next synthesized commit)
      - dispatch._mechanical_learnings_fallback (consolidated design guidance)
      - humans / the consolidator reviewing devloop-traces/

  LESSONS.jsonl  (under each project_dir/.devloop/)
    Project-local journal written by project.run_project. Same schema so the same
    readers can consume it; it carries the per-project-attempt learning history.
    See project.py for its consumers.

  Shared entry schema:
    {
      "ts": ISO-8601 UTC,
      "run" / project "purpose_id": identifier,
      "terminal": "COMPLETE" | "HUMAN_REVIEW" | "NO_TERMINATION" | ...,
      "intent" / "purpose": str,
      "n_criteria"/"attempt_n": int,
      "n_trusted": int,
      "rebuilds": int,
      "reason": str,
      "lesson": str,             # design-oriented one-liner (back-compat)
      "learnings_text": str,     # rich LEARNINGS section content
      "references": str,         # rich REFERENCES section content
      "failure_conditions": [str]  # AVOID:/DO NOT lines for planning
    }

Returns the same dict shape pipeline.py builds for the single-dispatch path
({content, session_id, elapsed, error, devloop_result, pipeline_mode}) so the call site stays thin.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

# Write-safe root (container default /opt/data); scratch repos + durable traces live under it.
# Run worktrees live IN-REPO at <repo>/.worktrees (user decision 2026-07-02, worktree.py).
_WRITE_SAFE = os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data")
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def devloop_enabled() -> bool:
    """devloop is the SDLC engine (the legacy sdlc.* engine was retired). DEVLOOP_ENABLED is a
    kill-switch that DEFAULTS ON — set it to a falsey value (0/false/no/off) to disable devloop and
    fall back to a single model dispatch."""
    return os.environ.get("DEVLOOP_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def _is_git_repo(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    r = subprocess.run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


# Sentinel: "build in a FRESH scratch workspace, never look at cwd". THE default for every
# entrypoint (CLI and pipeline) when no explicit repo is given — an implicit cwd-if-git fallback
# must NEVER fire from an agent session (verified hazard: the agent's terminal cwd can be the
# ~/.hermes DATA repo itself, and cwd-if-git would cut devloop branches off it and auto-merge
# into it on COMPLETE). Identity-checked (`repo is SCRATCH`); None is a fail-safe alias.
SCRATCH = object()


def _scratch_repo(name: str) -> str:
    """A fresh git-init'd scratch workspace under the write-safe root (greenfield). Gets one
    commit so `git worktree add` (which needs a HEAD) works. Idempotent per name.

    The init check requires the workspace's OWN .git — NOT _is_git_repo, whose upward walk
    made this a silent no-op inside an enclosing repo (live acceptance-run catch 2026-07-01:
    /opt/data IS the ~/.hermes data repo, so every "scratch" resolved to it and run branches
    were cut off the DATA repo; only merge_branch's dirty-guard stopped an auto-merge into
    the user's uncommitted working tree)."""
    scratch = os.path.join(_WRITE_SAFE, "devloop-workspaces", name)
    os.makedirs(scratch, exist_ok=True)
    if not os.path.isdir(os.path.join(scratch, ".git")):
        subprocess.run(["git", "-C", scratch, "init", "-q"], check=True)
        subprocess.run(["git", "-C", scratch, "config", "user.email", "devloop@hermes"], check=True)
        subprocess.run(["git", "-C", scratch, "config", "user.name", "devloop"], check=True)
        readme = os.path.join(scratch, "README.md")
        if not os.path.exists(readme):
            open(readme, "w").write("# devloop workspace\n")
        subprocess.run(["git", "-C", scratch, "add", "."], check=True)
        subprocess.run(["git", "-C", scratch, "commit", "-qm", "init"], check=True)
    return scratch


def _worktree_mod():
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    import worktree  # noqa: E402  (devloop's own, same dir)
    return worktree


def _regression_check(cwd):
    """Whole-suite regression on a SYNCED tree (pre-merge sync, user decision 2026-07-02) —
    same semantics as the loop's own gate: pytest exit 0 passes, exit 5 (no tests collected)
    is a vacuous pass, anything else is fail-closed. Returns (ok, reason)."""
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    import evidence  # noqa: E402  (devloop's own, same dir)
    import gate      # noqa: E402
    ev = evidence.run("__sync__", [sys.executable, "-m", "pytest", "-q"], cwd=cwd)
    return gate.regression_gate(ev)


def _conflict_resolver(path, conflicted):
    """LLM merge-conflict resolution (user decision 2026-07-02). dispatch is imported at CALL
    time so a broken dispatch only degrades runs that actually hit a conflict — worktree's guard
    catches any exception here as a fail-closed refusal."""
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    import dispatch  # noqa: E402
    return dispatch.merge_resolver_via_ask()(path, conflicted)


def _merge_fixer(path, why):
    """ONE bounded LLM fix for a red combined tree (user decision 2026-07-02); same lazy-import
    fail-closed shape as _conflict_resolver."""
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    import dispatch  # noqa: E402
    return dispatch.merge_fixer_via_ask()(path, why)


def _repo_status(repo):
    """{path: XY-code} from NUL-separated `git status --porcelain -z` with quotePath OFF —
    robust to spaces, quotes, tabs, and non-ASCII in names (the default quoted format made
    the boundary guard silently miss such paths). A rename/copy entry consumes its second
    NUL field and records BOTH sides: the new path with its code, the old path as a
    synthetic deleted-tracked entry (it must be restorable too). None when repo isn't a
    git repo."""
    try:
        r = subprocess.run(["git", "-C", repo, "-c", "core.quotePath=false",
                            "status", "--porcelain", "-z"],
                           capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    out = {}
    fields = r.stdout.split("\0")
    i = 0
    while i < len(fields):
        ln = fields[i]
        i += 1
        if len(ln) < 4:
            continue
        code, path = ln[:2], ln[3:]
        out[path] = code
        if code[0] in ("R", "C") and i < len(fields):   # next field = the ORIGINAL path
            out[fields[i]] = " D"
            i += 1
    return out


def _restore_boundary_breach(repo, pre):
    """WORKTREE-BOUNDARY GUARD (live-caught 2026-07-03): devloop's phase dispatchers are
    tool-using agents; one escaped its .worktrees checkout during a live run and deleted a
    tracked file in the TARGET repo's main working tree. All legitimate devloop output
    reaches the repo as COMMITS (branch/merge) — the main working tree must come out of a
    run exactly as dirty as it went in. Paths that are newly dirty after the run are agent
    debris: untracked/staged-new ones deleted (and unstaged), tracked ones restored from
    HEAD. Pre-existing dirt (a user's uncommitted work) is NEVER touched.

    Returns (restored, failed) — both VERIFIED against a fresh status recompute, so a
    restore that didn't actually take can never be reported as restored (review 2026-07-03:
    the earlier per-path bookkeeping trusted its own actions and could lie)."""
    if pre is None:
        return [], []
    post = _repo_status(repo)
    if post is None:
        return [], []
    new = {p: code for p, code in post.items() if p not in pre}
    for p, code in new.items():
        target = os.path.join(repo, p)
        try:
            # ??/A = never existed in HEAD; R/C new-side = staged under a name HEAD doesn't
            # have (its OLD side was recorded separately and takes the checkout branch)
            if code == "??" or code[0] in ("A", "R", "C"):
                if code != "??":                         # staged-new — unstage first
                    subprocess.run(["git", "-C", repo, "rm", "-q", "--cached", "--", p],
                                   capture_output=True, text=True)
                if os.path.islink(target) or os.path.isfile(target):
                    os.remove(target)
                elif os.path.isdir(target):
                    import shutil
                    shutil.rmtree(target)
            else:                                        # tracked in HEAD: restore index+tree
                subprocess.run(["git", "-C", repo, "checkout", "-q", "HEAD", "--", p],
                               capture_output=True, text=True)
        except OSError:
            continue                                     # the verification below reports it
    after = _repo_status(repo)
    if after is None:
        return [], sorted(new)
    restored = sorted(p for p in new if p not in after)
    failed = sorted(p for p in new if p in after)
    return restored, failed


def _preserve_trace(trace_path, name: str):
    """Copy the WHOLE run_dir — trace, checkpoint, stage artifacts (charter/design_spec/
    rendered_tests/judge_verdicts/attempts/grounding), and any DEVLOOP_DEBUG dispatch captures —
    out of the (about-to-be-removed) worktree to <write-safe>/devloop-traces/<name>/ (user ask
    2026-07-03: every loop stage inspectable after the run). Returns the durable trace.jsonl
    path. Best-effort telemetry: on any failure the original path is returned."""
    if not trace_path or not os.path.isfile(str(trace_path)):
        return trace_path
    try:
        import shutil
        dest_dir = os.path.join(_WRITE_SAFE, "devloop-traces", name)
        shutil.copytree(os.path.dirname(str(trace_path)), dest_dir, dirs_exist_ok=True)
        return os.path.join(dest_dir, os.path.basename(str(trace_path)))
    except Exception:   # noqa: BLE001
        return trace_path


def _summary(terminal: str, fin: dict, reason: str, blocking: list, trace_path,
             merged: dict | None = None, grounding: dict | None = None,
             kept: bool = False, scope_dropped: list | None = None) -> str:
    """Human outcome line(s). COMPLETE auto-merges (user decision 2026-07-01): a successful merge
    reports WHERE THE CODE LANDED; a failed merge degrades to the branch-for-review pointer with
    an explicit why. HUMAN_REVIEW reads as a NEEDS-YOUR-INPUT outcome, not an engine failure.
    A COMPLETE also ships its GROUNDING (user ask 2026-07-02): the per-promise proof chain —
    criterion -> tests -> judge votes -> passing evidence."""
    merged = merged or {"merged": False, "reason": "", "target": None}
    branch = fin.get("branch") if fin.get("branch_kept") else None
    changed = fin.get("changed", [])
    lines = []
    if terminal == "HUMAN_REVIEW":
        lines.append(f"devloop NEEDS YOUR INPUT — {reason or 'routed to human review'}")
        lines += [f"  ? {q}" for q in blocking[:6]]
    elif terminal == "COMPLETE" and merged["merged"]:
        sync_note = ""
        if merged.get("synced"):
            bits = ["target had advanced; combined tree re-verified"]
            if merged.get("resolved"):
                bits.append("conflicts resolved by coder")
            if merged.get("fixed"):
                bits.append("post-sync fix applied")
            sync_note = " (" + "; ".join(bits) + ")"
        lines.append(f"devloop COMPLETE — merged into '{merged['target']}' at "
                     f"{fin.get('repo_path') or ''}".rstrip() + sync_note)
    elif terminal == "COMPLETE" and kept and branch:
        lines.append(f"devloop COMPLETE — branch {branch} kept as requested (--keep-branch); "
                     f"merge with: git -C {fin.get('repo_path') or '<repo>'} "
                     f"merge --squash {branch} && git -C {fin.get('repo_path') or '<repo>'} "
                     f"commit -m 'devloop: squash-merge {branch}'")
    elif terminal == "COMPLETE" and branch:
        lines.append(f"devloop COMPLETE — auto-merge failed ({merged['reason'] or 'unknown'}); "
                     f"branch {branch} left for review")
    else:
        lines.append(f"devloop {terminal} — " + (
            f"branch {branch} (committed, left for review)" if branch
            else "no reviewable artifact produced"))
        if terminal != "COMPLETE" and reason:
            lines.append(f"reason: {reason}")
    if terminal == "HUMAN_REVIEW" and branch:
        lines.append(f"partial work committed on branch {branch} (left for review)")
    if grounding and grounding.get("criteria"):
        # C8 (user ask 2026-07-03): EVERY terminal ships its chain — on HUMAN_REVIEW the ✗ rows
        # say exactly which promises were left unproven and where the chain broke.
        lines.append("grounding (promise -> proof):")
        for it in grounding["criteria"][:8]:
            jt = sum(1 for x in (it.get("judges") or {}).values() if x)
            mark = "✓" if it.get("evidence_passed") else "✗"
            lines.append(f"  {mark} {it.get('criterion_id')}: {(it.get('criterion') or '')[:70]} — "
                         f"{len(it.get('tests') or [])} test(s), judges {jt}/2, evidence "
                         f"{'PASS' if it.get('evidence_passed') else 'FAIL'}")
        if grounding.get("overfit_advisory"):
            lines.append(f"  ⚠ overfit advisory (one auditor flagged, not blocking): "
                         f"{', '.join(grounding['overfit_advisory'])}")
    if scope_dropped:
        lines.append(f"excluded {len(scope_dropped)} scratch file(s) from the commit: "
                     f"{', '.join(scope_dropped[:10])}")
    lines.append(f"changed {len(changed)} file(s): {', '.join(changed[:20]) or '—'}")
    if trace_path:
        lines.append(f"trace: {trace_path}")
    return "\n".join(lines)


def _build_rich_commit_message(name: str, request: str, result: dict, charter: dict,
                                terminal: str | None, reason: str, trace_path: str | None) -> str:
    """Build a rich commit message using an LLM to synthesize the run's story.

    Every devloop commit includes:
    - INTENTION: what the request asked for
    - THESIS: what the build attempted and whether it worked out
    - LEARNINGS: key observations synthesized from the trace + prior learnings file
    - REFERENCES: git positions and trace paths for future reference

    The LLM reads:
    - The run trace (evidence, judge verdicts, rebuilds, grounding)
    - The devloop learnings file (accumulated lessons from prior runs)
    - Recent git log (prior commits that informed this build)
    And synthesizes them into a structured commit message.

    Falls back to a template message if the LLM is unavailable.
    """
    import json as _json

    terminal = terminal or "RUN"
    intent = (request or "").strip().split("\n")[0][:120]

    # --- Gather context for the LLM ---

    # 1. Trace summary (key facts the LLM needs)
    grounding = result.get("grounding") or {}
    criteria = grounding.get("criteria") or charter.get("dod") or []
    n_criteria = len(criteria)
    n_trusted = sum(1 for c in criteria
                    if isinstance(c, dict) and
                    all(j for j in [c.get("judges", {}).get("a"), c.get("judges", {}).get("b")]))
    n_evidence = sum(1 for c in criteria
                     if isinstance(c, dict) and c.get("evidence_passed"))
    regression_exit = grounding.get("regression_exit")
    rebuilds = result.get("rebuilds", 0)
    changed_files_list = grounding.get("files") or result.get("files_changed") or []
    trace_ref = trace_path or "(trace not preserved)"

    # 2. Read the devloop learnings file (accumulated lessons from prior runs)
    learnings_text = ""
    try:
        learnings_path = os.path.join(_WRITE_SAFE, "devloop-traces", "LEARNINGS.jsonl")
        if os.path.isfile(learnings_path):
            with open(learnings_path) as f:
                lines = f.readlines()[-20:]  # last 20 learnings
            learnings = [_json.loads(l) for l in lines if l.strip()]
            # Prefer the rich learnings_text (design content); fall back to the
            # lesson field (now also design-oriented, not status). Include
            # failure_conditions as AVOID: lines for the LLM to reference.
            parts = []
            for l in learnings:
                if not isinstance(l, dict):
                    continue
                lt = l.get("learnings_text", "")
                if lt:
                    lt = lt.lstrip().lstrip("-•* ").lstrip()
                    if len(lt) > 200:
                        lt = lt[:200].rsplit("\n", 1)[0]
                    parts.append(f"  - {lt}")
                elif l.get("lesson"):
                    les = l["lesson"]
                    if len(les) > 200:
                        les = les[:200].rsplit("\n", 1)[0]
                    parts.append(f"  - {les}")
                fcs = l.get("failure_conditions") or []
                if isinstance(fcs, list):
                    for fc in fcs:
                        fc_stripped = fc.strip()
                        if fc_stripped.startswith(("AVOID:", "DO NOT")):
                            parts.append(f"  {fc_stripped[:150]}")
                        else:
                            parts.append(f"  AVOID: {fc_stripped[:150]}")
            learnings_text = "\n".join(parts)
    except Exception:
        pass

    # 3. Recent git log (prior commits that informed this build)
    git_log = ""
    repo_path = result.get("repo_path") or os.environ.get("DEVLOOP_REPO", "")
    try:
        if repo_path and os.path.isdir(repo_path):
            r = subprocess.run(
                ["git", "-C", repo_path, "log", "--oneline", "-10"],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                git_log = r.stdout.strip()
    except Exception:
        pass

    # 4. Read the full trace if available (rich detail for the LLM)
    trace_summary = ""
    try:
        if trace_path and os.path.isfile(trace_path):
            with open(trace_path) as f:
                trace_lines = f.readlines()[-30:]  # last 30 trace events
            trace_summary = "".join(trace_lines)
    except Exception:
        pass

    # --- Dispatch the LLM to synthesize the commit message ---
    # Skip the LLM call in test mode (HERMES_BIN stubs or DEVLOOP_NO_COMMIT_LLM set)
    # to avoid hanging tests on a real model call. The template fallback is used instead.
    _llm_ok = False
    if os.environ.get("DEVLOOP_NO_COMMIT_LLM") != "1":
        try:
            if _THIS_DIR not in sys.path:
                sys.path.insert(0, _THIS_DIR)
            import dispatch as _dispatch

            # Don't fire a real LLM call if HERMES_BIN is a test stub
            # or if there's no real grounding data (test fake result)
            hermes_bin = getattr(_dispatch, "HERMES_BIN", "")
            has_real_data = bool(grounding.get("criteria") or trace_summary)
            if hermes_bin and not str(hermes_bin).startswith("/tmp/") and has_real_data:
                prompt = (
                    "You are writing a git commit message for an autonomous coding loop (devloop) run.\n"
                    "Synthesize the run's story into a structured commit message with these sections:\n\n"
                    "INTENTION: What the request asked for (1-2 sentences)\n"
                    "THESIS: What the build attempted, whether it worked out, and the key outcome\n"
                    "LEARNINGS: Key observations from this run — what went well, what failed, what was\n"
                    "  surprising, what patterns emerged. Reference prior learnings if relevant.\n"
                    "  CRITICALLY: include failure conditions — things that did NOT work and should NOT\n"
                    "  be tried again. These are the most valuable signals for future runs. Prefix\n"
                    "  each failure condition with 'AVOID:' so the journal extractor can find them.\n"
                    "REFERENCES: Git positions (SHAs from the git log), trace path, and any prior\n"
                    "  commits that were material in making this change. Use exact SHAs. Include key\n"
                    "  file paths or symbols that were critical to the solution.\n\n"
                    "RULES:\n"
                    "- Be concise but specific — no boilerplate, no disclaimers\n"
                    "- Use exact SHAs from the git log when referencing prior commits\n"
                    "- If the run failed, the THESIS should say what went wrong and what was learned\n"
                    "- If prior learnings informed this build, reference them in LEARNINGS\n"
                    "- If a prior learning was CONTRADICTED or SUPERSEDED by this run, state that\n"
                    "  explicitly — the latest run wins, and the consolidator needs to know\n"
                    "- Output ONLY the commit message body (no code fence, no preamble)\n"
                    "- Start with a one-line summary: devloop <TERMINAL>: <name>\n\n"
                    f"RUN DATA:\n"
                    f"  Name: {name}\n"
                    f"  Terminal: {terminal}\n"
                    f"  Reason: {reason or '(none)'}\n"
                    f"  Intent: {intent}\n"
                    f"  Criteria: {n_criteria} total, {n_trusted} trusted by both judges, {n_evidence} evidence passed\n"
                    f"  Regression: exit {regression_exit}\n"
                    f"  Rebuilds: {rebuilds}\n"
                    f"  Files changed: {', '.join(changed_files_list[:10]) or '(unknown)'}\n"
                    f"  Trace path: {trace_ref}\n\n"
                )
                if learnings_text:
                    prompt += f"PRIOR LEARNINGS (from devloop-traces/LEARNINGS.jsonl):\n{learnings_text}\n\n"
                if git_log:
                    prompt += f"RECENT GIT LOG (reference exact SHAs in REFERENCES):\n{git_log}\n\n"
                if trace_summary:
                    prompt += f"TRACE EVENTS (last 30 from this run):\n{trace_summary}\n\n"

                # Use the planner model (fast, good at synthesis) with a short timeout
                out, rc = _dispatch._chat(prompt, _dispatch.PLANNER, timeout=120)
                out = (out or "").strip()
                if out and not out.startswith("dispatch error"):
                    _llm_ok = True
                    return out
        except Exception:
            pass  # fall through to template

    # --- Fallback: template message (if LLM unavailable or skipped) ---
    # P8: design-oriented, NOT status lines. The LEARNINGS section carries
    # educational content (confirmed approach / refuted thesis), not raw metrics.
    if terminal == "COMPLETE":
        thesis = "All gates passed — the approach is confirmed"
        learning_line = f"Confirmed approach: {intent}"
    elif reason:
        thesis = f"Did not complete — {terminal}. The approach needs revision."
        learning_line = f"REFUTED THESIS: {reason[:200]}"
    else:
        thesis = f"Did not complete — {terminal}"
        learning_line = f"Unresolved: {intent} — terminal {terminal}"
    msg = (
        f"devloop {terminal}: {name}\n\n"
        f"INTENTION:\n  {intent}\n\n"
        f"THESIS:\n  {thesis}\n"
        f"  {n_trusted}/{n_criteria} trusted; {n_evidence}/{n_criteria} evidence; "
        f"regression exit {regression_exit}; {rebuilds} rebuilds\n\n"
        f"LEARNINGS:\n"
        f"  - {learning_line}\n"
    )
    if terminal != "COMPLETE" and reason:
        msg += f"  AVOID: {reason[:200]}\n"
    msg += f"\nREFERENCES:\n  Trace: {trace_ref}\n  Run: {name}\n"
    if git_log:
        msg += f"  Recent commits:\n{git_log[:500]}\n"
    return msg


_KNOWN_SECTIONS = frozenset({"INTENTION", "THESIS", "LEARNINGS", "REFERENCES",
                             "SUMMARY", "OUTCOME", "CHANGES", "NOTES"})


def _extract_commit_section(msg: str, section_name: str) -> str:
    """Extract a named section (LEARNINGS, REFERENCES, THESIS, INTENTION) from a
    structured commit message. Returns the section body (stripped), or '' if not found.
    Sections are delimited by 'SECTION_NAME:' at line start and end at the next
    KNOWN section header or end of message. This avoids false-positive cutoffs on
    lines like 'AVOID: ...' which are content, not section headers.
    """
    if not msg:
        return ""
    marker = f"{section_name}:"
    # Case-insensitive search for the section header
    lower_msg = msg.lower()
    marker_lower = marker.lower()
    start = lower_msg.find(marker_lower)
    if start == -1:
        return ""
    # Move past the marker and the rest of its line
    line_end = msg.find("\n", start)
    if line_end == -1:
        return msg[start + len(marker):].strip()
    body_start = line_end + 1
    # Find the next KNOWN section header (a line starting with a known section name + ':')
    remaining = msg[body_start:]
    for line in remaining.split("\n"):
        stripped = line.strip()
        if stripped and ":" in stripped:
            header_word = stripped.split(":")[0]
            # Only cut at KNOWN section headers — 'AVOID:' is content, not a header
            if header_word.upper() in _KNOWN_SECTIONS:
                end_pos = remaining.find(line)
                return remaining[:end_pos].strip()
    return remaining.strip()


def _extract_failure_conditions(learnings_text: str, terminal: str, reason: str) -> list[str]:
    """Extract failure conditions ('what NOT to try again') from the LEARNINGS section
    and/or the run's reason. Returns a list of short failure-condition strings.

    P1-3 fix (advisor review 2026-07-05): tightened to require explicit AVOID:/DO NOT
    prefix on the line, not substring keyword matching. The previous broad keywords
    ('rejected', 'failed', 'wrong', 'never') produced false positives by capturing
    positive observations (e.g., 'The judge correctly rejected weak assertions').
    The commit message LLM prompt already produces AVOID: prefixed lines — rely on
    that structural signal instead of scanning for failure-signal words.

    Heuristics:
    - If the run did NOT complete (terminal != COMPLETE), the reason itself is a failure condition.
    - Lines in LEARNINGS that START with 'AVOID:' or 'DO NOT' are failure conditions.
    """
    conditions = []
    if terminal != "COMPLETE" and reason:
        conditions.append(f"DO NOT repeat: {reason[:200]}")
    if learnings_text:
        for line in learnings_text.split("\n"):
            line = line.strip().lstrip("-•* ")
            if not line:
                continue
            # P1-3: Only match lines that explicitly START with a directive prefix
            upper = line.upper()
            if upper.startswith("AVOID:") or upper.startswith("DO NOT"):
                conditions.append(line[:300])
    # Dedup while preserving order
    seen = set()
    unique = []
    for c in conditions:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[:10]  # cap at 10


def _append_run_learning(name: str, request: str, result: dict, terminal: str | None, reason: str,
                         commit_msg: str | None = None) -> dict:
    """Append this run's key learning to the devloop learnings journal.

    Returns a dict with the extracted rich fields (learnings_text, references,
    failure_conditions) so callers (e.g. _run) can pass them through to
    devloop_result without re-extracting (N2: eliminate triple-extraction).

    This accumulates lessons across runs so future commit messages and the
    project outer loop can reference them. The learnings file lives at
    devloop-traces/LEARNINGS.jsonl (one JSON object per line, append-only).

    RICH JOURNALING (user ask 2026-07-05): when commit_msg is provided (the LLM-
    synthesized rich commit message), the LEARNINGS, REFERENCES, and failure-
    conditions sections are extracted and journaled as structured fields. This
    ensures key references, learnings, and 'what not to try again' patterns are
    carried forward across runs — not just a mechanical status line. If there's
    a contradiction with a prior journal entry, the LATEST entry wins (enforced
    by the git history consolidator's 'latest information wins' rule).
    """
    try:
        import json as _json
        from datetime import datetime, timezone
        if _THIS_DIR not in sys.path:
            sys.path.insert(0, _THIS_DIR)
        import state as _state

        grounding = result.get("grounding") or {}
        criteria = grounding.get("criteria") or []
        n_criteria = len(criteria)
        n_trusted = sum(1 for c in criteria
                        if isinstance(c, dict) and
                        all(j for j in [c.get("judges", {}).get("a"), c.get("judges", {}).get("b")]))
        rebuilds = result.get("rebuilds", 0)
        intent = (request or "").strip().split("\n")[0][:100]

        # Extract structured sections from the rich commit message (if provided)
        learnings_text = ""
        references_text = ""
        failure_conditions: list[str] = []
        if commit_msg:
            learnings_text = _extract_commit_section(commit_msg, "LEARNINGS")
            references_text = _extract_commit_section(commit_msg, "REFERENCES")
            failure_conditions = _extract_failure_conditions(learnings_text, terminal or "RUN", reason)
        else:
            # No commit message — still extract failure conditions from reason
            failure_conditions = _extract_failure_conditions("", terminal or "RUN", reason)

        # The journal entry's 'lesson' field is DESIGN-ORIENTED, not status.
        # It carries factual observations, refuted theses, and design learnings —
        # the educational residue of this run. The mechanical status metrics
        # (n_trusted, rebuilds, terminal) live in their own fields and are NOT
        # the lesson. If the commit message provided rich LEARNINGS, the lesson
        # IS those learnings (the design content). If not, we synthesize a
        # design-oriented line from the reason + terminal, never a bare status.
        # Back-compat: readers that only consume l.get("lesson") still get a
        # useful string; the structured fields carry the full rich content.
        if learnings_text:
            lesson_line = learnings_text[:500]
        elif terminal != "COMPLETE" and reason:
            # A failure: the lesson is what we learned went wrong (design-level)
            lesson_line = f"REFUTED THESIS: {reason[:300]}"
        else:
            # No rich learnings and no failure — a clean run with no surprises.
            # Record the intent as a confirmed thesis. P1-5: no status metrics
            # (rebuilds count) in the lesson field — that's telemetry, not design.
            lesson_line = f"Confirmed approach: {intent}"

        lesson = {
            "ts": datetime.now(timezone.utc).isoformat(),  # P7: timestamp for chronological ordering
            "run": name,
            "terminal": terminal or "RUN",
            "intent": intent,
            "n_criteria": n_criteria,
            "n_trusted": n_trusted,
            "rebuilds": rebuilds,
            "reason": (reason or "")[:200],
            # The 'lesson' field: DESIGN content (factual observations, refuted
            # theses, confirmed approaches). NOT a status line. Back-compat:
            # still a string for readers that do l.get("lesson").
            "lesson": lesson_line,
            # --- Rich journaling fields (user ask 2026-07-05) ---
            "learnings_text": learnings_text[:2000] if learnings_text else "",
            "references": references_text[:1000] if references_text else "",
            "failure_conditions": failure_conditions,
        }
        learnings_path = os.path.join(_WRITE_SAFE, "devloop-traces", "LEARNINGS.jsonl")
        _state.append_learning(learnings_path, lesson)
        # N2: return the extracted rich fields so _run can pass them to devloop_result
        # without re-extracting from the commit message.
        return {
            "learnings_text": learnings_text[:2000] if learnings_text else "",
            "references": references_text[:1000] if references_text else "",
            "failure_conditions": failure_conditions,
        }
    except Exception as e:
        # Quality review 2026-07-05: log when we silently return empty fields so
        # the direct-runner re-synthesis in project.py is traceable (otherwise an
        # exception here is invisible — project.py sees empty rich fields and
        # re-synthesizes, potentially producing different content).
        import logging as _logging
        _logging.getLogger("devloop_bridge").warning(
            "_append_run_learning failed (%s), returning empty rich fields — "
            "project.py will re-synthesize from the run result", type(e).__name__)
    return {"learnings_text": "", "references": "", "failure_conditions": []}


def _run(request: str, name: str, *, run_task=None, repo=None, keep_branch: bool = False,
         keep_worktree: bool = False) -> dict:
    """Drive ONE devloop run_task and translate its result into pipeline.py's dispatch_result shape.
    run_task is injectable so this is testable without an LLM.

    Lifecycle (deep review 2026-07-01): the run's work is COMMITTED onto devloop/<name> and the
    checkout removed (worktree.finalize — branch kept iff it has content); the trace is copied to
    a durable path first. HUMAN_REVIEW surfaces as a needs-your-input outcome (error=None,
    needs_human=True, blocking questions in the content), NOT as an error — only NO_TERMINATION /
    a missing terminal is an error."""
    if run_task is None:
        if _THIS_DIR not in sys.path:
            sys.path.insert(0, _THIS_DIR)
        from runner import run_task as _rt   # lazy: importing devloop pulls dispatch (needs HERMES_BIN)
        run_task = _rt
    if repo is SCRATCH or repo is None:
        repo = _scratch_repo(name)     # the default: fresh scratch workspace, NEVER the caller's cwd
    # else: an explicit, caller-validated git repo path (modify task)
    # Checkouts live IN-REPO at <repo>/.worktrees (user decision 2026-07-02) — self-contained per
    # repo and guaranteed ignored (worktree.create_worktree writes exclude + seeds .gitignore).
    root = os.path.join(repo, ".worktrees")
    pre_status = _repo_status(repo)      # boundary-guard baseline (see _restore_boundary_breach)
    t0 = time.time()
    res = run_task(repo, request, root, name, keep_worktree=keep_worktree)
    elapsed = time.time() - t0
    result = res.get("result") or {}
    wt = res.get("worktree") or {}
    charter = res.get("charter") or {}
    terminal = result.get("terminal")
    reason = result.get("reason", "") or ""
    blocking = [q.get("text", "") for q in charter.get("open_questions", [])
                if isinstance(q, dict) and q.get("blocking") and q.get("text")]
    trace_path = _preserve_trace(result.get("trace_path"), name)   # BEFORE the checkout is removed
    # Build a rich commit message using the LLM, fed by trace + learnings + git log:
    # every devloop commit includes INTENTION/THESIS/LEARNINGS/REFERENCES with exact git positions.
    # Built BEFORE journaling so the structured LEARNINGS/REFERENCES/failure-conditions can be
    # extracted from it and journaled alongside the mechanical status line (user ask 2026-07-05).
    commit_msg = _build_rich_commit_message(name, request, result, charter, terminal, reason, trace_path)
    # Append this run's learning to the accumulated journal (user ask 2026-07-05):
    # the rich commit message's LEARNINGS/REFERENCES/failure-conditions are extracted and journaled
    # as structured fields, so future runs (and the git history consolidator) carry them forward.
    # Latest entry wins on contradiction (enforced by the consolidator's 'latest wins' rule).
    # N2: capture the rich fields extracted by _append_run_learning so they can
    # be passed directly in devloop_result — no re-extraction in project.py.
    _rich = _append_run_learning(name, request, result, terminal, reason, commit_msg=commit_msg)
    if keep_worktree and wt.get("path"):
        # keep_worktree (advisor review 2026-07-09): skip finalize entirely, leaving the
        # worktree directory + run_dir artifacts (trace, judge_verdicts, progress, etc.)
        # in place for inspection. Useful for debugging and the diagnostic sprint.
        fin = {"changed": [], "committed": False, "branch_kept": True, "worktree_removed": False}
    else:
        try:
            fin = _worktree_mod().finalize(wt, commit_msg) if wt.get("path") \
                else {"changed": [], "committed": False, "branch_kept": False, "worktree_removed": False}
        except Exception:   # noqa: BLE001 — cleanup is best-effort, never a failure path
            fin = {"changed": [], "committed": False, "branch_kept": False, "worktree_removed": False}
    fin["branch"] = wt.get("branch")
    fin["repo_path"] = wt.get("repo")
    needs_human = terminal == "HUMAN_REVIEW"
    # AUTO-MERGE on COMPLETE (user decision 2026-07-01): every gate passed, so the work merges
    # into the target's current branch. Fail-SAFE: any merge failure (dirty tree / conflict /
    # detached HEAD / crash) degrades to the branch-for-review behavior — never worse.
    merged = {"merged": False, "synced": False, "resolved": False, "fixed": False,
              "reason": "", "target": None}
    # --keep-branch (user decision 2026-07-03): a COMPLETE run's verified branch stays unmerged
    # for a PR-style workflow — the CLI exit-0 contract then keys on kept_branch, not merged.
    # fin["committed"] is False when `changed` was empty (finalize never attempted a commit) — but
    # an empty-changed run ALSO gets branch_kept=False via finalize's head==base check, so requiring
    # `committed` alongside `branch_kept` here only excludes the real hazard (a FAILED commit that
    # left branch_kept True with nothing landed), never a legitimately-empty run.
    kept_branch = bool(keep_branch and terminal == "COMPLETE" and fin.get("branch_kept")
                       and fin.get("committed"))
    if (terminal == "COMPLETE" and fin.get("branch_kept") and fin.get("committed")
            and not keep_branch):
        try:
            # base + regression_check arm the PRE-MERGE SYNC (user decision 2026-07-02): a target
            # that advanced past the run's fork point is re-verified as a COMBINED tree first.
            # resolver/fixer let the CODER LLM resolve conflicts / fix a red combined tree —
            # guarded in worktree.py; the regression gate stays the decider.
            merged = _worktree_mod().merge_branch(wt.get("repo"), fin["branch"],
                                                  base=wt.get("base"),
                                                  regression_check=_regression_check,
                                                  resolver=_conflict_resolver,
                                                  fixer=_merge_fixer,
                                                  expected_branch=wt.get("start_branch"),
                                                  commit_message=commit_msg)
        except Exception as e:   # noqa: BLE001 — a merge crash degrades to branch-for-review
            merged = {"merged": False, "synced": False, "resolved": False, "fixed": False,
                      "reason": f"merge error: {type(e).__name__}: {e}", "target": None}
    if terminal == "COMPLETE" and fin.get("branch_kept") and not fin.get("committed"):
        merged["reason"] = ("finalize commit failed — work exists only in the kept checkout; "
                            "nothing landed on the branch")
    grounding = result.get("grounding")
    # boundary guard runs AFTER the merge: a successful merge leaves the tree clean, so
    # anything newly dirty here is agent escape debris, never legitimate run output
    boundary_restored, boundary_failed = _restore_boundary_breach(repo, pre_status)
    try:
        if _THIS_DIR not in sys.path:
            sys.path.insert(0, _THIS_DIR)
        import state  # noqa: E402
        from datetime import datetime, timezone
        events = list(fin.get("events", []))
        events.extend(merged.get("events", []))
        events.extend(state.ev("boundary", "restore", "info", detail=p)
                      for p in boundary_restored)
        events.extend(state.ev("boundary", "restore", "warn", detail=p)
                      for p in boundary_failed)
        dest_dir = os.path.join(_WRITE_SAFE, "devloop-traces", name)
        os.makedirs(dest_dir, exist_ok=True)
        events_path = os.path.join(dest_dir, "events.jsonl")
        for seq, event in enumerate(events):
            entry = dict(event)
            entry["ts"] = datetime.now(timezone.utc).isoformat()
            entry["seq"] = seq
            entry["run"] = name
            state.append_learning(events_path, entry)
            if (event.get("level") in ("warn", "error")
                    and os.environ.get("DEVLOOP_DEBUG") == "1"):
                print(f"[devloop:{name}] {event['level'].upper()} "
                      f"{event['phase']}/{event['step']}: {event.get('detail', '')}",
                      file=sys.stderr)
    except Exception:  # noqa: BLE001 — diagnostics must never alter the run result
        pass
    content = _summary(terminal, fin, reason, blocking, trace_path, merged, grounding,
                       kept=kept_branch, scope_dropped=result.get("scope_dropped"))
    if merged.get("leaked_branch"):
        content += f"\n⚠ merged but branch deletion failed: {merged['leaked_branch']}"
    if boundary_restored:
        content += ("\n⚠ worktree-boundary breach: an agent phase touched the target repo's "
                    f"main working tree — restored {len(boundary_restored)} path(s): "
                    + ", ".join(boundary_restored[:6]))
    if boundary_failed:
        content += ("\n⚠ boundary restore FAILED for "
                    f"{len(boundary_failed)} path(s) — inspect manually: "
                    + ", ".join(boundary_failed[:6]))
    return {
        "content": content,
        "session_id": None,
        "elapsed": elapsed,
        # COMPLETE = success; HUMAN_REVIEW = a needs-input outcome (NOT an error);
        # NO_TERMINATION / missing terminal = a real failure.
        "error": None if terminal in ("COMPLETE", "HUMAN_REVIEW")
                 else (reason or terminal or "devloop did not complete"),
        "devloop_result": {"terminal": terminal,
                           # branch reports what STILL EXISTS: None after a successful merge
                           # (the squash commit is the artifact) or when no artifact was produced.
                           "branch": (merged.get("leaked_branch") if merged["merged"] else
                                      (fin["branch"] if fin.get("branch_kept") else None)),
                           "worktree": None if fin.get("worktree_removed") else wt.get("path"),
                           "repo": wt.get("repo"), "changed_files": fin.get("changed", []),
                           "merged": merged["merged"], "kept_branch": kept_branch,
                           "merge_reason": merged["reason"],
                           "synced": merged.get("synced", False),
                           "sync_resolved": merged.get("resolved", False),
                           "sync_fixed": merged.get("fixed", False),
                           "code_path": wt.get("repo") if merged["merged"] else None,
                           "reason": reason, "trace_path": trace_path,
                           "grounding": grounding,
                           "scope_dropped": result.get("scope_dropped", []),
                           "needs_human": needs_human, "open_questions": blocking,
                           # scout.py's pipeline step adapter feeds these two to
                           # project.classify_outcome (escalate-vs-reattempt fidelity)
                           "retryable": result.get("retryable"), "charter": charter,
                           "boundary_restored": boundary_restored,
                           "boundary_restore_failed": boundary_failed,
                           # P0-1: expose the rich commit message so the project outer loop
                           # can extract LEARNINGS/REFERENCES/failure_conditions from it
                           # (advisor review 2026-07-05)
                           "commit_message": commit_msg,
                           # N2: expose the extracted rich fields directly so project.py
                           # doesn't need to re-extract from commit_message (eliminates
                           # triple-extraction risk).
                           "learnings_text": _rich.get("learnings_text", ""),
                           "references": _rich.get("references", ""),
                           "failure_conditions": _rich.get("failure_conditions", [])},
        "pipeline_mode": "devloop",
    }


def failure_result(reason: str) -> dict:
    """A FAIL-CLOSED dispatch_result: same shape as _run's return, terminal HUMAN_REVIEW, error set.
    Used when devloop itself errors — a build/debug request must surface the failure, never be
    silently downgraded to an unverified single-shot labeled success."""
    return {
        "content": f"devloop FAILED CLOSED — {reason}",
        "session_id": None,
        "elapsed": 0.0,
        "error": reason,
        "devloop_result": {"terminal": "HUMAN_REVIEW", "branch": None, "worktree": None,
                           "repo": None, "changed_files": [], "merged": False,
                           "kept_branch": False,
                           "synced": False, "sync_resolved": False, "sync_fixed": False,
                           "merge_reason": "", "code_path": None, "reason": reason,
                           "trace_path": None, "grounding": None, "scope_dropped": [],
                           # deliberately False: an engine CRASH is a failure (CLI exit 1),
                           # not a needs-your-input outcome (exit 2) — same keys as _run's
                           # shape so consumers never see two HUMAN_REVIEW dialects.
                           "needs_human": False, "open_questions": [],
                           # retryable False + empty charter: an engine crash escalates in
                           # project.classify_outcome instead of burning re-attempt budget
                           "retryable": False, "charter": {}, "boundary_restored": [],
                           "boundary_restore_failed": [],
                           # P0-1: commit_message in failure shape too (empty — no
                           # commit was made on a crash). Matches _run's shape.
                           "commit_message": "",
                           # N2: mirror rich fields in failure shape (empty — no
                           # extraction happened on a crash). Matches _run's shape.
                           "learnings_text": "",
                           "references": "",
                           "failure_conditions": []},
        "pipeline_mode": "devloop",
    }


def call_guarded(fn, *args, **kwargs) -> dict:
    """Run a bridge entrypoint with a fail-closed guard: ANY devloop runtime exception (missing
    HERMES_BIN, model-collision assert, a kernel bug) becomes a failure_result instead of an
    uncaught crash in pipeline.py. Fail-closed by construction — the fallback terminal is
    HUMAN_REVIEW with error set, so a broken engine can never read as success."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 — any devloop failure must fail closed, not propagate
        return failure_result(f"devloop runtime error: {type(e).__name__}: {e}")


def _name(kind: str) -> str:
    # unique per call (pid + ns) so the per-run worktree branch devloop/<name> never collides
    return f"{kind}-{os.getpid()}-{time.time_ns()}"


def _honor_timeout(timeout) -> None:
    """RAISE-only: a caller timeout above the per-model-call floor lifts the dispatch ceiling via
    DEVLOOP_DISPATCH_TIMEOUT_S (dispatch._dispatch_timeout floor-clamps, so a small caller value —
    e.g. pipeline's 300s default — can NEVER lower it; project policy: never shorten timeouts).
    This is a per-model-call ceiling, not a whole-run wall clock (back-off caps bound the run)."""
    try:
        t = int(timeout or 0)
    except (TypeError, ValueError):
        return
    if t > 1800:
        os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] = str(t)


def run_build(message: str, timeout=None, repo=SCRATCH, keep_branch: bool = False,
              keep_worktree: bool = False) -> dict:
    """build_code -> devloop. The DoD is derived from `message` by devloop's own CHARTER phase.
    `repo`: SCRATCH (the default) -> fresh scratch workspace; a caller-validated path -> modify
    that repo; None -> fail-safe alias for SCRATCH (never an implicit cwd).
    `keep_branch`: leave a COMPLETE run's verified branch unmerged (PR-style workflows).
    `keep_worktree`: skip worktree cleanup entirely, leaving the worktree + run_dir artifacts
    (trace, judge_verdicts, progress, etc.) in place for inspection (debugging/diagnostics)."""
    _honor_timeout(timeout)
    return _run(message, _name("build"), repo=repo, keep_branch=keep_branch,
                keep_worktree=keep_worktree)


def run_debug(message: str, code=None, error_feedback=None, timeout=None, repo=SCRATCH,
              keep_branch: bool = False, keep_worktree: bool = False) -> dict:
    """debug_cascade -> devloop. Fold the failing code + error into the request so the CHARTER phase
    has the full repair context (devloop has no separate debug entrypoint — it is one build loop)."""
    _honor_timeout(timeout)
    request = message
    if code:
        request += "\n\nCURRENT CODE:\n" + str(code)[:4000]
    if error_feedback:
        request += "\n\nERROR / FAILURE:\n" + str(error_feedback)[:2000]
    return _run(request, _name("debug"), repo=repo, keep_branch=keep_branch,
                keep_worktree=keep_worktree)
