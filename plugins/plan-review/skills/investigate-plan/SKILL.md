---
name: investigate-plan
description: >-
  Research a plan's OPEN, agentic unknowns with the Hermes investigator skill and fold
  the resolved facts back into the plan — then return to plan mode for approval. Invoke
  during plan review (in plan mode, before approving an ExitPlanMode plan) when the plan
  has unknowns that need active go-find-out research (verify live behavior, run a
  reversible experiment, probe a reachable system) rather than just reading the repo.
  Triggers: "/investigate-plan", "investigate this plan", "research the plan's unknowns",
  "resolve the open unknowns before I approve".
---

# investigate-plan

Turn a plan's **Open Unknowns** from disclaimers into resolved facts. This is the
user-invoked companion to the `plan-unknowns-gate` ExitPlanMode hook: the gate
*identifies* unknowns; this skill *resolves* the researchable ones with the Hermes
**investigator** (autonomous, agentic "go find out") and improves the plan in place.

Run it while still in plan mode, before the user approves the plan.

## When to use / not use

- **Use** for unknowns that need *active investigation*: verifying live/runtime behavior,
  running a reversible experiment, probing a reachable service, checking something that
  can't be settled by reading the repo.
- **Do NOT hand off** unknowns you can resolve yourself by reading the repo or docs —
  resolve those directly in plan mode (that is the existing gate's job). Only *agentic*
  unknowns go to the investigator.
- The investigator runs **inside the `hermes` container** and researches from *there*.
  It cannot see host-only files that aren't reachable from the container, so keep
  repo-reading unknowns on the host with you.

## Procedure

### 1. Load the plan
Read the active plan: the plan file under `~/.claude/plans/<name>.md` (named in the plan
system message), or the plan text from the conversation. Locate its `## Open Unknowns`
section if present.

### 2. Triage the unknowns
Split the unknowns into two buckets:
- **Repo-readable** → resolve now, yourself, in plan mode (read code, verify APIs/schemas,
  make the decision). Do not send these to the investigator.
- **Agentic / go-find-out** → the investigator bucket. If there are none, say so and stop —
  do not invoke the investigator for a plan with no researchable unknowns.

### 3. Build the problem text
Compose a single problem string: a short statement of the plan's goal, then the
**agentic unknowns emphasized as the questions to resolve** (the investigator generates
its own questions from this text, so surfacing the target unknowns biases it toward them).
Keep it focused on the agentic bucket.

### 4. Run the investigator
Pipe the problem text to the wrapper (it handles container exec, base64 transport,
run-dir, and JSON parsing):

```bash
printf '%s' "$PROBLEM_TEXT" \
  | ~/.claude/skills/investigate-plan/scripts/run_investigator.sh --slug <plan-slug>
```

- Use the plan's basename as `--slug` so re-running **resumes** the same `--run-dir`
  (durable `tombstones.jsonl`; already-answered questions are skipped) instead of
  re-researching. A long run can be safely re-invoked to continue.
- Tunables via env (defaults are conservative): `INV_K=4`, `INV_MAX_ROUNDS=2`,
  `INV_CAPABILITY=act` (use `experiment` only for reversible experiments, `read` for
  read-only), `INV_FLOOR=0.12`.
- Expect this to take **minutes** — it is K questions × rounds × agent researches.
  Progress streams to stderr; the final result dict is JSON on stdout.
- If the wrapper prints `{"error": ...}` (container down, entrypoint missing), degrade
  gracefully: tell the user the investigator is unavailable and resolve what you can
  yourself, or leave the unknowns as residual risk. Do not block.

### 5. Read the resolved facts
Parse the JSON. The key field is `.tombstones[]`, each:
`{question, status: "ANSWERED"|"NOT_FOUND", fact, evidence, via}`.
`ANSWERED` = the investigator found the answer (`fact` is the distilled finding);
`NOT_FOUND` = a genuine gap (`fact` is the gap reason). Also useful: `.n_answered`,
`.n_gaps`, `.next_questions`, `.stop_reason`.

Also read `.unresolved_key_questions` — a list of
`{question, value, stakes, gap_reason}` for the high-value questions the investigator
could **not** substantiate. These are a distinct, higher-severity category from an
ordinary `NOT_FOUND` tombstone: the investigator judged them important enough to call
out by name rather than let them pass as a routine gap.

### 6. Fold findings into the plan
Edit the plan file:
- **ANSWERED** → weave the finding into the relevant plan step (make the decision the
  fact now enables), and **remove** that item from `## Open Unknowns`.
- **Key unresolved question** (present in `.unresolved_key_questions`) → do NOT fold a
  silent assumption into the plan body. Keep it in `## Open Unknowns` as a **flagged
  material risk**, formatted like:
  `⚠️ **<the question>** — unresolved by investigation. Proceeding on assumption:
  <the assumption>. Why it matters: <stakes/impact>. Confirm before relying on it.`
  This honors the `plan-unknowns-gate` creed "plan the unknowns, don't disclaim them" —
  a high-stakes unknown becomes a visible decision for the user, not a buried assumption.
- **Ordinary NOT_FOUND** (not in the key list) → leave in `## Open Unknowns` as honest
  residual risk, annotated with what was tried.
- Curate — don't paste raw tombstones. Cite the fact, not the machinery.

This makes key gaps visible to the user at plan review — non-blocking (the plan still
proceeds), but the risk is surfaced rather than silently assumed.

### 7. Return to plan mode
Summarize what was resolved vs what remains, then let the user approve the improved plan
(call `ExitPlanMode` again, or hand back for their review). Do not auto-approve.

## Notes
- Fidelity caveat: the investigator re-derives its own questions from the problem text
  rather than answering your exact bullets one-for-one — that's why step 3 emphasizes the
  target unknowns in the problem string.
- This skill never approves a plan and never fires automatically; it runs only when you
  invoke it. Discoverability at plan-review time is provided (opt-in) by the
  `plan-unknowns-gate` hook when `CLAUDE_PLAN_INVESTIGATE=1`.

## Verification

Run the offline and stubbed wrapper suite alone:

```bash
bash ~/.claude/skills/investigate-plan/tests/run_investigator.test.sh
```

Run all related suites, optionally including the live Docker tier:

```bash
bash ~/.claude/skills/investigate-plan/tests/run.sh
bash ~/.claude/skills/investigate-plan/tests/run.sh live
```

Run the hook suite directly:

```bash
bash ~/.claude/hooks/plan-unknowns-gate.test.sh
```
