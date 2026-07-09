"""dispatch.py — real `ask`-backed dispatchers for the v0 loop (v0-real).

    charter_via_ask(request) -> Charter
        `ask planner` (GLM) emits JSON; wrapped into a full, schema-valid Charter.
    implementer_via_ask(target_dir) -> implement(charter, attempt, last_failure)
        `ask coder` (qwen) edits files in target_dir via the file toolset.

Mirrors productivity/ask dispatch (hermes chat -q -Q --yolo). Overridable via env:
HERMES_BIN, DEVLOOP_PLANNER, DEVLOOP_CODER. Must run where HERMES_BIN exists (the container).
The file tools only write under the Hermes write-safe root (HERMES_WRITE_SAFE_ROOT = /opt/data
in the image) — so target_dir MUST live under it.

Token caps / per-call timeouts: sourced from Hermes config at runtime; the `timeout` here is a
generous subprocess safety net, never a model-shortening cap (project policy).
"""
from __future__ import annotations

import json
import os
import re
import time

import config
import subprocess

import render
import testgen
import worktree

HERMES_BIN = os.environ.get("HERMES_BIN", "/opt/hermes/bin/hermes")
PLANNER = os.environ.get("DEVLOOP_PLANNER", "glm-5.2:cloud")
DESIGNER = os.environ.get("DEVLOOP_DESIGNER", "deepseek-v4-pro:cloud")  # writes tests, once per task; != coder
# Two DISTINCT assertion judges, both != coder and != designer (no model grades its own work).
JUDGE_A = os.environ.get("DEVLOOP_JUDGE_A", "glm-5.2:cloud")
JUDGE_B = os.environ.get("DEVLOOP_JUDGE_B", "minimax-m3:cloud")
# TIEBREAKER (advisor review 2026-07-09): a third judge called ONLY when judge_a and judge_b
# disagree on a criterion. Uses a different model from both judges and the coder/designer.
# Default: deepseek-reasoner (the advisor's architect model — strong reasoning, different
# provider from glm and minimax). Override with DEVLOOP_TIEBREAKER env var.
TIEBREAKER = os.environ.get("DEVLOOP_TIEBREAKER", "deepseek-reasoner:cloud")
# CODER runs per IMPLEMENT iteration (the bottleneck) -> a fast cloud model. All four of coder /
# designer / judge_a / judge_b MUST differ (assert_distinct_models) so no model writes both the
# tests and the code, or grades its own work. Roster: kimi (coder), deepseek (designer), glm +
# minimax (judges). The local qwen3-coder-next:devloop (FROM q4_K_M + PARAMETER num_ctx 65536) is
# available as a DEVLOOP_DESIGNER override; the qwen3-coder-next:cloud variant is broken upstream.
CODER = os.environ.get("DEVLOOP_CODER", "kimi-k2.7-code:cloud")
# REFINER reviews+rewrites the planner's DRAFT charter into atomic form (glm drafts inconsistently
# — 1 vs 3 criteria across runs). kimi by user choice; a planning role, NOT in assert_distinct_models
# (it shapes criteria, doesn't grade or write the tests/code that verify them).
REFINER = os.environ.get("DEVLOOP_REFINER", "kimi-k2.7-code:cloud")
# ADVISOR reviews the refined DoD for COMPLETENESS/correctness vs the request (Phase 0) — a fresh
# model independent of the drafter (glm) and refiner (kimi), so it catches gaps they share.
# Defaults to the DESIGNER model (deepseek) on purpose: the advisor only ADDS open_questions (can
# route to human, never cause COMPLETE), so it is NOT in assert_distinct_models — the "fresh" claim
# is relative to the drafter+refiner it reviews, not the later test designer.
ADVISOR = os.environ.get("DEVLOOP_ADVISOR", "deepseek-v4-pro:cloud")

# DIAGNOSER escalates the DEBUG cascade (#35): on a REPEAT code-fault red, a stronger INDEPENDENT
# reasoner diagnoses the root cause so the next coder attempt has real guidance. It produces only
# guidance text (never code/a verdict), so it can equal the designer/advisor model — coding itself
# stays kimi-only (user pref); only the DIAGNOSIS escalates, never the coder identity.
DIAGNOSER = os.environ.get("DEVLOOP_DIAGNOSER", "deepseek-v4-pro:cloud")

# Atomic/EARS-shaped charter prompt (research: references/planning-prompt-research.md). The schema
# is unchanged (_wrap_charter consumes the same 4 keys); only the GUIDANCE changed — it makes
# compound criteria ("X exists AND defines Y AND returns Z") and over-decomposition (add()->4)
# ungrammatical, and calibrates assumption-vs-block so a reasonable default proceeds and only a
# genuine gap (missing target system / required number) blocks. A/B-validated before wiring.
_CHARTER_PROMPT = (
    "You are the CHARTER phase of an autonomous coding loop. Turn the REQUEST into a precise, "
    "testable Definition of Done. Output ONLY a JSON object (no prose, no fence) with these keys:\n"
    '  "interpreted_intent": string — one sentence: what the user actually wants.\n'
    '  "dod": array of {"criterion": string, "verify_intent": string, "tier": "unit"|"integration"}. RULES:\n'
    "    - ONE behavior per criterion: one observable result of one named function/module. Never "
    'join two outcomes with "and"/"or" — split them into separate criteria.\n'
    '    - tier scopes the validation ladder: \"unit\" = an isolated behavior of the NEW logic itself '
    "(small and fast — a failure points at the new code, nothing else); \"integration\" = the new "
    "behavior exercised THROUGH existing code's public surface (real collaborators, proving it fits "
    "the system). Default to unit; use integration when the request wires new code into existing code.\n"
    "    - MANDATORY EXTERNAL-SYSTEM INTEGRATION CRITERIA (CRITICAL — read carefully):\\n"
    "      When the request asks the code to INITIATE an outbound call to a system that exists\\n"
    "      OUTSIDE the repo — a CLI tool (gws, gh, kubectl, aws, docker, git, curl, hermes), a\\n"
    "      REST API (GitHub, Slack, Google Calendar), an agent system (Claude Code, Cursor),\\n"
    "      a database, or a webhook — you MUST include at least ONE integration-tier criterion\\n"
    "      (tier: \"integration\") that exercises the REAL external system, NOT a mock.\\n"
    "      This is NON-NEGOTIABLE. A request that says 'via the gws CLI', 'calls the GitHub API',\\n"
    "      'uses the Hermes agent', 'invokes Claude Code', 'shells out to kubectl', 'sends a webhook',\\n"
    "      'posts to a Slack channel', 'queries the database', or ANY similar outbound integration\\n"
    "      MUST produce at least one integration criterion that shells out to the REAL binary/API.\\n"
    "      NOTE: a request that asks the code to CONSUME or PARSE the OUTPUT of an external call\\n"
    "      (e.g., 'parse the JSON returned by gh pr list') does NOT require integration tier —\\n"
    "      the external boundary is the function's input, not its output. Integration tier is\\n"
    "      required when the code INITIATES the outbound call itself.\\n"
    "      The integration criterion must:\n"
    "        (a) invoke the real external tool via subprocess.run([...]) or a real HTTP call — NOT a\n"
    "            mock, NOT a function call to an internal wrapper, NOT a substring check on a string;\n"
    "        (b) use a safe, read-only, or dry-run invocation when available (--dry-run, --help,\n"
    "            --validate, --no-execute, GET /api/health, etc.) — do NOT invent a flag the tool\n"
    "            doesn't support; if no safe mode exists, test against a real but harmless endpoint;\n"
    "        (c) assert on the REAL output/exit code/HTTP response — e.g. exit code 0, expected JSON\n"
    "            schema, specific response field — NOT a substring 'in' check on a mocked string.\n"
    "      You MAY also include unit-tier criteria for the internal parsing/logic functions (with the\n"
    "      external boundary mocked). But the EXTERNAL integration itself MUST have its own criterion.\n"
    "      A charter with ALL unit-tier criteria for a request that names an external system is\n"
    "      DEFECTIVE and will be rejected. This is the #1 source of false-COMPLETE runs — tests that\n"
    "      mock the external system pass even when the real command/API syntax is completely wrong.\n"
    "    - Atomic, NOT fragmented: a single function with one job is ONE criterion (add(a,b) "
    "returning the sum is ONE criterion, checked with several example inputs — not one per "
    "example). Describe the observable RESULT, not internal steps. Aim for the FEWEST criteria that "
    "fully capture the behavior — roughly ONE per public function/behavior the request names; a "
    "two-function module is about 2 criteria, not 7. Fold a function's edge cases into ITS "
    "criterion's verify_intent (more examples), never a separate criterion.\n"
    '    - verify_intent is ONE concrete assertion (e.g. "add(2,3)==5; add(-1,1)==0"), 1:1 with a '
    "single test. No checklists.\n"
    "    - Measurable = a test can decide pass/fail. NEVER invent a number (latency, %, size) the "
    "REQUEST did not give. A VAGUE QUALITY GOAL with no concrete target — 'make it faster / better / "
    "cleaner / more robust', 'optimize X', 'improve performance' — is UNMEASURABLE: you may NOT "
    "manufacture a benchmark, baseline, threshold, or self-referential 'reports a lower value' "
    "criterion for it. Emit a BLOCKING open_question ('no measurable success criterion for: <goal>') "
    "and do NOT add assumptions (at any confidence) to slip past it. This is a blocking GAP, not a "
    "defaultable detail.\n"
    "    - OBSERVABLE BEHAVIOR only, NOT implementation structure: a criterion describes what the "
    "code DOES from the outside (a return value, a raised error, an output) — never HOW it is built. "
    "Do NOT make \"X exists\", \"X has required frontmatter\", \"X delegates to / reuses / calls Y\", "
    "\"doesn't reimplement Z\", or \"uses helper W\" a criterion — those are implementation choices "
    "a test can't cleanly verify (a judge will split on them). Named deliverable files from the request "
    "(e.g. SKILL.md, known_places.json) belong in ASSUMPTIONS for the coder, not as existence criteria.\n"
    '  "assumptions": array of {"text": string, "confidence": number 0..1} — when a detail is '
    "unspecified but has a conventional default (ASCII vs Unicode, in-place vs new list, etc.), "
    "record the default here and PROCEED. Confidence calibration: assign HIGH confidence (>=0.85) to "
    "a conventional/obvious default (whitespace tokenization, ASCII, raise-on-empty, return-a-new-list); "
    "reserve confidence below 0.7 ONLY for a genuine coin-flip where guessing wrong is likely. Do NOT "
    "under-hedge a reasonable interpretation — a sensible default is high-confidence, not a maybe. "
    "ALWAYS record at least ONE assumption: even a fully specified request rests on some convention "
    "(language/runtime, file placement, input handling) — state it with high confidence. An EMPTY "
    "assumptions list routes the task to a human instead of proceeding.\n"
    '  "open_questions": array of {"text": string, "blocking": boolean}. Set blocking=true ONLY when '
    "there is NO sensible default and guessing wrong would build the WRONG thing — e.g. an "
    "unspecified target file/system, or a required numeric target the request never gave. A detail "
    "with an obvious convention is an assumption, NOT a blocking question.\n"
    "REQUEST:\n")

# The REFINE pass: a second model rewrites the draft into reliable atomic form. glm's draft is
# improved by _CHARTER_PROMPT but still inconsistent (over-splits by type, re-adds "is importable"
# cruft), so kimi normalizes it. Same output schema; fail-SAFE (a bad refine keeps the valid draft).
_REFINE_PROMPT = (
    "You are the REFINE phase of an autonomous coding loop. You receive a DRAFT charter (JSON) for "
    "the REQUEST. Rewrite it into a cleaner Definition of Done and output ONLY the corrected JSON "
    "with the SAME keys (interpreted_intent, dod, assumptions, open_questions). Fixes to apply:\n"
    '  - SPLIT any compound criterion (joined by "and"/"or", or naming two outcomes) into separate '
    "atomic criteria — one observable behavior each.\n"
    "  - MERGE over-decomposed criteria aggressively: aim for the FEWEST criteria that capture the "
    "behavior — roughly ONE per public function the request names (a two-function module is about 2 "
    "criteria, NOT 7). If several describe the SAME function (e.g. \"add for ints\" + \"add for "
    "floats\", or a function's edge cases), combine into ONE with a multi-example verify_intent. DROP "
    "\"file exists\" / \"is importable\" / \"is valid Python\" / \"has frontmatter\" "
    "criteria — the tests prove those by importing and calling the code. Keep named deliverable "
    "files from the request as ASSUMPTIONS for the coder, not as existence criteria in the DoD.\n"
    '  - Each verify_intent = ONE concrete assertion (e.g. "add(2,3)==5; add(-1,1)==0"), 1:1 with '
    "one test. No checklists.\n"
    "  - DROP implementation-STRUCTURE criteria (\"X delegates to / reuses / calls Y\", \"doesn't "
    "reimplement Z\", \"uses helper W\"): those are HOW the code is built, not observable behavior, and "
    "a judge can't cleanly verify them. If reuse matters, move it to assumptions, not the DoD.\n"
    "  - PRESERVE EXTERNAL-SYSTEM INTEGRATION CRITERIA (CRITICAL): if the DRAFT contains any "
    "integration-tier criterion that exercises a REAL external tool/API/CLI via subprocess or HTTP, "
    "you MUST keep it — do NOT merge it into a unit criterion, do NOT downgrade it to unit, do NOT "
    "drop it as 'implementation structure'. The request named an external system (CLI tool, REST API, "
    "RPC endpoint, command-line interface, existing repository service like gws, Hermes, Claude Code, "
    "kubectl, gh, aws, etc.) — at least ONE integration-tier criterion that shells out to the REAL "
    "binary MUST remain in the DoD. If the DRAFT has ALL unit-tier criteria for a request that names "
    "an external system, ADD an integration-tier criterion that exercises the real binary with a safe "
    "invocation (--dry-run, --help, --validate, or a harmless read-only call). A refiner that drops "
    "or downgrades integration criteria for external-system requests produces DEFECTIVE charters.\n"
    "  - Keep a blocking open_question ONLY for a genuine gap (no sensible default); turn "
    "defaultable details into assumptions instead.\n"
    "  - UNMEASURABLE GOAL guard: if the DRAFT manufactured a benchmark / baseline / threshold / "
    "'reports a lower value' criterion for a vague goal the REQUEST never quantified (faster, better, "
    "optimize, more robust), DELETE that criterion and emit a BLOCKING open_question instead — an "
    "unmeasurable goal must route to a human, never proceed on an invented target.\n"
    "  - Calibrate each assumption's confidence: a conventional/obvious default is HIGH confidence "
    "(>=0.85); reserve confidence below 0.7 only for a genuine coin-flip. Do NOT under-hedge a "
    "reasonable default into a low score (that needlessly routes a fine task to a human). NEVER "
    "return an empty assumptions list — keep the draft's assumptions (recalibrated) or state the one "
    "load-bearing conventional default; an empty list routes a fine task to a human.\n"
    "  - Do NOT add requirements, numeric targets, or behaviors the REQUEST/DRAFT did not contain.\n"
    "DRAFT:\n")


# Per-model-call subprocess ceiling. RAISE-only override via DEVLOOP_DISPATCH_TIMEOUT_S — the
# max() clamp means an env/caller value can never LOWER the floor (project policy: never shorten
# timeouts to "fix" a slow model). This is a per-call ceiling, not a whole-run wall clock.
DISPATCH_TIMEOUT_S = 1800


def _dispatch_timeout() -> int:
    try:
        return max(DISPATCH_TIMEOUT_S, int(os.environ.get("DEVLOOP_DISPATCH_TIMEOUT_S", "0") or 0))
    except (TypeError, ValueError):
        return DISPATCH_TIMEOUT_S


def _chat_raw(prompt, model, cwd=None, toolsets="", timeout=None):
    """One real `hermes chat` dispatch. Returns (combined stdout+stderr, returncode)."""
    cmd = [HERMES_BIN, "chat", "-q", prompt, "-m", model, "-Q", "--yolo"]
    if toolsets:
        cmd += ["-t", toolsets]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout or _dispatch_timeout(), cwd=cwd)
    return (r.stdout or "") + "\n" + (r.stderr or ""), r.returncode


# A response worth retrying (#36) — NOT a quality judgement (a terse-but-real answer is fine); only
# an empty body, an explicit refusal, or a non-zero process exit (transport/API error) is transient.
_REFUSAL_MARKERS = ("i cannot ", "i can't ", "i am unable", "i'm unable", "as an ai", "cannot assist", "i won't ")
_sleep = time.sleep   # indirection so tests don't actually wait between retries
_BACKOFF_S = 1.5


def _unusable(out, code) -> bool:
    if code not in (0, None):           # process / transport / API error
        return True
    text = (out or "").strip()
    if not text:                        # empty body
        return True
    low = text.lower()
    return any(m in low for m in _REFUSAL_MARKERS)


_DEBUG_SEQ = [0]   # per-process capture counter (one run per process at the CLI boundary)


def _capture_debug(prompt, model, out):
    """DEVLOOP_DEBUG=1: persist this model call's FULL prompt + raw reply under
    $DEVLOOP_DEBUG_DIR/dispatch/ (the runner points that at the run's .devloop dir, so the
    captures ride the post-run bundle to devloop-traces/<name>/). Off by default — raw replies
    are diagnosis material, not routine telemetry. Best-effort: never fails a dispatch."""
    if os.environ.get("DEVLOOP_DEBUG") != "1":
        return
    d = os.environ.get("DEVLOOP_DEBUG_DIR")
    if not d:
        return
    try:
        cap = os.path.join(d, "dispatch")
        os.makedirs(cap, exist_ok=True)
        _DEBUG_SEQ[0] += 1
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(model))[:40]
        with open(os.path.join(cap, f"{_DEBUG_SEQ[0]:03d}-{safe}.txt"), "w",
                  encoding="utf-8") as f:
            f.write(f"MODEL: {model}\n=== PROMPT ===\n{prompt}\n=== REPLY ===\n{out}\n")
    except OSError:
        pass


def _chat(prompt, model, cwd=None, toolsets="", timeout=None, retries=None):
    """Dispatch a phase, RETRYING a transient failure (#36): an empty/refusal/process-error result is
    retried up to config.MAX_DISPATCH_RETRIES with a small backoff, then FAIL-CLOSED — the last (bad)
    result is returned so the caller's parse path routes to HUMAN_REVIEW, never fabricating success.
    A raised subprocess error (timeout/transport) counts as a retryable failure, not a crash."""
    retries = config.MAX_DISPATCH_RETRIES if retries is None else retries
    last = ("", 1)
    for attempt in range(retries + 1):
        try:
            last = _chat_raw(prompt, model, cwd=cwd, toolsets=toolsets, timeout=timeout)
        except Exception as e:          # noqa: BLE001 — transport/timeout is retryable, not fatal
            last = (f"dispatch error: {type(e).__name__}: {e}", 1)
        if not _unusable(*last):
            break
        if attempt < retries:
            _sleep(_BACKOFF_S * (attempt + 1))
    _capture_debug(prompt, model, last[0])
    return last


def _snapshot(d):
    """{path: (mtime_ns, size)} for every NON-JUNK file under d — to detect whether IMPLEMENT
    changed anything. Junk (worktree._JUNK_SEGMENTS: venvs, tool caches, .git, ...) is pruned
    from the walk: a coder-spawned venv is not progress, and feeding third-party files to the
    lint gate can false-block a pass (learn-accept live run: one coder .venv -> 992 "changed"
    files, 852 of them linted)."""
    snap = {}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in worktree._JUNK_SEGMENTS]
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
                snap[p] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
    return snap


def _count_changed(before, after):
    changed = sum(1 for k, v in after.items() if before.get(k) != v)
    changed += sum(1 for k in before if k not in after)   # deletions
    return changed


def _changed_paths(before, after):
    """Files the coder CREATED or MODIFIED (existing paths only — a deleted file can't be linted).
    This is the 'what did the coder write' list the lint gate runs on."""
    return [k for k, v in after.items() if before.get(k) != v]


def _extract_json(text):
    """Pull a JSON object out of model output (fenced block preferred, else first{..}last})."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    cand = m.group(1) if m else None
    if cand is None:
        i, j = text.find("{"), text.rfind("}")
        cand = text[i:j + 1] if (i != -1 and j > i) else None
    if cand is None:
        return None
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        return None


def _coerce_qa(items, default_confidence=0.7, *, kind="open_questions"):
    """Coerce bare-string elements to the {text, ...} object shape the validator and
    downstream gates expect. GLM-5.2 (the planner) commonly returns open_questions and
    assumptions as string arrays instead of object arrays — a schema slip that fails
    validation at state.py:142 ('open_questions[0] is not an object') and wastes a full
    devloop round-trip. This normalizer catches the common LLM slip BEFORE validation.

    - Bare string -> {"text": str, "blocking": False} (open_questions) or
                     {"text": str, "confidence": default_confidence} (assumptions)
    - Already a dict -> passed through unchanged
    - None/non-list -> empty list

    kind: "open_questions" adds only "blocking", "assumptions" adds only "confidence".
    This avoids cross-contaminating keys (quality review 2026-07-05).
    """
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if isinstance(item, str):
            if kind == "assumptions":
                result.append({"text": item, "confidence": default_confidence})
            else:
                result.append({"text": item, "blocking": False})
        elif isinstance(item, dict):
            result.append(item)
        # non-str, non-dict elements are dropped (silently — a stray null or number
        # in the array is garbage, not a question)
    return result


def _wrap_charter(data):
    """Wrap the planner's core fields into a full, schema-valid Charter (assigns stable ids).

    Normalizes open_questions and assumptions via _coerce_qa to handle the common
    planner-model slip of returning string arrays instead of object arrays.
    """
    dod = []
    for k, c in enumerate(data.get("dod") or [], 1):
        tier = c.get("tier")
        if tier not in ("unit", "integration"):
            tier = "unit"   # fail-safe: an unknown tier never invents a new taxonomy downstream
        dod.append({"id": f"c{k}", "criterion": c.get("criterion", ""),
                    "verify_intent": c.get("verify_intent", ""), "kind": "shown", "tier": tier})
    # Only the keys downstream stages actually consume — the stub fields (happy_path, blast_radius,
    # backoff_map, advisors_verdict, ambiguity_decision, purpose) were written but never re-ingested
    # (state-flow audit), so we no longer emit dead state. The ambiguity decision is journaled where
    # it's actually read back: the trace ('ambiguity_gate' event), not a stale charter field.
    return {
        "interpreted_intent": data.get("interpreted_intent", ""),
        "dod": dod,
        "assumptions": _coerce_qa(data.get("assumptions", []), kind="assumptions"),
        "open_questions": _coerce_qa(data.get("open_questions", []), kind="open_questions"),
    }


def _git_history_learnings(target_dir, max_commits=30):
    """Consolidate the repo's commit history into a compact learnings summary for planning.

    Two-phase approach:
    1. MECHANICAL: scan git log for commits with THESIS/LEARNINGS sections, extract raw text
    2. LLM CONSOLIDATION: feed raw learnings to the planner model, which:
       - Identifies which learnings supersede earlier ones (latest information wins)
       - Consolidates duplicates and related themes
       - Produces a compact summary organized by topic, not by commit
       - References exact git SHAs for traceability

    The consolidated summary is written to <target_dir>/.devloop/git_learnings_consolidated.txt
    so it doesn't pollute the charter prompt context. The compact summary (≤15 lines) is
    returned for injection into the planner prompt.

    Falls back to mechanical extraction if the LLM is unavailable (test mode, no HERMES_BIN).
    """
    if not target_dir or not os.path.isdir(target_dir):
        return ""

    # Phase 1: MECHANICAL — extract raw structured commits from git log
    try:
        r = subprocess.run(
            ["git", "-C", target_dir, "log", f"--max-count={max_commits}",
             "--format=%H%n%B%n---COMMIT-END---"],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or not r.stdout.strip():
            return ""
    except Exception:
        return ""

    raw_commits = []
    for block in r.stdout.split("---COMMIT-END---"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        sha = lines[0][:12] if lines else ""
        body = "\n".join(lines[1:])
        # Only include commits with structured learnings
        if "THESIS" not in body and "LEARNINGS" not in body and "INTENTION" not in body:
            continue
        # Keep the full body for the LLM to read (it will consolidate)
        raw_commits.append(f"=== COMMIT {sha} ===\n{body.strip()}\n")

    if not raw_commits:
        return ""

    raw_history = "\n".join(raw_commits)

    # Also read the devloop learnings journal (cross-run lessons from LEARNINGS.jsonl)
    # Rich journaling (user ask 2026-07-05): entries now carry structured learnings_text,
    # references, and failure_conditions fields alongside the mechanical lesson summary.
    # The consolidator needs ALL of these to carry forward key learnings and 'what not to
    # try again' patterns. Latest entry wins on contradiction (enforced by the prompt rules).
    learnings_journal = ""
    try:
        lj_path = os.path.join(_WRITE_SAFE_ROOT, "devloop-traces", "LEARNINGS.jsonl")
        if os.path.isfile(lj_path):
            with open(lj_path) as f:
                lj_lines = f.readlines()[-20:]
            lj_entries = []
            for line in lj_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    import json as _j
                    obj = _j.loads(line)
                    if not isinstance(obj, dict):
                        continue
                    parts = []
                    # The mechanical summary line (always present, back-compat)
                    if obj.get("lesson"):
                        parts.append(f"  summary: {obj['lesson']}")
                    # Rich LEARNINGS section from the commit message
                    if obj.get("learnings_text"):
                        parts.append(f"  learnings: {obj['learnings_text']}")
                    # References (SHAs, trace paths)
                    if obj.get("references"):
                        parts.append(f"  references: {obj['references']}")
                    # Failure conditions ('what NOT to try again')
                    fcs = obj.get("failure_conditions") or []
                    if isinstance(fcs, list) and fcs:
                        parts.append("  failure_conditions:")
                        for fc in fcs:
                            # Strip existing AVOID:/DO NOT prefix to avoid double-prefixing
                            fc_clean = fc
                            if fc_clean.startswith("AVOID: "):
                                fc_clean = fc_clean[7:]
                            elif fc_clean.startswith("AVOID:"):
                                fc_clean = fc_clean[6:]
                            elif fc_clean.startswith("DO NOT "):
                                fc_clean = fc_clean[7:]
                            parts.append(f"    AVOID: {fc_clean.strip()}")
                    if parts:
                        lj_entries.append("\n".join(parts))
                except Exception:
                    continue
            if lj_entries:
                learnings_journal = "\n---\n".join(lj_entries)
    except Exception:
        pass

    # N1: Also read the project-local LESSONS.jsonl (per-project learnings).
    # Same schema as LEARNINGS.jsonl — same readers, same last-20 cap.
    # Guarded with isfile: may not exist on a fresh worktree.
    try:
        pl_path = os.path.join(target_dir, ".devloop", "LESSONS.jsonl")
        if os.path.isfile(pl_path):
            with open(pl_path) as f:
                pl_lines = f.readlines()[-20:]
            pl_entries = []
            for line in pl_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    import json as _j2
                    obj = _j2.loads(line)
                    if not isinstance(obj, dict):
                        continue
                    parts = []
                    if obj.get("lesson"):
                        parts.append(f"  summary: {obj['lesson']}")
                    if obj.get("learnings_text"):
                        parts.append(f"  learnings: {obj['learnings_text']}")
                    if obj.get("references"):
                        parts.append(f"  references: {obj['references']}")
                    fcs = obj.get("failure_conditions") or []
                    if isinstance(fcs, list) and fcs:
                        parts.append("  failure_conditions:")
                        for fc in fcs:
                            # Strip existing AVOID:/DO NOT prefix to avoid double-prefixing
                            fc_clean = fc
                            if fc_clean.startswith("AVOID: "):
                                fc_clean = fc_clean[7:]
                            elif fc_clean.startswith("AVOID:"):
                                fc_clean = fc_clean[6:]
                            elif fc_clean.startswith("DO NOT "):
                                fc_clean = fc_clean[7:]
                            parts.append(f"    AVOID: {fc_clean.strip()}")
                    if parts:
                        pl_entries.append("\n".join(parts))
                except Exception:
                    continue
            if pl_entries:
                project_journal = "\n---\n".join(pl_entries)
                # Merge: LESSONS.jsonl appended AFTER LEARNINGS.jsonl so project-local
                # learnings are last in the journal — mechanical dedup keeps the LAST
                # occurrence (latest wins), so project-local overrides repo-wide on conflict.
                learnings_journal = (learnings_journal + "\n---\n" + project_journal) if learnings_journal else project_journal
    except Exception:
        pass

    # Phase 2: LLM CONSOLIDATION — the model reads raw history and produces a compact summary
    # Skip LLM in test mode (HERMES_BIN stubs or DEVLOOP_NO_HISTORY_LLM set)
    if os.environ.get("DEVLOOP_NO_HISTORY_LLM") == "1":
        return _mechanical_learnings_fallback(raw_commits, target_dir,
                                              learnings_journal=learnings_journal)

    try:
        hermes_bin = HERMES_BIN
        if not hermes_bin or str(hermes_bin).startswith("/tmp/"):
            return _mechanical_learnings_fallback(raw_commits, target_dir,
                                                  learnings_journal=learnings_journal)

        prompt = (
            "You are a learnings consolidator for an autonomous coding loop (devloop).\n"
            "You receive the raw git commit history AND a cross-run learnings journal, each\n"
            "entry containing INTENTION/THESIS/LEARNINGS/REFERENCES sections. Your job is to\n"
            "consolidate these into a COMPACT summary that a planner can use to avoid past\n"
            "mistakes and build on patterns that worked.\n\n"
            "RULES:\n"
            "- LATEST INFORMATION WINS: if a later commit or journal entry corrects or\n"
            "  supersedes an earlier learning, keep only the corrected version. Note what\n"
            "  was superseded. This is the most important rule — contradictions are resolved\n"
            "  by chronological order (newer wins).\n"
            "- CONSOLIDATE: group related learnings by topic, not by commit. Merge duplicates.\n"
            "- BE COMPACT: output at most 15 lines. Each line is one actionable learning.\n"
            "- REFERENCE SHAs: prefix each line with the commit SHA it came from.\n"
            "- SKIP NOISE: ignore boilerplate, disclaimers, and non-actionable observations.\n"
            "- FOCUS ON PATTERNS: what approaches worked? What failed? What was surprising?\n"
            "- CARRY FORWARD FAILURE CONDITIONS: if a learning is a 'what NOT to do' (failure\n"
            "  condition, anti-pattern, pitfall), preserve it — these are the most valuable\n"
            "  signals for a planner. Prefix them with 'AVOID:' for visibility.\n"
            "- OUTPUT ONLY the consolidated summary (no preamble, no code fence)\n\n"
            f"RAW GIT HISTORY ({len(raw_commits)} structured commits):\n{raw_history}\n\n"
        )
        if learnings_journal:
            prompt += (
                f"CROSS-RUN LEARNINGS JOURNAL (from LEARNINGS.jsonl and LESSONS.jsonl —\n"
                f"repo-wide and project-local learnings with structured learnings_text,\n"
                f"references, and failure_conditions fields):\n{learnings_journal}\n\n"
            )

        out, rc = _chat(prompt, PLANNER, timeout=60)
        out = (out or "").strip()
        if out and not out.startswith("dispatch error"):
            # Write the consolidated summary to file
            learnings_dir = os.path.join(target_dir, ".devloop")
            os.makedirs(learnings_dir, exist_ok=True)
            try:
                with open(os.path.join(learnings_dir, "git_learnings_consolidated.txt"), "w") as f:
                    f.write(f"Consolidated git history learnings ({len(raw_commits)} commits analyzed):\n")
                    f.write(out + "\n")
            except OSError:
                pass
            return out
    except Exception as e:
        # P5: log when we fall back to mechanical extraction — the "latest wins"
        # rule is NOT applied in the fallback, so the planner gets unconsolidated
        # noise instead of a distilled summary. This is silent in production.
        import logging as _logging
        _logging.getLogger("dispatch").warning(
            "git history LLM consolidation failed (%s), falling back to mechanical "
            "extraction — 'latest wins' rule NOT applied", type(e).__name__)

    # Fallback: mechanical extraction (no LLM)
    return _mechanical_learnings_fallback(raw_commits, target_dir,
                                          learnings_journal=learnings_journal)


_WRITE_SAFE_ROOT = os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data")


def _mechanical_learnings_fallback(raw_commits, target_dir, learnings_journal=""):
    """Fallback: extract LEARNINGS sections mechanically (no LLM consolidation).

    P0-2 fix (advisor review 2026-07-05): now accepts learnings_journal and includes
    its content (especially failure_conditions) in the output. Previously the journal
    was silently dropped when the LLM path was skipped.

    P1-6 fix: applies a lightweight mechanical latest-wins dedup — normalizes each
    line to lowercase, drops exact duplicates keeping the LAST occurrence (latest wins).
    """
    learnings = []
    for commit_text in raw_commits:
        # Extract the LEARNINGS section only (most actionable)
        if "LEARNINGS:" in commit_text:
            start = commit_text.index("LEARNINGS:") + len("LEARNINGS:")
            rest = commit_text[start:]
            end = len(rest)
            for marker in ("\nTHESIS:", "\nINTENTION:", "\nREFERENCES:"):
                pos = rest.find(marker)
                if pos != -1 and pos < end:
                    end = pos
            section = rest[:end].strip()
            sha = commit_text.split("\n")[0].replace("=== COMMIT ", "").replace(" ===", "")
            for line in section.split("\n"):
                line = line.strip()
                if line and not line.startswith("THESIS") and not line.startswith("INTENTION"):
                    learnings.append(f"[{sha}] {line}")

    # P0-2: Include journal content (failure_conditions are the most valuable)
    if learnings_journal:
        for entry_block in learnings_journal.split("\n---\n"):
            entry_block = entry_block.strip()
            if not entry_block:
                continue
            # Extract AVOID: lines from the journal block
            for line in entry_block.split("\n"):
                line = line.strip()
                if line.startswith("AVOID:") or line.startswith("DO NOT"):
                    learnings.append(f"[journal] {line}")
                elif line.startswith("learnings:") or line.startswith("summary:"):
                    # Include the journal's learnings/summary lines too
                    content = line.split(":", 1)[-1].strip()
                    if content:
                        learnings.append(f"[journal] {content}")

    if not learnings:
        return ""

    # P1-6: Mechanical latest-wins dedup — normalize to lowercase, keep last occurrence.
    # Strip the [sha] prefix before normalizing so the same learning from different
    # commits is recognized as a duplicate.
    import re as _re
    seen = {}
    for line in learnings:
        # Strip [sha] or [journal] prefix for dedup key
        key_text = _re.sub(r'^\[[^\]]+\]\s*', '', line).strip()
        key = " ".join(key_text.lower().lstrip("-•* ").split())
        seen[key] = line  # last occurrence wins (latest)
    deduped = list(seen.values())

    # Write to file
    if target_dir and os.path.isdir(target_dir):
        ld = os.path.join(target_dir, ".devloop")
        os.makedirs(ld, exist_ok=True)
        try:
            with open(os.path.join(ld, "git_learnings_consolidated.txt"), "w") as f:
                f.write(f"Mechanical learnings extraction ({len(deduped)} entries, deduped):\n")
                for l in deduped[:15]:
                    f.write(l + "\n")
        except OSError:
            pass

    return "\n".join(deduped[:15])


def _environment_survey(target_dir):
    """ENVIRONMENT SURVEY (user ask 2026-07-02): investigate what already exists BEFORE building a
    solve. Injected into the charter/refine prompts (which run with NO file tools, so the survey
    must come to them) — the target checkout's modules and public symbols, with a directive to
    align interpretation/assumptions with the existing style and reuse existing services where
    that does NOT conflict with the request. '' for a greenfield/empty tree. Reuses
    _repo_symbols — the same lens the designer's modules hint uses."""
    if not target_dir:
        return ""
    syms = _repo_symbols(target_dir)
    if not syms:
        return ""
    listing = "\n".join(f"- {m}: {', '.join(s[:12])}" for m, s in sorted(syms.items())[:20])
    return ("\nEXISTING ENVIRONMENT (modules and public symbols already present in the target "
            "repo). Investigate before solving: align your interpretation and assumptions with "
            "this existing style, PREFER reusing these services/helpers over re-inventing them, "
            "and record any reuse choice as an assumption — but NEVER let this override what the "
            "request explicitly asks for. Do NOT write criteria about preserving/keeping current "
            "behavior (a whole-suite regression gate already guarantees that); every criterion "
            "must state a NEW concretely-checkable behavior with explicit expected values. When "
            "the request MODIFIES or extends this existing code, include at least ONE "
            'integration-tier criterion (tier: "integration") that exercises the NEW behavior '
            "THROUGH the existing public surface (concrete inputs -> explicit expected values — "
            "still a new behavior, never a preservation check):\n"
            + listing + "\n")


def charter_via_ask(request, planner=PLANNER, target_dir=None):
    # Git history learnings: scan repo commits for prior THESIS/LEARNINGS, distill to file,
    # feed compact version to the planner so it learns from previous runs (user ask 2026-07-05).
    git_learnings = _git_history_learnings(target_dir)
    history_block = ""
    if git_learnings:
        history_block = (
            "\nPRIOR GIT HISTORY LEARNINGS (from this repo's commit history — guidance, NOT new "
            "requirements). These are distilled from previous devloop runs and manual commits "
            "on this repo. Use them to AVOID repeating past mistakes and to BUILD on patterns "
            "that worked. Full detail in .devloop/git_learnings_consolidated.txt:\n"
            + git_learnings + "\n"
        )
    out, _ = _chat(_CHARTER_PROMPT + request + history_block + _environment_survey(target_dir),
                   planner, toolsets="")
    data = _extract_json(out)
    if not data or not data.get("dod"):
        # fail-closed: unparseable/empty -> a Charter with empty dod -> validate_charter fails
        # -> ambiguity gate routes to HUMAN_REVIEW (never silently proceeds on a bad charter).
        return _wrap_charter({"interpreted_intent": "(planner produced no parseable DoD)",
                              "dod": [], "assumptions": [],
                              "open_questions": [{"text": "planner output unparseable", "blocking": True}]})
    return _wrap_charter(data)


def refiner_via_ask(charter, request, refiner=REFINER, target_dir=None):
    """REFINE the draft charter into atomic form (split compounds, merge over-decomposition, drop
    existence cruft). Fail-SAFE: if the refiner returns nothing parseable, KEEP the draft charter
    (it is already valid) rather than discarding good work or routing a fine task to a human. A
    refiner that adds a blocking open_question still flows through the ambiguity gate downstream."""
    draft = {"interpreted_intent": charter.get("interpreted_intent", ""),
             "dod": [{"criterion": c.get("criterion", ""), "verify_intent": c.get("verify_intent", "")}
                     for c in charter.get("dod", [])],
             "assumptions": charter.get("assumptions", []),
             "open_questions": charter.get("open_questions", [])}
    prompt = (_REFINE_PROMPT + json.dumps(draft, indent=2) + "\nREQUEST:\n" + request
              + _environment_survey(target_dir))
    out, _ = _chat(prompt, refiner, toolsets="")
    data = _extract_json(out)
    if not data or not data.get("dod"):
        return charter                       # fail-safe: keep the valid draft
    return _wrap_charter(data)


_ADVISOR_PROMPT = (
    "You are an ADVISOR doing a FINAL completeness check on a Definition of Done before coding. "
    "Output ONLY a JSON object: { \"concerns\": [ {\"text\": string, \"blocking\": boolean} ] }\n"
    "Block (blocking=true) ONLY in the rare case where proceeding would build the WRONG thing — "
    "specifically: a whole BEHAVIOR the request EXPLICITLY names is ENTIRELY ABSENT from the DoD, or a "
    "criterion directly CONTRADICTS the request. DEFAULT TO NOT BLOCKING.\n"
    "A competent implementer fills reasonable defaults, so do NOT block on any of these: a missing "
    "implementation detail the request did not specify (backoff/sleep between retries, a retry count, "
    "iteration order, performance); an unspecified edge case that has a sensible default; HOW the code "
    "is structured (delegation, reuse, 'uses helper Y', file layout, 'delegates to X'); or merely that "
    "'the DoD could be more thorough'. Those are implementation choices, NOT wrong-thing gaps.\n"
    "IMPORTANT: the DoD deliberately EXCLUDES implementation structure (behavior-not-structure rule). "
    "If the REQUEST says 'using Y' / 'uses Y' / 'delegates to Y' / 'reuses Y' / 'imports Y' / 'MUST "
    "import' and the DoD covers the observable BEHAVIOR without naming Y, that requirement was dropped "
    "ON PURPOSE (it is recorded as an assumption for the coder) — it is NOT a missing behavior; NEVER "
    "block on a dropped delegation/reuse/structure requirement. If every behavior the request "
    "explicitly names is present in the DoD, return an empty list.\n"
    "REQUEST:\n")


def advisor_via_ask(charter, request, advisor=ADVISOR):
    """ADVISORS review (Phase 0): a fresh model checks the refined DoD for COMPLETENESS/correctness
    vs the request, and folds any BLOCKING gap into open_questions — which the ambiguity gate already
    consumes (-> HUMAN_REVIEW). Only blocking concerns are surfaced (advisory nitpicks would just add
    write-only noise / drag the confidence floor). Fail-SAFE: an unparseable review leaves the
    charter untouched (an advisor outage never blocks a good plan)."""
    dod = "\n".join(f"- {c.get('criterion', '')}" for c in charter.get("dod", []))
    prompt = _ADVISOR_PROMPT + request + "\nDoD:\n" + dod

    def _blocking_concerns(out):
        concerns = (_extract_json(out) or {}).get("concerns") or []
        # require non-empty text: a {"blocking": true} with no reason would block a good plan on a
        # meaningless "advisor:" stub — the garbage-never-blocks promise, in the over-block direction.
        return [c["text"] for c in concerns
                if isinstance(c, dict) and c.get("blocking") and c.get("text")]

    # MAJORITY VOTE (spike fix): the advisor blocks intermittently (it flagged a clear task on one run
    # but not another). Vote ADVISOR_VOTES times and block ONLY if a strict majority flag a blocking
    # gap — a single flaky over-block no longer routes a fine task to a human.
    votes = [_blocking_concerns(_chat(prompt, advisor, toolsets="")[0]) for _ in range(config.ADVISOR_VOTES)]
    if sum(1 for v in votes if v) * 2 <= len(votes):
        return charter                       # not a majority -> no blocking gap -> proceed unchanged
    blocking = next(v for v in votes if v)   # the concerns from a blocking vote
    augmented = dict(charter)
    augmented["open_questions"] = list(charter.get("open_questions", [])) + [
        {"text": "advisor: " + t, "blocking": True} for t in blocking]
    return augmented


# Handoff-quality directives folded into the coder prompt so the code is documented + defensively
# correct BY CONSTRUCTION (not a post-hoc pass). Framed as HOW-to-write, never as new DoD criteria,
# so it can't inflate the DoD or trip the ambiguity/judge gates (behavior-not-structure stays intact).
_IMPL_STYLE = (
    "Write the code to be HANDED OFF, not merely to pass:\n"
    "- DOCS/BREADCRUMBS (token-efficient): a one-line purpose header per file and major section; "
    "comment the WHY and any non-obvious invariant, never restate what the code literally does; add "
    "file:line or symbol cross-references between related pieces so the next reader navigates cheaply.\n"
    "- ERROR-CHECKING where it matters: validate inputs at boundaries and handle the error/edge paths "
    "this DoD implies; fail loudly or safely on the unexpected. Targeted guards only — no blanket "
    "try/except, no defensive bloat.\n"
    "- SHIPPED code never references the harness: do not mention generated test filenames, criterion "
    "ids (dod:cN), test expectations, or this loop in code or comments — write them as if the tests "
    "did not exist.\n"
    "- NEVER overfit a wrong test: if a test asserts an expected value that CONTRADICTS the "
    "criterion's plain semantics (miscounted words/characters, wrong arithmetic), do NOT add "
    "special-case logic just to make that test pass — implement the honest semantics and let that "
    "test fail; the loop audits failing tests and can regenerate wrong ones. Special-casing code to "
    "mirror a test's expectations is a DEFECT.\n"
    "- EXTERNAL BOUNDARY RULE: if the DoD includes an integration-tier criterion that exercises a "
    "real external binary (subprocess.run against gws, gh, kubectl, etc.), the implementation MUST "
    "call that binary directly via subprocess — do NOT wrap it in an internal helper function that "
    "the test then mocks. The test exercises the REAL binary at the integration boundary; wrapping "
    "it in a helper that gets mocked defeats the integration test (the real binary is never called). "
    "If you need a helper for reuse, the helper must CONTAIN the subprocess call and the integration "
    "test must exercise the helper, not mock it.\n"
    "- Do NOT create virtualenvs or install packages; run tests with the interpreter already available.\n"
    "- Do NOT leave scratch files (notes, debug scripts, experiments, temporary reproductions) in "
    "the tree — delete your scratch before finishing; every file that remains is treated as a "
    "deliverable and will be committed.\n"
    "These are HOW to write it, NOT new requirements: satisfy exactly the DoD above and add no scope.\n")


_DIAGNOSE_PROMPT = (
    "You are a senior debugger. The code in the working directory FAILS the checks below. Read the "
    "relevant code, then give a SHORT, SPECIFIC root-cause diagnosis and the exact fix (what to change "
    "and why). Pinpoint the defect — do NOT rewrite whole files, do NOT restate the task. No preamble.\n")


def diagnose_via_ask(charter, last_failure, target_dir, diagnoser=DIAGNOSER):
    """#35 cascade escalation: a stronger INDEPENDENT model reads the failing evidence + the code and
    returns a root-cause diagnosis to guide the next coder attempt (coding stays kimi-only). Fail-safe:
    an empty/error reply -> '' (the coder simply proceeds with the basic failure feedback)."""
    dod = "\n".join(f"- {c.get('criterion', '')}" for c in charter.get("dod", []))
    fails = json.dumps(last_failure)[:1500]
    out, _ = _chat(_DIAGNOSE_PROMPT + "DoD:\n" + dod + "\nFAILING EVIDENCE:\n" + fails,
                   diagnoser, cwd=target_dir, toolsets="file")
    text = (out or "").strip()
    return text if text and "dispatch error" not in text[:40].lower() else ""


def implementer_via_ask(target_dir, coder=CODER):
    def implement(charter, attempt, last_failure):
        crit = "\n".join(f"- {c['criterion']} (verify: {c['verify_intent']})" for c in charter["dod"])
        # Assumptions reach the coder as guidance (deep review 2026-07-01): behavior-not-structure
        # moves "use module Y"-style preferences OUT of the DoD into assumptions — without this line
        # they were write-only and a request's recorded reuse preference never reached the coder.
        assump = "\n".join(f"- {a.get('text', '')}" for a in charter.get("assumptions", [])
                           if isinstance(a, dict) and a.get("text"))
        extra = ""
        if last_failure:
            extra = "\nThe previous attempt FAILED verification:\n" + json.dumps(last_failure)[:1200] + "\nFix it."
            # #35 DEBUG cascade: on a REPEAT failure, escalate to a stronger independent diagnoser whose
            # root-cause analysis guides THIS kimi attempt. Coding stays kimi-only — only diagnosis escalates.
            if attempt >= config.DIAGNOSE_AFTER_ATTEMPT:
                diagnosis = diagnose_via_ask(charter, last_failure, target_dir)
                if diagnosis:
                    extra += "\n\nROOT-CAUSE DIAGNOSIS (independent reviewer model):\n" + diagnosis[:1500]
        prompt = (
            f"You are the IMPLEMENT phase of an autonomous coding loop. Use your file tools to "
            f"create or edit code files (use ABSOLUTE paths under {target_dir}) so this Definition "
            f"of Done is satisfied. The tests already exist on disk and are the ORACLE: READ them "
            f"first and match the EXACT module and function names they import; do NOT write, edit, "
            f"move, or delete any test file — change the CODE until the tests pass.\n"
            f"Intent: {charter['interpreted_intent']}\nDoD:\n{crit}\n"
            + (f"Assumptions (context + preferences to honor — e.g. which existing module to reuse; "
               f"NOT new requirements):\n{assump}\n" if assump else "")
            + extra + "\n"
            + _IMPL_STYLE
            + "Stop when done.")
        before = _snapshot(target_dir)
        out, code = _chat(prompt, coder, cwd=target_dir, toolsets="file,terminal")
        after = _snapshot(target_dir)
        # Rich result so the loop can distinguish a model/dispatch ERROR (coder errored or wrote
        # nothing) from a genuine code red (dispatch-error short-circuit), and so the lint gate can
        # run on exactly the files the coder touched (changed_paths).
        return {"exit_code": code, "files_changed": _count_changed(before, after),
                "summary": out.strip()[-600:], "changed_paths": _changed_paths(before, after)}
    return implement


def merge_resolver_via_ask(coder=CODER):
    """LLM conflict resolution at merge time (user decision 2026-07-02: leverage the LLM to do
    the merge). Returns resolve(workdir, conflicted) -> bool. The model only EDITS files —
    worktree._resolve_conflicts enforces the guards in code (no test-file edits, no markers
    left, index clean, commit succeeds) and the whole-suite regression gate still decides."""
    def resolve(workdir, conflicted):
        listing = "\n".join(f"- {p}" for p in conflicted[:40])
        prompt = (
            f"You are the MERGE-RESOLUTION phase of an autonomous coding loop. A git merge in "
            f"{workdir} stopped with CONFLICTS. Use your file tools (ABSOLUTE paths under "
            f"{workdir}) to resolve every conflict: read each conflicted file, understand BOTH "
            f"sides (<<<<<<< ours = this run's verified work; >>>>>>> theirs = the target "
            f"branch's newer commits), and write a single coherent version that preserves the "
            f"INTENT of both sides. Remove ALL conflict markers. Do NOT run any git command "
            f"(no add/commit/merge — the loop does that itself); do NOT write, edit, move, or "
            f"delete any test file.\nConflicted files:\n{listing}\nStop when every conflict "
            f"marker is gone.")
        _, code = _chat(prompt, coder, cwd=workdir, toolsets="file")
        return code in (0, None)
    return resolve


def merge_fixer_via_ask(coder=CODER):
    """ONE bounded LLM fix attempt when the SYNCED (combined) tree fails the whole-suite
    regression (user decision 2026-07-02: leverage the LLM to fix merge issues). Returns
    fix(workdir, why) -> bool. worktree restores any test-file edits afterwards and re-runs the
    regression gate — the gate decides, never this model's claim."""
    def fix(workdir, why):
        prompt = (
            f"You are the POST-MERGE FIX phase of an autonomous coding loop. Two verified change "
            f"sets were just merged in {workdir}, and the COMBINED tree now fails its test "
            f"suite — a semantic conflict between the two sides. Failing output:\n{str(why)[:1500]}\n"
            f"Use your file tools (ABSOLUTE paths under {workdir}) to fix the CODE so the whole "
            f"suite passes. You may run the suite with your terminal tool (python3 -m pytest -q) "
            f"to check your work. The tests are the ORACLE: do NOT write, edit, move, or delete "
            f"any test file — change the code. Stop when the suite passes.")
        _, code = _chat(prompt, coder, cwd=workdir, toolsets="file,terminal")
        return code in (0, None)
    return fix


def _repo_symbols(target_dir):
    """{module: [public top-level defs/classes]} for the repo's EXISTING .py files. The designer has
    no file tools, so on a MODIFY task it can't see where an existing function lives and invents a
    module (the spike bug: it imported `normalize` from a hallucinated `utils` instead of `textutil`).
    Feeding it the real module->symbol map fixes that. Top-level + one dir deep; skips tests/.venv/.git."""
    import ast
    out = {}
    if not os.path.isdir(target_dir):
        return out
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", ".devloop", "__pycache__")
                   and os.path.relpath(root, target_dir).count(os.sep) < 1]
        for f in files:
            if not f.endswith(".py") or f.startswith("test_") or f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(root, f), target_dir)
            mod = rel[:-3].replace(os.sep, ".")
            try:
                tree = ast.parse(open(os.path.join(root, f), encoding="utf-8").read())
            except Exception:   # noqa: BLE001 — a symbol hint is best-effort, never a failure path
                continue
            syms = [n.name for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and not n.name.startswith("_")]
            if syms:
                out[mod] = syms
    return out


def _existing_modules_hint(target_dir):
    """A one-line designer directive listing the real importable modules, or '' for a greenfield repo."""
    syms = _repo_symbols(target_dir)
    if not syms:
        return ""
    listing = "; ".join(f"{m} ({', '.join(s)})" for m, s in sorted(syms.items()))
    return ("\nEXISTING repo modules — for any criterion about an ALREADY-EXISTING function, import it "
            f"from its REAL module below; NEVER invent a module name: {listing}\n")


_DESIGN_SPEC_PROMPT = (
    "You are the TEST-DESIGN phase of an autonomous coding loop. For the DoD criteria below, output "
    "ONLY a JSON object (no prose, no markdown fence, no file edits) describing the tests:\n"
    '{ "schema_version": 1, "tests": [\n'
    '  { "criterion_id": "<criterion id>", "module": "<module to import, e.g. calc>", '
    '"call": "<the function to call, e.g. add>",\n'
    '    "cases": [ {"args": [..], "kwargs": {..}, "expected": <value>},\n'
    '               {"args": [..], "raises": "<BuiltinExceptionName>"},\n'
    '               {"args": [..], "expected": <float>, "approx": true} ] } ] }\n'
    "RULES:\n"
    "  - EXACTLY one entry per criterion id below. cases: >=1; each case is ONE call asserting "
    "EXACTLY ONE of `expected` (==) or `raises` (a built-in exception class name). Use approx:true "
    "for float equality. Use only values/literals — NEVER inline code or expressions in args/expected.\n"
    "  - For a criterion that args->expected/raises cannot express (stateful objects, custom "
    "exceptions, ordering/invariants, f(f(x)), cross-module 'A uses B'), use the ESCAPE HATCH: "
    '{ "criterion_id": "<id>", "oracle": "raw", "raw_test": "def test_<id>():\\n    from <mod> import '
    '<x>\\n    ..." } — EXACTLY one top-level function literally named test_<id>, importing the impl '
    "INSIDE the function (so it collects before the code exists).\n"
    "  - Do NOT invent behavior the criterion did not state. Do NOT write the implementation.\n"
    "  - RAW ESCAPE HATCH is REQUIRED (not optional) when: (a) any arg or expected value is NOT a "
    "JSON literal — datetime objects, Path objects, Decimal, custom classes, callables, or any "
    "non-serializable type; (b) the test must inspect what was PASSED to a dependency (call_args "
    "inspection) rather than just its return value; (c) the test must verify ordering, side effects, "
    "or state changes across multiple calls. In these cases, do NOT force a structured entry with "
    "string literals — use the raw escape hatch and write real pytest code with real imports.\n"
    "  - DEPENDENCY INJECTION PATTERN (for callable parameters): when the function under test "
    "accepts a callable as a PARAMETER (e.g. `def parse(input, get_now=None)`), mock.patch CANNOT "
    "target a parameter — it only patches module-level names. The test MUST use the raw escape "
    "hatch and pass a mock CALLABLE as the argument: `from unittest.mock import MagicMock; "
    "mock_get_now = MagicMock(return_value=datetime(2026,7,5,14,0)); result = parse('tomorrow', "
    "get_now=mock_get_now); assert result == ...; mock_get_now.assert_called_once()`. This is the "
    "ONLY way to verify what was passed to a callable dependency — structured mode cannot express "
    "it. Do NOT use mock.patch() for callable parameters; judges will reject it.\n"
    "  - CRITICAL: structured mode with 'mocks' ALWAYS renders as `with mock.patch(...)` — \n"
    "    this is REJECTED by the quality lint gate. If ANY criterion needs to mock a dependency, \n"
    "    you MUST use the RAW ESCAPE HATCH instead of structured mode with mocks. The raw escape \n"
    "    hatch lets you use dependency injection (passing a mock as a parameter) which is the \n"
    "    ONLY pattern the quality lint accepts. A structured entry with 'mocks': [...] will \n"
    "    ALWAYS be rejected — do NOT use it for any criterion that touches an external dependency. \n"
    "    For criteria that need NO mocks (pure logic: string parsing, URL building, data \n"
    "    transformation), structured mode is fine. For ANY criterion that calls subprocess, \n"
    "    urllib.request, os.environ, or any external module, use the RAW ESCAPE HATCH.\n"
    "  - For structured entries with mocks: prefer assert_called_with / assert_call_arg / "
    "assert_called_once over bare return_value when the criterion requires verifying WHAT was "
    "passed to the dependency. A mock that only sets return_value without inspecting call_args "
    "is a WEAK test — judges will reject it. Use: \"mocks\": [{\"target\": \"mod.dep\", "
    "\"return_value\": ..., \"assert_called_with\": [[arg1, arg2], {\"kw\": val}]}] or "
    "\"assert_call_arg\": [0, \"field\", expected_value] to inspect positional arg 0's field.\n"
    "  - NEGATIVE EXAMPLES — judges REJECT these patterns; DO NOT use them:\n"
    "      BAD:  with mock.patch('sys.stdout', new=io.StringIO()): main(); assert captured == '...'\n"
    "      GOOD: def test_cX(): from unittest.mock import MagicMock; fake_out = MagicMock(); main(stdout=fake_out); fake_out.write.assert_called_with('...')\n"
    "      BAD:  mock_now = Mock(return_value=datetime(2026,7,5,14,0)); with mock.patch('mod.now', mock_now): result = parse('tomorrow'); assert result == ...\n"
    "      GOOD: def test_cX(): from unittest.mock import MagicMock; mock_now = MagicMock(return_value=datetime(2026,7,5,14,0)); result = parse('tomorrow', get_now=mock_now); mock_now.assert_called_once(); assert result == ...\n"
    "      BAD:  assert result == 'datetime(2026,7,6)'\n"
    "      GOOD: from datetime import datetime; assert result == datetime(2026, 7, 6)\n"
    "  - When the function under test accepts a callable/dependency as a PARAMETER, structured mode CANNOT express this — you MUST use the raw escape hatch. mock.patch CANNOT verify what the function passes to that dependency.\n"
    "  - When the test must verify WHAT was passed to a mock (not just its return value), use the raw escape hatch and inspect `mock.call_args[0][0]` or `mock.assert_called_with(...)`.\n"
    "  - TIER discipline (each criterion below carries a tier): tier=unit isolates the NEW logic — "
    "if it touches an external boundary (network, filesystem, clock, other services), mock THAT "
    'boundary via "mocks": [{"target": "mod.dep", "return_value": ...}] so a failure can only mean '
    "the new logic is wrong; NEVER mock the function under test. tier=integration exercises the "
    "behavior through the repo's REAL public modules — no mocks in an integration entry.\n"
    "  - EXTERNAL-SYSTEM INTEGRATION TESTS (CRITICAL — this is the #1 source of false-COMPLETE runs):\n"
    "    When a criterion is tier=integration AND involves an external system (CLI tool, REST API, RPC\n"
    "    endpoint, command-line interface, existing repository service), the test MUST:\n"
    "      (a) invoke the REAL external binary via subprocess.run([...], capture_output=True, text=True)\n"
    "          or make a REAL HTTP request (requests.get/post/urllib) — NOT a mock, NOT a call to an\n"
    "          internal wrapper function, NOT a string comparison on a mocked call_args value;\n"
    "      (b) use a safe, read-only, or dry-run invocation: --dry-run, --help, --validate, --no-execute,\n"
    "          a GET request to a health/status endpoint, a --version flag, or similar harmless call.\n"
    "          Do NOT invent a flag the tool doesn't support — if you don't know the safe flag, use\n"
    "          --help or --version (almost all CLIs support these) and assert on the exit code / output;\n"
    "      (c) assert on the REAL response: exit code == 0, specific output pattern, JSON schema field,\n"
    "          HTTP status code, or response body content — NOT a substring 'in' check on a mocked\n"
    "          string (e.g. assert 'lunch' in mock_fn.call_args[0][0] is WEAK and will be REJECTED by\n"
    "          the quality lint and judges). Use subprocess.run and assert on result.returncode,\n"
    "          result.stdout, or result.stderr — the REAL values from the REAL binary.\n"
    "    Examples of external systems that REQUIRE real-binary integration tests:\n"
    "      - CLI tools: gws, gh, kubectl, aws, gcloud, docker, git, curl, hermes\n"
    "      - REST APIs: GitHub API, Slack API, Google Calendar API, OpenAI API, any HTTP endpoint\n"
    "      - Agent systems: Hermes agent, Claude Code, Cursor, Copilot CLI\n"
    "      - Database/storage: SQLite, PostgreSQL, Redis, S3, local filesystem\n"
    "      - Message/webhook: Slack webhooks, Discord webhooks, email APIs\n"
    "    A test that mocks the external runner and asserts 'expected_substring in mock.call_args[0][0]'\n"
    "    is a WEAK test — it passes even when the real command syntax is completely wrong (e.g.\n"
    "    'gws calendar events create --title' vs the correct 'gws calendar +insert --summary').\n"
    "    The quality lint WILL flag this pattern and the judges WILL reject it.\n"
    "    For integration criteria, use the RAW ESCAPE HATCH with subprocess.run against the real binary:\n"
    "      def test_cX():\n"
    "          import subprocess\n"
    "          result = subprocess.run(['gws', 'calendar', '+insert', '--help'],\n"
    "                                 capture_output=True, text=True)\n"
    "          assert result.returncode == 0\n"
    "          assert 'summary' in result.stdout.lower()  # +insert accepts --summary\n"
    "DoD criteria:\n")


def designer_spec_via_ask(target_dir, designer=DESIGNER):
    """STRUCTURED design (#17): ask the designer for a JSON test SPEC (NO file tools, so output style
    can't vary), WE render it to ONE canonical pytest shape (render.render_spec), and return the REAL
    collected map (testgen.collect_spec_map) — the same legitimacy pivot the free-form designer had, but
    coverage is derived from rendered node ids instead of parsed off free-form output."""
    def design(charter):
        crit = [{"id": c["id"], "criterion": c.get("criterion", ""),
                 "verify_intent": c.get("verify_intent", ""),
                 "tier": c.get("tier", "unit")} for c in charter["dod"]]
        prompt = _DESIGN_SPEC_PROMPT + json.dumps(crit, indent=2) + _existing_modules_hint(target_dir)
        # Feed user answers from a prior HUMAN_REVIEW round so the designer sees corrections
        # (e.g. "use real datetime objects not string literals"). Without this, the designer
        # repeats the same mistake that caused the prior test fault — the root cause of 5/5
        # calendar-quick-add failures.
        answers = charter.get("_answers", "")
        if answers:
            prompt += f"\nUSER ANSWERS (from a prior round — these override defaults):\n{answers}\n"
        out, _ = _chat(prompt, designer, toolsets="")
        # run_name = the worktree basename (<repo>/.worktrees/<run-name>): distinct runs render
        # distinct oracle files, so re-runs accumulate DoD protection and concurrent runs on one
        # repo never merge-conflict on a shared test file.
        planned = render.render_spec(_extract_json(out) or {}, target_dir,
                                     run_name=os.path.basename(os.path.realpath(target_dir)))
        return testgen.collect_spec_map(target_dir, planned)
    return design


def _is_yes(text):
    """Strict, fail-closed: True only if the answer clearly says YES and not NO."""
    yes = re.search(r"\byes\b", text or "", re.IGNORECASE)
    no = re.search(r"\bno\b", text or "", re.IGNORECASE)
    return bool(yes) and not no


def judge_via_ask(model, target_dir):
    """judge(criterion, test_ids) -> bool: do the criterion's tests, TAKEN TOGETHER, verify it?
    Concatenates the REAL node source (testgen.node_source) of every test so the judge sees exactly
    what was written, and asks `model`. We show the human-anchored `criterion` (the general
    statement) rather than the narrow `verify_intent` checklist, and tell the judge a suite may
    SPLIT a criterion across functions — judging each test alone against a compound criterion
    rejects every partial test (a real failure mode). Fail-closed: no source at all, or any
    non-clear-YES answer -> False."""
    def judge(criterion, test_ids):
        srcs = [s for s in (testgen.node_source(target_dir, tid) for tid in (test_ids or [])) if s]
        if not srcs:
            return False, "no test source found — tests may not have collected"
        prompt = (
            "You are an assertion JUDGE for an autonomous coding loop. Do the TESTS below, TAKEN "
            "TOGETHER, adequately verify the CRITERION? A good test suite may SPLIT a criterion "
            "across several focused functions — judge the WHOLE set, not each test alone, and "
            "answer YES if together they verify the criterion (NO if part of it is left untested). "
            "RECOMPUTE each asserted expected value from the CRITERION's plain semantics before "
            "answering (count the words, characters, elements yourself): a test that calls the "
            "right function but asserts a value the criterion's semantics do NOT produce is a "
            "WRONG test — answer NO. "
            "Reply on the FIRST line with one word only: YES or NO. "
            "If NO, on the SECOND line give a SHORT reason (one sentence) explaining what the "
            "test does wrong or what it fails to verify — this reason will be sent to the test "
            "designer so it can fix the test.\n"
            f"CRITERION: {criterion.get('criterion') or criterion.get('verify_intent', '')}\n"
            f"TESTS:\n{chr(10).join(srcs)}\n")
        # MAJORITY VOTE (spike fix): a single judge call is non-deterministic and can flip a trusted
        # test to untrusted across runs. Vote JUDGE_VOTES times and require a strict majority of clear
        # YES — fail-closed on a tie or any non-clear answer (a flaky NO no longer sinks a real test).
        votes_and_reasons = []
        for _ in range(config.JUDGE_VOTES):
            reply, _ = _chat(prompt, model, toolsets="")
            is_yes = _is_yes(reply)
            # Extract reason from second line if NO
            reason = ""
            if not is_yes:
                lines = (reply or "").strip().split("\n")
                if len(lines) > 1:
                    reason = lines[1].strip()[:300]
            votes_and_reasons.append((is_yes, reason))
        votes = [v for v, _ in votes_and_reasons]
        majority_yes = sum(votes) * 2 > len(votes)
        if majority_yes:
            return True, ""
        # Collect the most common rejection reason
        reasons = [r for _, r in votes_and_reasons if r]
        reason = reasons[0] if reasons else ""
        return False, reason
    return judge


def tiebreaker_via_ask(model=None, target_dir=None):
    """Tiebreaker judge (advisor review 2026-07-09): called ONLY when judge_a and judge_b
    disagree on a criterion. Same judge prompt as judge_via_ask (majority vote, fail-closed)
    but uses the TIEBREAKER model (default: deepseek-reasoner — different provider from both
    judge_a and judge_b). The tiebreaker function has the same signature as judge_via_ask so
    it can be passed directly to judge_assertions(tiebreaker=...)."""
    return judge_via_ask(model or TIEBREAKER, target_dir)


def test_auditor_via_ask(model, target_dir):
    """Judged mid-run TEST-REPAIR audit (user decision 2026-07-02):
    audit(criterion, test_ids, evidence_tail) -> bool, True = the TEST asserts the WRONG output
    for this criterion (a designer mistake the coder can never code past). Shown the criterion
    TEXT, the real test source, and the failing evidence. Fail-closed toward the oracle: no
    source or any non-clear-YES answer -> False. Majority vote like the assertion judge (a flaky
    YES must not indict a correct test)."""
    def audit(criterion, test_ids, evidence_tail):
        srcs = [s for s in (testgen.node_source(target_dir, tid) for tid in (test_ids or [])) if s]
        if not srcs:
            return False
        prompt = (
            "You are a TEST AUDITOR for an autonomous coding loop. The implementation has "
            "repeatedly FAILED the tests below, and the loop suspects the TESTS may assert the "
            "WRONG expected output for the criterion (a test-design mistake), rather than the "
            "code being at fault. Judge the TESTS strictly against the CRITERION text. Answer "
            "YES only if a test clearly asserts an expected value or behavior the CRITERION does "
            "not support; answer NO if the tests are a fair encoding (then the code is at "
            "fault). Reply with one word only: YES or NO.\n"
            f"CRITERION: {criterion.get('criterion') or criterion.get('verify_intent', '')}\n"
            f"TESTS:\n{chr(10).join(srcs)}\n"
            f"FAILING EVIDENCE (tail):\n{(evidence_tail or '')[:800]}\n")
        indict = [_is_yes(_chat(prompt, model, toolsets="")[0]) for _ in range(config.JUDGE_VOTES)]
        return sum(indict) * 2 > len(indict)
    return audit


def _impl_source_for_tests(target_dir, srcs, cap=8000):
    """The implementation source the tests exercise — non-test .py files whose module path the
    test source imports (junk-pruned, size-capped). What the green-side overfit auditor reads."""
    mods = set()
    for s in srcs:
        for m in re.finditer(r"(?:from|import)\s+([\w.]+)", s):
            dotted = m.group(1)
            mods.add(dotted)
            mods.add(dotted.split(".")[0])
    out = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [x for x in dirs if x not in worktree._JUNK_SEGMENTS]
        for f in sorted(files):
            if not f.endswith(".py") or f.startswith("test_") or f.endswith("_test.py"):
                continue
            rel = os.path.relpath(os.path.join(root, f), target_dir)
            parts = rel[:-3].replace(os.sep, ".").split(".")
            if any(".".join(parts[:i + 1]) in mods for i in range(len(parts))):
                try:
                    out.append(f"# {rel}\n" + open(os.path.join(root, f)).read())
                except OSError:
                    pass
    return "\n\n".join(out)[:cap]


def overfit_auditor_via_ask(model, target_dir):
    """GREEN-side overfit audit (user decision 2026-07-03, from the run-3 live specimen: a test
    asserted words=4/chars=19 where honest semantics give 3/18, and the coder special-cased the
    implementation to match). overfit(criterion, test_ids) -> bool, True = the test asserts
    values the criterion's semantics do not produce, OR the implementation contains logic that
    exists only to mirror the test's expectations. Sees the criterion, the REAL test source, and
    the implementation the tests exercise. Majority vote; fail-closed False (a flaky YES must
    not indict a clean run — only UNANIMOUS two-auditor indictment acts, enforced in loop.py)."""
    def overfit(criterion, test_ids):
        srcs = [s for s in (testgen.node_source(target_dir, tid) for tid in (test_ids or [])) if s]
        if not srcs:
            return False
        impl = _impl_source_for_tests(target_dir, srcs)
        prompt = (
            "You are an OVERFIT AUDITOR for an autonomous coding loop. Every test below currently "
            "PASSES. Your job is to catch a test-design mistake that was coded AROUND instead of "
            "fixed: RECOMPUTE each asserted expected value from the CRITERION's plain semantics "
            "(count the words/characters/elements yourself). Answer YES only if a test clearly "
            "asserts a value the criterion's semantics do NOT produce, or the IMPLEMENTATION "
            "contains special-case logic that exists only to mirror a test's expectations rather "
            "than the stated behavior. Answer NO if tests and implementation are an honest "
            "encoding of the criterion. Reply with one word only: YES or NO.\n"
            f"CRITERION: {criterion.get('criterion') or criterion.get('verify_intent', '')}\n"
            f"TESTS:\n{chr(10).join(srcs)}\n"
            f"IMPLEMENTATION:\n{impl}\n")
        votes = [_is_yes(_chat(prompt, model, toolsets="")[0]) for _ in range(config.JUDGE_VOTES)]
        return sum(votes) * 2 > len(votes)
    return overfit


def commit_scope_auditor_via_ask(model=None):
    """COMMIT-SCOPE audit (user ask 2026-07-03: only intended items reach the commit).
    scope(charter, path, head_of_content) -> "deliverable" | "scratch". Majority vote;
    fail-closed to "deliverable" on any unclear answer — over-inclusion is cosmetic, a wrong
    exclusion destroys work (loop.py additionally re-verifies the pruned tree and restores on
    red, and PROTECTED files never reach this auditor at all)."""
    model = model or JUDGE_A

    def scope(charter, path, head):
        crit = "\n".join(f"- {c.get('criterion', '')}" for c in charter.get("dod", []))
        prompt = (
            "You are a COMMIT-SCOPE auditor for an autonomous coding loop. The run is about to "
            "COMMIT its work into the target repository. Is the FILE below SCRATCH — a debug "
            "script, working notes, an experiment, or a temporary reproduction that is NOT part "
            "of the deliverable the Definition of Done describes? Deliverables include the "
            "implementation, its tests, and any file the DoD implies. Answer YES only if the "
            "file is CLEARLY scratch; when in doubt answer NO. Reply with one word only: "
            "YES or NO.\n"
            f"INTENT: {charter.get('interpreted_intent', '')}\nDoD:\n{crit}\n"
            f"FILE: {path}\nCONTENT (head):\n{head}\n")
        votes = [_is_yes(_chat(prompt, model, toolsets="")[0]) for _ in range(config.JUDGE_VOTES)]
        return "scratch" if sum(votes) * 2 > len(votes) else "deliverable"
    return scope


def assert_distinct_models(*models):
    """Raise if any non-empty model id repeats — no model may grade work it produced
    (coder / designer / the two judges must all differ)."""
    ids = [m for m in models if m]
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"devloop models must be distinct (no model grades its own work): {ids}")
