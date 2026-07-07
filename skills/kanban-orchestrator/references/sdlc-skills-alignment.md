# SDLC Skills Alignment — Kanban + Skills Integration

## The `--skill` Flag

`hermes kanban create` accepts `--skill <name>` (repeatable). Each skill is force-loaded into the worker's system prompt alongside the auto-injected `KANBAN_GUIDANCE`. This bridges procedural knowledge (skills) with execution context (Kanban).

## Standard SDLC Phase → Skill Mapping (R5-verified)

| Phase | `--skill` flag(s) | What the worker gains |
|---|---|---|
| T1 Research | `--skill spike` | Structured research/experimentation with VALIDATED/PARTIAL/INVALIDATED verdict |
| T2 Write tests | `--skill test-driven-development` | RED-GREEN-REFACTOR discipline, test-first enforcement |
| T3 Implement | `--skill test-driven-development --skill systematic-debugging` | GREEN phase + 4-phase debugging if tests fail |
| T4 Review | `--skill multi-model-code-review` | Independent cross-agent review protocol (NOT requesting-code-review, which is a pre-commit self-review) |
| T5 Final test | No skill — test instructions in task body | `skill-testing-harness` is for validating Hermes skills, not project test suites |

### R4 Corrections (from council review round 4)

- T1: Changed from `plan` to `spike` — `plan` writes to `.hermes/plans/` and forbids project file edits, conflicting with producing RESEARCH.md
- T4: Changed from `requesting-code-review` to `multi-model-code-review` — the former is a pre-commit self-review skill that assumes `git diff --cached` and the reviewer wrote the code
- T5: Removed `skill-testing-harness` — it validates Hermes skills (frontmatter, scripts, tests under `skills/<name>/tests/`), not project test suites

### R5 Additions (from council review round 5)

- **`--idempotency-key`** on T1 prevents duplicate chains on script rerun (derived from project+goal hash)
- **`--board <slug>`** support for multi-project isolation (optional 3rd arg or `HERMES_KANBAN_BOARD` env var)
- **Status name is `running`** not `in_progress` — verified via `hermes kanban list --help`
- **Deprecated daemon warning** — do NOT run `hermes kanban daemon` while `dispatch_in_gateway` is enabled
- **`hermes kanban reassign --reclaim`** for switching profiles mid-run when a worker keeps crashing
- **Fix 6 CLOSED** — `--skill` multi-load verified by live test (T3 used 2 skills successfully)

## Three Layers of Knowledge Per Worker

1. **Kanban lifecycle** (auto-injected KANBAN_GUIDANCE) — how to use kanban_show, kanban_complete, kanban_block
2. **Phase skill** (via `--skill`) — how to do TDD, how to review code, how to debug
3. **Project context** (via AGENTS.md in `dir:` workspace) — project-specific invariants and standards

## Skill Precedence When Conflicts Arise

1. **KANBAN_GUIDANCE wins on lifecycle** — when to complete/block/heartbeat
2. **Task body wins on deliverables** — what to produce, where to put it
3. **Phase skill wins on technical method** — how to TDD, how to debug, how to review

## Reusable Script

`${HERMES_HOME}/scripts/kanban-sdlc.sh` — creates a full 5-phase SDLC chain with skills auto-injected per phase. Usage:

```bash
${HERMES_HOME}/scripts/kanban-sdlc.sh /opt/data/projects/<name> "goal description" [board_slug]
```

The script:
- Creates T1-T5 with parent-child dependencies
- Injects the correct `--skill` flag(s) per phase
- Uses shared `dir:` workspace so each phase can read prior output
- Subscribes Slack notifications for all tasks
- Uses `--idempotency-key` on T1 to prevent duplicates
- Supports `--board <slug>` for multi-project isolation
- Prints the full task graph with IDs

## Why This Matters

Without `--skill`, a worker gets only the task body and KANBAN_GUIDANCE. It must figure out HOW to do TDD, how to review code, or how to debug from scratch — inconsistent across runs. With `--skill`, the worker follows a proven process every time.

## Discovery Notes

- 2026-06-26: The `--skill` flag was verified via `hermes kanban create --help` — it's a built-in feature, not a workaround
- 2026-06-26: No existing skills referenced Kanban in their SKILL.md (grep confirmed zero matches)
- 2026-06-26: Worker and reviewer profiles both inherit 17 skill categories from default
- 2026-06-26: The `kanban-worker` skill is auto-loaded for every dispatched worker; `kanban-orchestrator` is loaded on demand
- 2026-06-27: Live test confirmed `--skill` multi-load works (T3 loaded TDD + systematic-debugging)
- 2026-06-27: R5 council verified `--idempotency-key`, `--board`, status names, and `reassign --reclaim` against latest docs
