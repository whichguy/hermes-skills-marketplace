---
name: investigate-plan
title: Investigate Plan — Claude Code adapter
description: >-
  Use from Claude Code plan mode when the user invokes "/investigate-plan", asks to
  "investigate this plan", "research the plan's unknowns", or "resolve the open
  unknowns before I approve". This Claude Code plan-mode companion to the
  plan-unknowns-gate hook drives the Hermes investigator skill to research agentic
  unknowns, fold resolved facts into the plan, and return it for approval.
version: 1.0.0
author: agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    category: autonomous-ai-agents
    tags: [planning, claude-code, investigator, adapter, plan-mode]
    related_skills: [investigator, next-best-questions]
    config:
      - key: investigate-plan.k
        description: Top-K questions to research per round (passed through to the investigator)
        default: 4
        prompt: How many questions should the investigator research per round?
      - key: investigate-plan.max_rounds
        description: Max investigate-then-re-rank rounds before responding
        default: 2
        prompt: Max investigation rounds?
      - key: investigate-plan.capability
        description: Investigator capability — act (full agency) | experiment (reversible) | read (read-only)
        default: act
        prompt: Default capability level for the investigator?
      - key: investigate-plan.floor
        description: Minimum EVSI value to bother researching a question
        default: 0.12
        prompt: Value-of-information floor?
---

# Investigate Plan — Claude Code adapter

> ⚠️ **Claude-Code adapter** — this skill is invoked by Claude Code (plan mode) and drives
> the container-side `investigator` skill; it is NOT runnable from inside the hermes runtime.
> Requires a running `hermes` container + Claude Code.

Turn a plan's **Open Unknowns** from disclaimers into resolved facts. This is the
user-invoked companion to the `plan-unknowns-gate` ExitPlanMode hook: the gate
*identifies* unknowns; this skill *resolves* the researchable ones with the Hermes
**investigator** (autonomous, agentic "go find out") and improves the plan in place.

Run it while still in plan mode, before the user approves the plan.

## When to use / not use

- **Use** for unknowns that need *active investigation*: verifying live/runtime behavior,
  running a reversible experiment, probing a reachable service, or checking something that
  cannot be settled by reading the repo.
- **Do NOT hand off** unknowns you can resolve by reading the repo or docs. Resolve those
  directly in plan mode; only *agentic* unknowns go to the investigator.
- The investigator runs **inside the `hermes` container** and researches from there. It cannot
  see host-only files that are not reachable from the container, so keep repo-reading unknowns
  on the host with Claude Code.

## Procedure

### 1. Load the plan

Read the active plan: the plan file under `~/.claude/plans/<name>.md` named in the plan system
message, or the plan text from the conversation. Locate its `## Open Unknowns` section if present.

### 2. Triage the unknowns

Split the unknowns into two buckets:

- **Repo-readable** → resolve now in plan mode by reading code and verifying APIs or schemas.
  Do not send these to the investigator.
- **Agentic / go-find-out** → the investigator bucket. If there are none, say so and stop;
  do not invoke the investigator for a plan with no researchable unknowns.

### 3. Build the problem text

Compose a single problem string: a short statement of the plan's goal, then the **agentic
unknowns emphasized as the questions to resolve**. The investigator generates its own questions
from this text, so surfacing the target unknowns biases it toward the plan's actual gaps. Keep it
focused on the agentic bucket.

### 4. Run the investigator

Pipe the problem text to the host-side wrapper. It handles container execution, base64 transport,
the resumable run directory, and JSON parsing:

```bash
printf '%s' "$PROBLEM_TEXT" \
  | ~/.claude/skills/investigate-plan/scripts/run_investigator.sh --slug <plan-slug>
```

The literal `~/.claude/skills/investigate-plan/scripts/run_investigator.sh` path is intentional:
Claude Code invokes the real wrapper from the **host**. The script bundled in this marketplace
copy is for catalog visibility and source inspection; do not invoke it through
`${HERMES_SKILL_DIR}` or imply that Hermes runs this adapter as a container skill.

- Use the plan's basename as `--slug` so re-running resumes the same `--run-dir` via its durable
  `tombstones.jsonl`; already-answered questions are skipped.
- Tunables map to the declared config defaults: `INV_K=4`, `INV_MAX_ROUNDS=2`,
  `INV_CAPABILITY=act` (`experiment` for reversible experiments or `read` for read-only), and
  `INV_FLOOR=0.12`.
- Expect this to take minutes: it is K questions × rounds × agent researches. Progress streams
  to stderr; the final result object is JSON on stdout.
- If the wrapper prints `{"error": ...}` because the container is down or the entrypoint is
  missing, degrade gracefully: report that the investigator is unavailable, resolve what can be
  resolved directly, and leave remaining unknowns as residual risk. Do not block.

### 5. Read the resolved facts

Parse the JSON. The key field is `.tombstones[]`, whose entries have this shape:
`{question, status: "ANSWERED"|"NOT_FOUND", fact, evidence, via}`.
`ANSWERED` means the investigator found an answer and `fact` is the distilled finding;
`NOT_FOUND` means a genuine gap and `fact` is the gap reason. Also inspect `.n_answered`,
`.n_gaps`, `.next_questions`, and `.stop_reason`.

### 6. Fold findings into the plan

Edit the plan file:

- For each **ANSWERED** fact, weave the finding into the relevant plan step, make the decision
  it enables, and remove that item from `## Open Unknowns`.
- Leave **NOT_FOUND** items in `## Open Unknowns` as honest residual risks annotated with what
  was tried.
- Curate the findings. Cite the fact, not the machinery; do not paste raw tombstones.

### 7. Return to plan mode

Summarize what was resolved and what remains, then return the improved plan for approval. Call
`ExitPlanMode` again when appropriate, or hand it back for review. Do not auto-approve.

## Notes

- Fidelity caveat: the investigator re-derives its own questions from the problem text rather
  than answering exact bullets one-for-one. Step 3 therefore emphasizes the target unknowns.
- This adapter never approves a plan and never fires automatically; it runs only when invoked.
  Discoverability at plan-review time is provided, opt-in, by the `plan-unknowns-gate` hook when
  `CLAUDE_PLAN_INVESTIGATE=1`.
- See [references/design.md](references/design.md) for the host-to-container contract and
  tombstone schema.

## Dependency

Depends on the Hermes **investigator** skill (`autonomous-ai-agents/investigator`) being installed
inside the container. The install commands below prepare the container-side dependency and make
this adapter visible in the catalog. `investigate-plan` remains a host-side Claude Code skill: its
marketplace SKILL.md is documentation/catalog content consumed by Claude Code, not an executable
Hermes runtime skill.

**Hub install (dependency order matters — the categories pin the resolution paths):**
```bash
hermes skills install whichguy/hermes-skills-marketplace/skills/investigator --category autonomous-ai-agents
hermes skills install whichguy/hermes-skills-marketplace/skills/investigate-plan --category autonomous-ai-agents
```

## Verification

- Offline and stubbed wrapper suite:
  `bash ~/.claude/skills/investigate-plan/tests/run_investigator.test.sh`
- All original suites:
  `bash ~/.claude/skills/investigate-plan/tests/run.sh [live]`
- This marketplace copy intentionally omits `tests/` per marketplace convention; run verification
  from the original host-side Claude Code skill path above.
