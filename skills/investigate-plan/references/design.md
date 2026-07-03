# Investigate Plan adapter design

## Why this is an adapter

`investigate-plan` is a Claude Code plan-mode adapter, not a skill that runs inside the
Hermes container. Claude Code owns the active plan, separates repo-readable questions from
agentic unknowns, and folds the findings back into that plan before asking for approval.

Hermes supplies the autonomous `investigator` that can resolve the agentic unknowns. The
marketplace copy documents this contract and makes the adapter visible in the catalog; it
does not turn the adapter into a standalone container-side workflow.

## Host-to-container contract

1. Claude Code runs on the host in plan mode and builds one focused problem statement from
   the plan goal and its agentic open unknowns.
2. The host wrapper at
   `~/.claude/skills/investigate-plan/scripts/run_investigator.sh` reads that statement from
   stdin and base64-encodes it for safe transport.
3. The wrapper uses `docker exec` to invoke the installed `investigator` entrypoint inside
   the running `hermes` container.
4. The investigator researches from the container's reachable environment. Progress is
   emitted on stderr and the final result object returns as JSON on stdout.
5. Claude Code parses that JSON, incorporates answered facts into the plan, and leaves
   unresolved gaps visible for review.

The wrapper supplies a stable container-side `--run-dir` derived from the plan slug. The
investigator journals tombstones there, so repeating the same plan run resumes prior work
and skips questions already answered instead of re-researching them.

## Tombstone schema

Each per-question outcome in `.tombstones[]` has this shape:

```text
{
  question,
  status: ANSWERED | NOT_FOUND,
  fact,
  evidence,
  via
}
```

- `question` is the unknown the investigator attempted to resolve.
- `status: ANSWERED` means `fact` is the distilled discovered answer.
- `status: NOT_FOUND` means `fact` records the known gap or reason it could not be resolved.
- `evidence` records grounding for the outcome.
- `via` records the route used to produce it.

Claude Code curates these outcomes rather than pasting them verbatim. Answered facts become
plan constraints or decisions; not-found outcomes remain explicit residual risks.
