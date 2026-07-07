# Token Efficiency Review — 2026-07-05

Cross-skill review of 7 autonomous-ai-agents skills for SWE best practices,
token efficiency, and reuse.

## Finding: `advisors/SKILL.md` is the heaviest skill in the category

| Skill | Size | Token Load |
|---|---|---|
| advisors | 54 KB (1268 lines) | **High** — many inline Python code snippets |
| method-explorer | 43 KB | Medium-high |
| relentless-solve | 31 KB | Medium |
| next-best-questions | 19 KB | Medium |
| investigator | 17 KB | Low-medium |
| delegate-progress-protocol | 27 KB | Medium |
| task-decomposer | 9 KB | **Gold standard** — lean, schema-owning |

## Recommendation

Extract inline Python examples from `advisors/SKILL.md` into `scripts/` files
and reference them with short code blocks instead of full listings. The
`task-decomposer` skill (9 KB) demonstrates the target shape: focused prose
with schema definitions, no redundant examples.

## Broader Pattern for Skill Authors

- **SKILL.md**: prose, triggers, steps, pitfalls, schema — keep under ~15 KB
- **`scripts/`**: re-runnable code the agent invokes directly
- **`references/`**: session-specific detail, error transcripts, domain notes
- **`templates/`**: starter files meant to be copied and modified

## Other Cross-Cutting Findings

1. **No shared error taxonomy** across skills. Each skill defines its own exit
   codes and failure semantics. Consider a common `ERROR_CODES.md` reference.
2. **Overlap between relentless-solve / task-decomposer / method-explorer is
   intentional** — they serve distinct execution modes (orchestrator, stateless
   planner, self-contained backtracking search). Do not consolidate.
3. **`delegate-progress-protocol`** could benefit from extracting the polling
   loop algorithm into a separate `references/polling-pattern.md`.
