#!/usr/bin/env python3
"""PreToolUse plan-review gate on ExitPlanMode.

A plan cannot be presented for approval until three stages pass, in order,
each failing OPEN so the gate can never brick planning:

  Stage 1 — quality review. If review-plan wrote its `.review-ready-<slug>`
    sentinel, good. Missing → a soft nudge (default) or a hard deny when
    CLAUDE_PLAN_REQUIRE_REVIEW=1.

  Stage 2 — unknowns audit. If the plan lacks an '## Open Unknowns' heading,
    the plan is sent to the OpenAI Codex CLI (read-only sandbox) for a
    cross-model unknowns review. Codex tags bullets needing active
    go-find-out research with `[investigate]`. If any are tagged, a
    `.needs-investigation-<slug>` sentinel is written; the tool call is
    denied with Codex's findings. The point is to PLAN the unknowns, not
    disclaim them: resolve each one during planning where possible (or add a
    concrete resolution step), and only then record what remains under the
    heading and retry.

  Stage 3 — investigation (closed loop). Once the heading exists, if the plan
    has agentic unknowns (the sentinel from Stage 2, or `[investigate]`
    markers in the plan text) that were neither investigated nor waived, the
    exit is denied until `/investigate-plan` runs (which drops
    `.investigated-<slug>`) or the user waives via `/waive-investigation`.
    If the hermes container is down, investigation is impossible, so this
    stage fails open.

Opt out of the whole gate with CLAUDE_PLAN_UNKNOWNS_GATE=0.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CODEX_TIMEOUT_S = 150  # keep below the hook timeout in settings.json (180)
MAX_SECTION_CHARS = 8000  # cap on Codex output embedded in the deny reason
PLANS_DIR = os.environ.get("CLAUDE_PLANS_DIR") or os.path.expanduser("~/.claude/plans")
HERMES_CONTAINER = os.environ.get("INV_CONTAINER", "hermes")
INVESTIGATE_TAG = "[investigate]"

# Markdown heading line: up to 3 spaces indent, 1-6 hashes, then a space.
HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*)$")
BULLET_RE = re.compile(r"^[ \t]*([-*+]|[0-9]+[.)])[ \t]+")
# Codex output heading may omit the space after the hashes; be lenient here
# and normalize to the canonical form before it reaches the plan.
SECTION_HEAD_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*open\s+unknowns\b", re.IGNORECASE | re.MULTILINE)
FENCE_RE = re.compile(r"^[ \t]{0,3}(```|~~~)")

CODEX_PROMPT = """You are reviewing an implementation plan written by another AI agent. \
Your job is to surface the unknowns the plan silently relies on: assumptions stated \
without evidence, APIs/schemas/behaviors referenced but never verified, unexplored \
failure modes, and decisions the plan never actually makes. Only list things that were \
NOT already investigated, discussed, or resolved in the plan text itself. You may \
briefly inspect the repository in your working directory (read-only) to check the \
plan's claims, but keep it quick.

Output ONLY a markdown section in exactly this shape, with no preamble, no code fences, \
and nothing after it:

## Open Unknowns

- **<the unknown>** — why it matters / what breaks if guessed wrong. *Resolve:* <the concrete step that closes it — what to inspect, verify, or decide, and where in the plan that step belongs (before implementation, during step N, as a verification gate, or as a question for the user)>.

If closing an unknown requires active go-find-out research — verifying live/runtime \
behavior, running a reversible experiment, or probing a reachable running system, rather \
than reading the repo or docs — append ` [investigate]` to the END of that bullet. Leave \
bullets that are resolvable by reading the repo/docs untagged. Only tag when you are \
confident active investigation is genuinely required.

One bullet per unknown, most important first, at most 6 bullets. Every bullet must be \
resolvable — name the action that would close it, not just the risk. If the plan genuinely \
resolved everything material, output the section with the single line: \
None — all material unknowns were investigated.

The plan to review follows:

"""

FALLBACK_REASON = """Before this plan can be presented, its unknowns must be planned, not \
just listed. Re-read the plan and identify the unknowns it relies on that were NOT \
actually investigated or discussed during planning (unverified assumptions, APIs/schemas \
never checked, unexplored failure modes, decisions never made). Then, for each one: \
(a) if you can resolve it NOW, do the investigation in plan mode — read the code, verify \
the API/schema, make the decision — and fold the answer into the plan body; \
(b) otherwise add a concrete resolution step at the right point in the plan (spike, \
default + verification gate, question for the user). If closing an unknown needs active \
go-find-out research (verify live behavior, run an experiment, probe a running system), \
mark that bullet with ` [investigate]` and plan to run /investigate-plan for it. Finally \
append a section titled exactly '## Open Unknowns' recording only what remains open and, \
for each item, how the plan now handles it. If there are genuinely none, write \
'None — all material unknowns were investigated.' under the heading. \
Then call ExitPlanMode again."""

CODEX_REASON_TEMPLATE = """Codex (cross-model reviewer) analyzed this plan and identified \
unknowns that were not resolved during planning. Do NOT just paste this list into the \
plan. For each item below: (a) if you can resolve it NOW, do the investigation in plan \
mode — read the code, verify the API/schema, make the decision — and fold the answer \
into the plan body; (b) otherwise add a concrete resolution step at the right point in \
the plan (spike, default + verification gate, question for the user). Items tagged \
`[investigate]` need active go-find-out research — plan to run /investigate-plan for \
those (the repo-readable ones you resolve yourself). Then append a '## Open Unknowns' \
section (keep that exact heading) recording only what remains open and how the plan now \
handles each item — drop items you can show are already settled — and call ExitPlanMode \
again:

{section}"""

INVESTIGATION_REQUIRED_REASON = """This plan has open unknowns tagged for active \
investigation ([investigate]) — go-find-out research that reading the repo can't settle \
(live/runtime behavior, a reversible experiment, probing a running system). Resolve them \
before presenting the plan:

- Run `/investigate-plan` — it researches the agentic unknowns with the Hermes \
investigator and folds the resolved facts back into the plan.
- Or, if you have consciously decided to proceed without investigating, run \
`/waive-investigation` to record that choice.

Then call ExitPlanMode again."""

INVESTIGATION_MENU_REASON = """Do NOT resolve this plan's unknowns silently and do NOT \
approve the plan yet. This plan has unknowns that need active go-find-out investigation. \
FIRST call the AskUserQuestion tool with one question — "This plan has unknowns that need \
active investigation. How do you want to proceed?" — and exactly these three options: \
(1) "Investigate now" — run the /investigate-plan skill (the Hermes investigator resolves \
the agentic unknowns and folds the findings into the plan); (2) "Waive investigation" — \
run /waive-investigation to record a conscious decision to proceed without investigating; \
(3) "I'll revise the plan" — go back and edit the plan yourself. Then act on the user's \
selection. Do not call ExitPlanMode again until the user has chosen."""

REVIEW_REQUIRED_REASON = """CLAUDE_PLAN_REQUIRE_REVIEW is set, but review-plan has not \
recorded a completed quality review for this plan (no `.review-ready-<slug>` sentinel). \
Run the review-plan quality review, then call ExitPlanMode again."""

REVIEW_NUDGE = (
    "\U0001f4a1 Optional: this plan has no completed review-plan quality review "
    "(`.review-ready-<slug>` sentinel absent). Consider running review-plan before "
    "approving. (Set CLAUDE_PLAN_REQUIRE_REVIEW=1 to make this a hard gate.)"
)


# Opt-in (CLAUDE_PLAN_INVESTIGATE=1, off by default and independent of the
# unknowns gate): surface the /investigate-plan skill at the plan-review moment
# so the user can research the plan's open unknowns before approving. This never
# blocks approval — it only advertises the option.
INVESTIGATE_ADVISORY = (
    "\n\n\U0001f4a1 Optional: run `/investigate-plan` to research this plan's open "
    "unknowns with the Hermes investigator before approving — it resolves the "
    "researchable ones and folds the findings into the plan."
)


def investigate_enabled():
    return os.environ.get("CLAUDE_PLAN_INVESTIGATE", "0") == "1"


def allow(message=None):
    # Optionally surface a non-blocking systemMessage (soft review nudge and/or
    # the investigate advisory). Absent a permissionDecision the call proceeds
    # (allow). With no message this stays a bare exit 0 — identical to before.
    msgs = []
    if message:
        msgs.append(message)
    if investigate_enabled():
        msgs.append(INVESTIGATE_ADVISORY.strip())
    if msgs:
        print(json.dumps({"systemMessage": "\n\n".join(msgs)}))
    sys.exit(0)


def deny(reason, advisory=True):
    if advisory and investigate_enabled():
        reason = reason + INVESTIGATE_ADVISORY
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def has_unknowns_heading(text):
    """True if a real (non-fenced-code) markdown heading mentions 'unknowns'."""
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m and re.search(r"\bunknowns\b", m.group(2), re.IGNORECASE):
            return True
    return False


def has_investigate_tag(text):
    """True if a non-fenced markdown bullet ends with '[investigate]'."""
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if BULLET_RE.match(line) and line.rstrip().endswith(INVESTIGATE_TAG):
            return True
    return False


def plan_slug(tool_input):
    """Plan basename without .md, matching the investigator's --slug. None if absent."""
    path = tool_input.get("planFilePath")
    if isinstance(path, str) and path:
        base = os.path.basename(path)
        if base.endswith(".md"):
            base = base[:-3]
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "-", base)[:64]
        return sanitized or "plan"
    return None


def sentinel_path(kind, slug):
    return os.path.join(PLANS_DIR, ".%s-%s" % (kind, slug))


def sentinel_exists(kind, slug):
    return slug is not None and os.path.exists(sentinel_path(kind, slug))


def write_sentinel(kind, slug, content=""):
    if slug is None:
        return
    try:
        os.makedirs(PLANS_DIR, exist_ok=True)
        with open(sentinel_path(kind, slug), "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass


def container_running(name=HERMES_CONTAINER):
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        proc = subprocess.run(
            [docker, "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, timeout=5,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def get_plan_text(tool_input):
    plan = tool_input.get("plan")
    if isinstance(plan, str) and plan.strip():
        return plan
    path = tool_input.get("planFilePath")
    if isinstance(path, str) and path:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except (OSError, UnicodeError):
            pass
    return ""


def extract_section(text):
    """Pull the Open Unknowns section out of Codex output, normalizing its
    heading to the canonical '## Open Unknowns' so the appended plan always
    satisfies has_unknowns_heading(). Returns None if absent/empty."""
    m = SECTION_HEAD_RE.search(text)
    if not m:
        return None
    tail = text[m.end():]
    # Drop the rest of the matched heading line, keep everything after it.
    body = tail.split("\n", 1)[1] if "\n" in tail else ""
    section = "## Open Unknowns\n" + body.rstrip()
    if not body.strip():
        return None
    if len(section) > MAX_SECTION_CHARS:
        section = section[:MAX_SECTION_CHARS] + "\n- ... (truncated)"
    return section


def run_codex(plan, cwd):
    """Return Codex's '## Open Unknowns' section, or None on any failure."""
    codex = shutil.which("codex")
    if not codex:
        return None
    outfile = None
    try:
        fd, outfile = tempfile.mkstemp(prefix="plan-unknowns-", suffix=".md")
        os.close(fd)
        cmd = [
            codex, "exec",
            "--sandbox", "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C", cwd,
            "-o", outfile,
            "--color", "never",
            "-",
        ]
        proc = subprocess.run(
            cmd,
            input=CODEX_PROMPT + plan,
            capture_output=True,
            text=True,
            timeout=CODEX_TIMEOUT_S,
        )
        if proc.returncode != 0:
            return None
        with open(outfile, encoding="utf-8", errors="replace") as f:
            return extract_section(f.read())
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None
    finally:
        if outfile:
            try:
                os.unlink(outfile)
            except OSError:
                pass


def main():
    if os.environ.get("CLAUDE_PLAN_UNKNOWNS_GATE", "1") == "0":
        allow()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or payload.get("tool_name") != "ExitPlanMode":
        allow()

    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    plan = get_plan_text(tool_input)
    if not plan.strip():
        allow()  # nothing to audit — fail open

    slug = plan_slug(tool_input)
    cwd = payload.get("cwd")
    if not (isinstance(cwd, str) and os.path.isdir(cwd)):
        cwd = os.getcwd()

    # Stage 1 — quality review. Hard only when explicitly required; else a soft
    # nudge on the allow path (can't distinguish "review skipped legitimately"
    # from "not yet run", so default must never block).
    require_review = os.environ.get("CLAUDE_PLAN_REQUIRE_REVIEW", "0") == "1"
    review_missing = slug is not None and not sentinel_exists("review-ready", slug)
    if require_review and review_missing:
        deny(REVIEW_REQUIRED_REASON)

    # Stage 2 — unknowns audit. Runs once, when the heading is still absent.
    if not has_unknowns_heading(plan):
        section = run_codex(plan, cwd)
        if section:
            if has_investigate_tag(section):
                write_sentinel("needs-investigation", slug, section)
            deny(CODEX_REASON_TEMPLATE.format(section=section))
        deny(FALLBACK_REASON)

    # Stage 3 — investigation of agentic unknowns (heading present, retry path).
    # Triggered by the Stage-2 sentinel OR by [investigate] markers the agent
    # wrote directly. Needs a slug to track investigated/waived state; without
    # one we can't manage the loop, so fail open.
    if slug is not None:
        needs = sentinel_exists("needs-investigation", slug) or has_investigate_tag(plan)
        if needs and not sentinel_exists("investigated", slug) \
                and not sentinel_exists("investigation-waived", slug):
            if container_running():
                if investigate_enabled():
                    deny(INVESTIGATION_MENU_REASON, advisory=False)
                deny(INVESTIGATION_REQUIRED_REASON)
            # container down → investigation impossible → fall through (allow)

    allow(REVIEW_NUDGE if (review_missing and not require_review) else None)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fail open: the gate must never brick planning.
        sys.exit(0)
