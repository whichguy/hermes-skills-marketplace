#!/usr/bin/env python3
"""PostToolUse cleanup on ExitPlanMode.

After a plan successfully exits plan mode, remove the per-slug investigation
and worktree-assessment sentinels so the next plan-mode session starts fresh.
Companion to the plan review PreToolUse gates. Slug is derived from
tool_input.planFilePath, matching the gates.

Scoped to the investigation and worktree sentinels listed in KINDS, and
nothing else. The `.review-ready-<slug>` sentinel this used to work around
was retired 2026-07-26 together with exit-plan-mode-cleanup.sh, which owned
it — nothing writes or reads it now, so there is no longer anything to avoid
here. Fails silently — cleanup must never disrupt anything.
"""

import json
import os
import re
import sys

PLANS_DIR = os.environ.get("CLAUDE_PLANS_DIR") or os.path.expanduser("~/.claude/plans")
KINDS = (
    "needs-investigation",
    "investigated",
    "investigation-waived",
    "worktree-assessed",
)


def main():
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or payload.get("tool_name") != "ExitPlanMode":
        return
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    path = tool_input.get("planFilePath")
    if not (isinstance(path, str) and path):
        return
    base = os.path.basename(path)
    if base.endswith(".md"):
        base = base[:-3]
    if not base:
        return
    base = re.sub(r"[^A-Za-z0-9._-]", "-", base)[:64] or "plan"
    for kind in KINDS:
        try:
            os.remove(os.path.join(PLANS_DIR, ".%s-%s" % (kind, base)))
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
