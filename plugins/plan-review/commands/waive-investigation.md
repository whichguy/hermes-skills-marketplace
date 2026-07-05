---
description: "Waive the plan-review investigation gate for the active plan (records a conscious skip)"
allowed-tools: "Bash"
---
The plan-review gate is blocking ExitPlanMode because this plan has open
unknowns tagged for active investigation (`[investigate]`) that were neither
investigated nor waived. The user is choosing to proceed WITHOUT running
`/investigate-plan`.

Record the waiver so the gate allows the exit:

1. Identify the active plan slug. It is the basename (without `.md`) of the plan
   file named in the plan-mode system message. If unsure, list candidates with
   `ls -t ~/.claude/plans/*.md | head -3` and confirm the intended one with the
   user before proceeding — waiving the wrong plan silently defeats the gate.

2. Write the waiver sentinel (replace `<slug>`):

   ```bash
   touch ~/.claude/plans/.investigation-waived-<slug>
   ```

3. Briefly restate to the user which unknowns are being left un-investigated (so
   the skip is a visible decision, not a silent one), then call ExitPlanMode
   again. The PostToolUse cleanup removes the sentinel after a successful exit.
