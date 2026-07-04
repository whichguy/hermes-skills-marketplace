#!/usr/bin/env python3
"""PostToolUse cleanup on ExitPlanMode.

After a plan successfully exits plan mode, remove the per-slug investigation
sentinels this gate created so the next plan-mode session starts fresh.
Companion to plan-unknowns-gate.py (the PreToolUse gate). Slug is derived
from tool_input.planFilePath, matching the gate.

Scoped to the investigation sentinels only. The `.review-ready-<slug>`
sentinel is owned by review-plan / the plugin's own ExitPlanMode cleanup
(which renames it to `.exited-<slug>` for idempotent re-exit) — deleting it
here would break that. Fails silently — cleanup must never disrupt anything.
"""

import json
import os
import sys

PLANS_DIR = os.environ.get("CLAUDE_PLANS_DIR") or os.path.expanduser("~/.claude/plans")
KINDS = (
    "needs-investigation",
    "investigated",
    "investigation-waived",
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
