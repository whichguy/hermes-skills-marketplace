"""scout.py — the SCOUT -> BUILD pipeline: relentless-solve finds the happy path (cheap,
read-only, information-producing), devloop builds each returned step (expensive, verified,
change-producing).

Architecture verdict this module encodes (user decision 2026-07-03): devloop must NOT call
relentless-solve as an inner component — relentless is the skill family's ORCHESTRATE role
(acyclic, orchestrator-at-top; its task verdicts are self-reported), while devloop's
0-false-completes invariant rests on code-owned control flow. The composition exploits the
cost asymmetry instead: relentless's cost scales with UNCERTAINTY (a scout's mistake costs
one wasted build attempt), devloop's cost is fixed RIGOR per step (a builder's mistake is
merged wrong code). Scout first, build second, verify always.

The seam is the family's blessed kind — a CLI subprocess plus an artifact on disk, no
imports in either direction. The scout's own plan.json tasks are its INVESTIGATION moves,
not the build steps; the build steps are its FINDINGS, demanded as a deliverable artifact
(scout-steps.json) whose schema THIS module validates fail-closed.

Steps drive project.run_project through a bridge-backed step runner (finalize + auto-merge
+ trace preservation — project.py's raw runner path leaves branches uncommitted/unmerged),
so ordered steps compose: each step's merge lands before the next step's worktree is cut.

Correctness properties this module OWNS (mutant-pinned):
  * A build happens ONLY on a scout that CONCLUDED (outcome "success" + a valid artifact);
    no_path / unconcluded / failed scouts never enqueue devloop work.
  * The artifact schema is validated fail-closed — ANY violation reads as scout failure.
  * A step counts achieved ONLY if its devloop run COMPLETEd AND the merge landed
    (an unmerged COMPLETE is downgraded so the drain re-attempts instead of building the
    next step on code that never arrived).
  * The slug hashes the request AND the repo's realpath — a leftover artifact in a reused
    state dir can only ever belong to the SAME request against the SAME repo (relentless's
    resume feature stays intact; use fresh=True / --fresh to force a clean re-scout).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

SCHEMA_VERSION = 1
MAX_STEPS = 24                 # a runaway artifact must not enqueue an unbounded build
DEFAULT_WALLCLOCK_S = 1800     # scout budget — RAISE via --wallclock, never lowered here
DEFAULT_MAX_CYCLES = 3
SUBPROCESS_PAD_S = 120         # backstop over relentless's own --wallclock (the oneshot.py
                               # lesson: the child's bound is primary, ours only catches hangs)

_TERMINAL_OUTCOMES = ("success", "information-dry", "max-cycles", "wallclock")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _hermes_home() -> str:
    return os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))


def _project_mod():
    # lazy: importing project pulls runner -> dispatch (needs the Hermes runtime)
    import project
    return project


def _bridge_mod():
    import devloop_bridge
    return devloop_bridge


def _worktree_mod():
    import worktree
    return worktree


def scout_slug(request: str, repo: str) -> str:
    """Deterministic (same request AGAINST THE SAME REPO -> same relentless state dir, so
    re-invocations RESUME) and collision-resistant (16-hex sha256 prefix): the hash covers
    BOTH the request and the repo's realpath — a truncated kebab prefix shared by two
    different requests is separated by the hash, and the SAME request against a DIFFERENT
    repo gets fresh state (a reused drain PLAN from repo A would otherwise 'complete'
    instantly against repo B)."""
    kebab = _SLUG_RE.sub("-", request.lower()).strip("-")[:32].strip("-") or "task"
    fp = hashlib.sha256(f"{os.path.realpath(repo)}\0{request}".encode("utf-8")).hexdigest()[:16]
    return f"scout-{kebab}-{fp}"


def _relentless_script() -> tuple[str | None, list[str]]:
    """(path, candidates-tried) — resolution ladder mirroring relentless's own lazy-loader
    convention: env override -> deployed skills tree -> the hermes-agent mirror."""
    home = _hermes_home()
    cands = []
    env = os.environ.get("DEVLOOP_RELENTLESS_SCRIPT")
    if env:
        cands.append(env)
    cands.append(os.path.join(home, "skills", "relentless-solve", "scripts", "relentless.py"))
    cands.append(os.path.join(home, "hermes-agent", "skills", "autonomous-ai-agents",
                              "relentless-solve", "scripts", "relentless.py"))
    for c in cands:
        if os.path.isfile(c):
            return c, cands
    return None, cands


def scout_intent(request: str, repo: str, steps_path: str) -> str:
    """The scout convention prompt: read-only discipline + the demanded deliverable artifact
    (schema echoed verbatim so the executor cannot guess a shape load_steps would reject)."""
    return (
        f"Determine the happy path for the following goal in the git repository at {repo}.\n"
        f"GOAL: {request}\n"
        "Investigate READ-ONLY: do NOT implement, modify, commit, or write anything inside "
        "the repository — your deliverable is a step list, not code. If you must try "
        "something out to verify feasibility, work on a COPY outside the repository (e.g. "
        "under /tmp); any modification to the repository itself will be detected and "
        "discarded.\n"
        f"DELIVERABLE: write EXACTLY one JSON object to {steps_path} :\n"
        '{"schema_version": 1, "steps": [{"purpose": "<ONE buildable change, plain English, '
        'naming the files/behaviors involved>", "success_criterion": "<strict, objectively '
        'checkable definition of done for that step>"}, ...]}\n'
        "If scouting PROVES there is no viable path, write instead: "
        '{"schema_version": 1, "steps": [], "no_path": "<why no viable path exists>"}\n'
        "Steps must be ordered (each may assume the previous steps landed), and each must be "
        "sized like one small self-contained development task. Keep the list minimal — the "
        "happy path, not every conceivable improvement.\n"
        "Steps must be FUNCTIONAL/PRODUCT changes only — never a step whose deliverable is "
        "itself a test (the builder that executes these steps designs, runs, and gates on "
        "its own tests for every step; a 'write a test' step is redundant and unbuildable "
        "there). Fold any verification detail into the step's success_criterion instead."
    )


def _invoke(cmd: list, timeout: int):
    """subprocess.run, but a TimeoutExpired becomes a returncode=124 CompletedProcess with the
    partial output (the oneshot.py lesson — the child may have advanced durable state on disk
    before the kill, and relentless runs are journal-resumable, so never raise)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out, err = e.stdout, e.stderr
        stdout = out.decode(errors="replace") if isinstance(out, bytes) else (out or "")
        stderr = err.decode(errors="replace") if isinstance(err, bytes) else (err or "")
        return subprocess.CompletedProcess(cmd, 124, stdout, stderr)


def _parse_outcome(stdout: str):
    """result.outcome from relentless's final stdout JSON — scanned tolerant (last JSON object
    carrying a result.outcome wins; engine chatter above it is ignored)."""
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip().startswith("{")]
    for chunk in reversed(lines + [stdout or ""]):
        try:
            obj = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            r = obj.get("result")
            if isinstance(r, dict) and "outcome" in r:
                return r.get("outcome")
    return None


def load_steps(steps_path: str):
    """Fail-closed artifact read: {'steps': [...], 'no_path': str|None} or None on ANY
    violation — a malformed finding must read as scout failure, never as a build queue."""
    try:
        with open(steps_path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    sv = d.get("schema_version")
    if type(sv) is not int or sv != SCHEMA_VERSION:
        return None
    steps = d.get("steps")
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        return None
    for s in steps:
        if not isinstance(s, dict):
            return None
        if not (isinstance(s.get("purpose"), str) and s["purpose"].strip()):
            return None
        if not (isinstance(s.get("success_criterion"), str) and s["success_criterion"].strip()):
            return None
    no_path = d.get("no_path")
    if no_path is not None and not (isinstance(no_path, str) and no_path.strip()):
        return None
    try:
        for s in steps:
            s["purpose"].encode("utf-8")
            s["success_criterion"].encode("utf-8")
        if isinstance(no_path, str):
            no_path.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if steps and no_path:
        return None          # contradictory finding — refuse rather than pick a side
    if not steps and not no_path:
        return None          # an empty step list is only meaningful WITH a no_path reason
    return {"steps": [{"purpose": s["purpose"].strip(),
                       "success_criterion": s["success_criterion"].strip()} for s in steps],
            "no_path": no_path.strip() if isinstance(no_path, str) else None}


def run_scout(request: str, repo: str, *, slug=None, fresh: bool = False,
              wallclock: int = DEFAULT_WALLCLOCK_S, max_cycles: int = DEFAULT_MAX_CYCLES,
              plan_timeout=None, task_timeout=None, invoke=None) -> dict:
    """One relentless-solve scout run (read capability, journal-resumable) -> a gated finding.

    Returns {ok, outcome, steps, no_path, unconcluded, reason, slug, state_dir, steps_path}.
    ok=True means the scout produced a USABLE finding: verified steps (outcome success),
    an honest no_path, or — flagged unconcluded=True — steps a capped/dry run left for
    human review (surfaced, never built). Everything else is fail-closed ok=False."""
    slug = slug or scout_slug(request, repo)
    state_dir = os.path.join(_hermes_home(), "relentless", slug)
    steps_path = os.path.join(state_dir, "scout-steps.json")
    base = {"ok": False, "slug": slug, "state_dir": state_dir, "steps_path": steps_path,
            "outcome": None, "steps": [], "no_path": None, "unconcluded": False, "reason": ""}
    if fresh:
        # explicit opt-out of relentless's resume: clear the slug's whole state dir so the
        # scout re-derives everything (the artifact alone must NOT be deleted — a resumed
        # run replays memoized steps without re-executing the agent that wrote it).
        shutil.rmtree(state_dir, ignore_errors=True)
        if os.path.exists(state_dir):
            return {**base, "reason": f"--fresh could not clear prior scout state at "
                                      f"{state_dir} — refusing to silently resume"}
    script, tried = _relentless_script()
    if script is None:
        return {**base, "reason": "scout unavailable — relentless-solve not found "
                                  "(tried: " + ", ".join(tried) + ")"}
    cmd = [sys.executable, script, "run", "--slug", slug, "--answer-cwd", repo,
           "--prompt", scout_intent(request, repo, steps_path),
           "--capability", "read", "--max-cycles", str(max_cycles),
           "--wallclock", str(wallclock)]
    if plan_timeout:
        cmd += ["--plan-timeout", str(plan_timeout)]
    if task_timeout:
        cmd += ["--task-timeout", str(task_timeout)]
    r = (invoke or _invoke)(cmd, wallclock + SUBPROCESS_PAD_S)
    outcome = _parse_outcome(r.stdout)
    if r.returncode != 0 or outcome not in _TERMINAL_OUTCOMES:
        why = (f"scout subprocess timed out (rc 124) — the run is journal-resumable: "
               f"re-run the same pipeline (slug {slug}) to continue where it stopped"
               if r.returncode == 124 else
               f"scout failed (rc {r.returncode}, outcome {outcome!r}): "
               + (r.stderr or r.stdout or "")[-300:].strip())
        return {**base, "outcome": outcome, "reason": why}
    doc = load_steps(steps_path)
    if doc is None:
        return {**base, "outcome": outcome,
                "reason": f"scout run ended ({outcome}) but produced no valid "
                          f"scout-steps.json at {steps_path}"}
    if doc["no_path"] and outcome in ("success", "information-dry"):
        # an honest, concluded "there is no viable path" — a valid scout answer, not an error
        return {**base, "ok": True, "outcome": outcome, "no_path": doc["no_path"]}
    if outcome == "success" and doc["no_path"] is None:
        return {**base, "ok": True, "outcome": outcome, "steps": doc["steps"]}
    # capped/dry run that still left a finding: surface it for review, NEVER build on it
    return {**base, "ok": True, "outcome": outcome, "steps": doc["steps"],
            "no_path": doc["no_path"], "unconcluded": True,
            "reason": f"scout did not conclude ({outcome}) — finding is for review, not built"}


def _git_status(repo: str):
    """Porcelain status lines, or None when `repo` isn't a git repo (the CLI always hands the
    pipeline a validated git repo; programmatic callers own their own validation)."""
    try:
        r = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                           capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _scrub_scout_debris(repo: str):
    """Hard-restore scout-introduced changes. Only ever called when the repo was CLEAN before
    the scout (the precondition), so everything dirty is scout debris. Returns the restored
    paths ([] when already clean), or None if the restore itself failed — the caller must
    then fail closed (repo state unknown)."""
    dirty = _git_status(repo)
    if dirty is None:
        return None
    if not dirty:
        return []
    r1 = subprocess.run(["git", "-C", repo, "reset", "--hard", "-q"],
                        capture_output=True, text=True)
    r2 = subprocess.run(["git", "-C", repo, "clean", "-fdq"],
                        capture_output=True, text=True)
    post = _git_status(repo)
    if r1.returncode != 0 or r2.returncode != 0 or post is None or post:
        return None
    return [ln.split(None, 1)[-1] for ln in dirty]


def steps_to_purposes(steps: list) -> list:
    """Each step's success criterion rides INTO the purpose text so devloop's charter sees a
    checkable definition of done (and its vague-goal gate honestly bounces a fuzzy step)."""
    return [f"{s['purpose']}\n\nSuccess criterion: {s['success_criterion']}" for s in steps]


def bridge_step_run_task(repo, request, root, name):
    """project.run_project-compatible step runner with the BRIDGE's full lifecycle (finalize +
    auto-merge + trace preservation) — the raw runner path leaves the branch uncommitted and
    unmerged, and pipeline steps MUST land before the next step's worktree is cut.

    A COMPLETE whose auto-merge degraded to branch-for-review is downgraded to
    MERGE_DEGRADED: 'achieved' must mean the code actually ARRIVED in the repo — the outer
    drain then re-attempts (a transient dirty tree may clear) or blocks honestly."""
    br = _bridge_mod()
    out = br.call_guarded(br._run, request, name, repo=repo)
    dr = out.get("devloop_result") or {}
    terminal = dr.get("terminal")
    if terminal == "COMPLETE" and not dr.get("merged"):
        terminal = "MERGE_DEGRADED"
    reason = dr.get("reason", "") or dr.get("merge_reason", "") or ""
    if terminal == "MERGE_DEGRADED" and dr.get("merge_reason"):
        reason = f"merge degraded: {dr['merge_reason']}"
    return {"result": {"terminal": terminal, "reason": reason,
                       "retryable": dr.get("retryable")},
            "charter": dr.get("charter") or {},
            "worktree": {},        # checkout already finalized/removed by the bridge
            "content": out.get("content"), "devloop_result": dr}


def _why_not_built(sc: dict, scout_only: bool) -> str:
    if not sc["ok"]:
        return "scout failed — nothing to build"
    if scout_only:
        return "scout-only run — build skipped by request"
    if sc["unconcluded"]:
        return "scout did not conclude — review the finding, then re-run (resumes) or --fresh"
    if sc["no_path"]:
        return "scout concluded there is no viable path"
    return "no steps"


def render_report(res: dict) -> str:
    sc = res["scout"]
    out = [f"# Pipeline report — {res['request'][:120]}", "",
           f"## Scout — outcome: {sc.get('outcome') or '—'} (state: {sc['state_dir']})"]
    if not sc["ok"]:
        out.append(f"- ✗ SCOUT FAILED: {sc.get('reason') or '(no reason)'}")
    elif sc["no_path"] and not sc["unconcluded"]:
        out.append(f"- ✗ NO VIABLE PATH: {sc['no_path']}")
    else:
        if sc.get("scrubbed"):
            out.append(f"- ⚠ read-only discipline breach: the scout modified "
                       f"{len(sc['scrubbed'])} path(s) in the repo — RESTORED clean "
                       f"({', '.join(sc['scrubbed'][:6])})")
        if sc["unconcluded"]:
            out.append(f"- ⚠ UNCONCLUDED: {sc.get('reason')}")
        for i, s in enumerate(sc["steps"], 1):
            out.append(f"- {i}. {s['purpose']}  [done when: {s['success_criterion']}]")
        if sc["no_path"]:
            out.append(f"- (run also recorded a no-path note: {sc['no_path']})")
    out += ["", "## Build"]
    if res["built"]:
        out.append((res["project"] or {}).get("report") or "(no project report)")
    else:
        out.append(f"- not built: {_why_not_built(sc, res.get('scout_only', False))}")
    return "\n".join(out)


def _bundle(root: str, slug: str, sc: dict, report: str):
    """Inspection bundle (same discipline as devloop-traces): the finding + the combined
    report, post-hoc diagnosable without digging into $HERMES_HOME/relentless/. Best-effort —
    a bundle write failure must never sink a pipeline whose work already landed."""
    d = os.path.join(root, "devloop-traces", f"pipeline-{slug}")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "report.md"), "w", encoding="utf-8") as f:
            f.write(report)
        if os.path.exists(sc["steps_path"]):
            shutil.copy2(sc["steps_path"], os.path.join(d, "scout-steps.json"))
    except (OSError, UnicodeEncodeError):
        return None
    return d


def run_pipeline(repo: str, request: str, *, root=None, scout_only: bool = False,
                 fresh: bool = False, wallclock: int = DEFAULT_WALLCLOCK_S,
                 max_cycles: int = DEFAULT_MAX_CYCLES, plan_timeout=None, task_timeout=None,
                 invoke=None, run_project=None, step_run_task=None) -> dict:
    """SCOUT -> gate -> BUILD -> combined report. `repo` is a caller-validated git repo (the
    CLI validates); `root` is the write-safe root for the pipeline's own durable state
    (drain PLAN/LESSONS under devloop-pipelines/<slug>/, bundle under devloop-traces/)."""
    root = root or _bridge_mod()._WRITE_SAFE
    slug = scout_slug(request, repo)
    state_dir = os.path.join(_hermes_home(), "relentless", slug)
    pdir = os.path.join(root, "devloop-pipelines", slug)
    if fresh:
        # fresh = start the WHOLE pipeline over: run_scout clears the relentless state; the
        # drain state must go too — a PLAN.json full of blocked items from a prior
        # (e.g. environmental) failure would otherwise resume as an instant no-op re-report
        shutil.rmtree(pdir, ignore_errors=True)
        if os.path.exists(pdir):
            sc = {"ok": False, "slug": slug, "state_dir": state_dir,
                  "steps_path": os.path.join(state_dir, "scout-steps.json"),
                  "outcome": None, "steps": [], "no_path": None, "unconcluded": False,
                  "reason": f"--fresh could not clear prior pipeline state at {pdir} "
                            "— refusing to silently resume"}
        else:
            sc = None
    else:
        sc = None
    # READ-ONLY DISCIPLINE IS A CODE GATE, not a prompt promise (live-caught 2026-07-03: a
    # scout task executor trial-implemented the feature in the target repo and deleted a
    # test file while "verifying feasibility"). Precondition: a clean repo — which is also
    # what makes the post-scout scrub safe (everything dirty afterwards is scout debris).
    if sc is None:
        pre = _git_status(repo)
        if pre is None:
            sc = {"ok": False, "slug": slug, "state_dir": state_dir,
                  "steps_path": os.path.join(state_dir, "scout-steps.json"),
                  "outcome": None, "steps": [], "no_path": None,
                  "unconcluded": False,
                  "reason": "cannot read the target repo's git status — fail closed "
                            "(pipeline needs a verifiable clean baseline)"}
        elif pre:
            sc = {"ok": False, "slug": slug, "state_dir": state_dir,
                  "steps_path": os.path.join(state_dir, "scout-steps.json"),
                  "outcome": None, "steps": [], "no_path": None,
                  "unconcluded": False,
                  "reason": "target repo has uncommitted changes ("
                            + ", ".join(ln.split(None, 1)[-1] for ln in pre[:6])
                            + (", …" if len(pre) > 6 else "")
                            + ") — commit or stash first: the pipeline merges "
                              "verified steps into this repo, and scout-debris "
                              "restoration needs a clean baseline"}
    if sc is None:
        sc = run_scout(request, repo, slug=slug, fresh=fresh, wallclock=wallclock,
                       max_cycles=max_cycles, plan_timeout=plan_timeout,
                       task_timeout=task_timeout, invoke=invoke)
        scrubbed = _scrub_scout_debris(repo)
        if scrubbed is None:
            sc = {**sc, "ok": False, "steps": [], "no_path": None,
                  "unconcluded": False,
                  "reason": "scout modified the target repo and the restore FAILED "
                            "— repo state unknown, inspect manually. "
                            + (sc.get("reason") or "")}
        elif scrubbed:
            sc = {**sc, "scrubbed": scrubbed}
    res = {"request": request, "slug": slug, "scout": sc, "scout_only": scout_only,
           "built": False, "project": None}
    # bool(steps) alone covers the no_path case too: load_steps enforces steps XOR no_path,
    # so a no-path finding always arrives with an empty step list
    buildable = (sc["ok"] and not scout_only and not sc["unconcluded"]
                 and bool(sc["steps"]))
    if buildable:
        rp = run_project or _project_mod().run_project
        rt = step_run_task or bridge_step_run_task
        res["project"] = rp(repo, os.path.join(repo, ".worktrees"),
                            steps_to_purposes(sc["steps"]), project_dir=pdir, run_task=rt)
        res["built"] = True
    res["report"] = render_report(res)
    res["bundle"] = _bundle(root, slug, sc, res["report"])
    return res
