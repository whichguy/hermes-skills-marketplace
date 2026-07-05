#!/usr/bin/env python3
"""PreToolUse advisory/hard gate for git-worktree isolation on ExitPlanMode.

Plans that warrant implementation in an isolated git worktree should document
how the worktree is created, seeded, used, merged, and cleaned up. The gate is
advisory by default and hard only when CLAUDE_PLAN_WORKTREE_REQUIRE=1. Every
failure path fails open so the gate can never brick planning.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CODEX_TIMEOUT_S = 150  # keep below the hook timeout in hooks.json (180)
MAX_SECTION_CHARS = 8000  # cap on Codex output embedded in a message/reason
PLANS_DIR = os.environ.get("CLAUDE_PLANS_DIR") or os.path.expanduser("~/.claude/plans")
INVESTIGATE_TAG = "[investigate]"

# Markdown heading line: up to 3 spaces indent, 1-6 hashes, then a space.
HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*)$")
BULLET_RE = re.compile(r"^[ \t]*([-*+]|[0-9]+[.)])[ \t]+")
# Codex output heading may omit the space after the hashes; be lenient here
# and normalize to the canonical form before it reaches the plan.
SECTION_HEAD_RE = re.compile(
    r"^[ \t]{0,3}#{1,6}[ \t]*git\s+isolation\s+strategy\b",
    re.IGNORECASE | re.MULTILINE,
)
FENCE_RE = re.compile(r"^[ \t]{0,3}(```|~~~)")

CODEX_PROMPT = """You are reviewing an implementation plan written by another AI agent, to decide whether it needs an explicit git-worktree ISOLATION strategy.

First decide: will executing this plan MUTATE files (create/modify code, config, or scripts)? If the plan is read-only, investigation/research-only, docs-only, or a trivial single-file edit, output exactly one line and nothing else:
WORKTREE: not-needed — <brief reason>

Otherwise, decide if it genuinely warrants worktree isolation. It DOES when any hold: the plan spawns parallel or multi-agent work that would collide in one checkout; it must preserve the user's dirty working tree (uncommitted AND untracked files) while doing risky isolated work; it is a long-running/risky change the user's checkout should be shielded from; or it has multiple independent write streams. It does NOT when a single sequential edit in the current checkout is fine, or when isolation is already handled by the execution harness. If not warranted, output: WORKTREE: not-needed — <brief reason>

If warranted, output ONLY a markdown section in exactly this shape (no preamble, no code fences, nothing after it), tailored to THIS plan, at most 6 bullets:

## Git Isolation Strategy

- **Create worktree** — prefer the harness `EnterWorktree` (or `git worktree add .claude/worktrees/<name> -b <branch>` from the base ref); a worktree is seeded from a ref, not from the dirty tree.
- **Seed uncommitted + untracked changes** — the non-trivial step: `git diff HEAD` piped through `git -C <wt> apply`, and separately carry UNTRACKED files (`git ls-files --others --exclude-standard`, or `git stash push -u` then apply) because worktree/stash skip untracked by default.
- **Do the work** in the worktree so the user's checkout stays untouched.
- **Merge back** — from the original branch `git merge --no-ff <worktree-branch>` (or open a PR / cherry-pick), resolving conflicts.
- **Clean up** — `git worktree remove <wt>` and `git branch -d <worktree-branch>` (prefer `ExitWorktree`).

Keep each bullet concrete and specific to the plan. Output the section OR the single not-needed line — never both.

The plan to review follows:

"""

FALLBACK_REASON = """Codex could not assess whether this plan needs git-worktree isolation. Before presenting it, append a section titled exactly '## Git Isolation Strategy' that covers: creating the worktree (defer to EnterWorktree where the harness provides it); seeding uncommitted and untracked changes, with explicit handling for untracked files; doing the work in the worktree; merging back to the branch; and cleaning up the worktree and branch (defer to ExitWorktree where provided). Then call ExitPlanMode again."""

NEEDED_REASON_TEMPLATE = """Codex (cross-model reviewer) judged this plan needs an explicit git-worktree isolation strategy. Do NOT just paste this in — adapt it to the plan, defer worktree create/cleanup to EnterWorktree/ExitWorktree where the harness already provides them, and make sure untracked-file seeding is addressed. Then append the section (keep the exact heading '## Git Isolation Strategy') and call ExitPlanMode again:

{section}"""


def allow(message=None):
    if message:
        print(json.dumps({"systemMessage": message}))
    sys.exit(0)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def has_isolation_heading(text):
    """True if a real (non-fenced-code) heading names an isolation strategy."""
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m and re.search(
                r"git isolation|isolation strategy|worktree strategy",
                m.group(2), re.IGNORECASE):
            return True
    return False


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


def plan_hash(plan):
    return hashlib.sha256(plan.encode("utf-8")).hexdigest()[:16]


def read_assessment(slug, plan):
    """Return a matching cached (verdict, section), or None on a cache miss."""
    if slug is None:
        return None
    try:
        with open(sentinel_path("worktree-assessed", slug), encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeError):
        return None
    if len(lines) < 2 or lines[0] != plan_hash(plan):
        return None
    verdict = lines[1]
    section = "\n".join(lines[2:]) or None
    if verdict != "needed":
        section = None
    return (verdict, section)


def in_worktree(cwd):
    marker = os.sep + ".claude" + os.sep + "worktrees" + os.sep
    if marker in os.path.realpath(cwd):
        return True
    try:
        git_dir = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=5,
        )
        common_dir = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        )
        if git_dir.returncode != 0 or common_dir.returncode != 0:
            return False

        def resolved(value):
            value = value.strip()
            if not os.path.isabs(value):
                value = os.path.join(cwd, value)
            return os.path.realpath(value)

        return resolved(git_dir.stdout) != resolved(common_dir.stdout)
    except (OSError, subprocess.SubprocessError):
        return False


def extract_section(text):
    """Pull and normalize a non-empty Git Isolation Strategy section."""
    m = SECTION_HEAD_RE.search(text)
    if not m:
        return None
    tail = text[m.end():]
    # Drop the rest of the matched heading line, keep everything after it.
    body = tail.split("\n", 1)[1] if "\n" in tail else ""
    section = "## Git Isolation Strategy\n" + body.rstrip()
    if not body.strip():
        return None
    if len(section) > MAX_SECTION_CHARS:
        section = section[:MAX_SECTION_CHARS] + "\n- ... (truncated)"
    return section


def run_codex(plan, cwd):
    """Return ('failed'|'not-needed'|'needed', section-or-None).

    The explicit status keeps a successful not-needed verdict distinct from
    failure, which matters when hard enforcement is enabled.
    """
    codex = shutil.which("codex")
    if not codex:
        return "failed", None
    outfile = None
    try:
        fd, outfile = tempfile.mkstemp(prefix="plan-worktree-", suffix=".md")
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
            return "failed", None
        with open(outfile, encoding="utf-8", errors="replace") as f:
            section = extract_section(f.read())
        if section:
            return "needed", section
        return "not-needed", None
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return "failed", None
    finally:
        if outfile:
            try:
                os.unlink(outfile)
            except OSError:
                pass


def main():
    if os.environ.get("CLAUDE_PLAN_WORKTREE_GATE", "1") == "0":
        allow()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or payload.get("tool_name") != "ExitPlanMode":
        allow()

    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    plan = get_plan_text(tool_input)
    if not plan.strip():
        allow()  # nothing to assess — fail open

    slug = plan_slug(tool_input)

    if has_isolation_heading(plan):
        allow()

    if os.environ.get("CLAUDE_PLAN_UNKNOWNS_GATE", "1") != "0" \
            and not has_unknowns_heading(plan):
        allow()

    # The unknowns gate will deny unresolved investigation, so defer this
    # assessment until the plan is mature enough to proceed.
    if os.environ.get("CLAUDE_PLAN_UNKNOWNS_GATE", "1") != "0" and slug is not None:
        if (sentinel_exists("needs-investigation", slug) or has_investigate_tag(plan)) \
                and not sentinel_exists("investigated", slug) \
                and not sentinel_exists("investigation-waived", slug):
            allow()

    cwd = payload.get("cwd")
    if not (isinstance(cwd, str) and os.path.isdir(cwd)):
        cwd = os.getcwd()

    if in_worktree(cwd):
        allow()

    require = os.environ.get("CLAUDE_PLAN_WORKTREE_REQUIRE", "0") == "1"
    cached = read_assessment(slug, plan)
    if cached is not None:
        verdict, section = cached
    else:
        verdict, section = run_codex(plan, cwd)
        if verdict != "failed" and slug is not None:
            write_sentinel(
                "worktree-assessed", slug,
                "%s\n%s\n%s" % (plan_hash(plan), verdict, section or ""),
            )
    if verdict == "failed":
        if require:
            deny(FALLBACK_REASON)
        allow()
    if verdict == "not-needed":
        allow()

    if require:
        deny(NEEDED_REASON_TEMPLATE.format(section=section))
    allow(section + "\n\nSet CLAUDE_PLAN_WORKTREE_REQUIRE=1 to enforce.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fail open: the gate must never brick planning.
        sys.exit(0)
