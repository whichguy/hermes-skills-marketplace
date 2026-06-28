# Council R4 — Kanban SDLC Skills Mapping Review (2026-06-26)

## Context

After R1-R3 produced the Kanban integration plan and SDLC script, the user asked for a council review of the skills-per-phase mapping in the SDLC chain. The question: are the right skills mapped to the right phases?

## Panel

| Seat | Model | Role | Toolsets |
|---|---|---|---|
| Reasoner | deepseek-v4-pro:cloud | Skeptical review — verify every skill claim | file, web |
| Coder | kimi-k2.7-code:cloud | Code-focused — read actual skill files, check fit | file, web |

**Dispatch:** Individual (separate delegate_task calls) — both reviewers got the full context: SDLC script, execution plan, kanban-orchestrator skill, kanban-worker skill, and all referenced skill definitions.

## Results

| Seat | Model | Time | Verdict | Confidence |
|---|---|---|---|---|
| DeepSeek | deepseek-v4-pro:cloud | 83s | APPROVE WITH CHANGES | MEDIUM |
| Kimi | kimi-k2.7-code:cloud | 114s | APPROVE WITH CHANGES | MEDIUM-HIGH |

**Consensus:** Both reviewers independently identified the same 3 critical skill mapping errors. Strong convergence — the issues were factual, not subjective.

## Critical Findings (Both Reviewers Agreed)

| # | Finding | Fix |
|---|---|---|
| 1 | T1 used `plan` skill — writes to `.hermes/plans/`, forbids project file edits | Changed to `spike` |
| 2 | T4 used `requesting-code-review` — pre-commit self-review, assumes `git diff --cached` | Changed to `multi-model-code-review` |
| 3 | T5 used `skill-testing-harness` — validates Hermes skills, not project test suites | Removed skill, test instructions in task body |

## Additional Findings

| # | Finding | Fix |
|---|---|---|
| 4 | No skill-conflict precedence rules | Added to kanban-worker SKILL.md |
| 5 | No file-based handoff contracts between phases | Added RESEARCH.md → TEST_PLAN.md → CHANGES.md → REVIEW.md → TEST_RESULTS.md |
| 6 | No pre-flight skill existence check | Added REQUIRED_SKILLS validation loop in script |
| 7 | notify-subscribe at end of script (race with dispatcher) | Moved to per-task immediate |
| 8 | Hardcoded Slack chat ID | Changed to KANBAN_SLACK_CHAT env var |
| 9 | Model diversity concern (plan text said same model for worker+reviewer) | Verified actual configs correct (Qwen worker, DeepSeek reviewer); plan text was stale |

## Kanban SDLC vs multi-model-dev-pipeline

Both reviewers independently recommended: **DO NOT MERGE.** Keep as separate, cross-referenced alternatives.

| Dimension | Kanban SDLC | multi-model-dev-pipeline |
|---|---|---|
| Best for | Multi-session projects with review gates | Fast single-session feature builds |
| Durability | Survives restarts (SQLite) | Lost if session ends |
| Human-in-loop | Native block/unblock | None |
| Audit trail | Full comment thread + state history | Summary only |

## Lessons

1. **Skill definitions must be read, not assumed.** All 3 critical errors came from assuming what a skill does based on its name. `plan` sounds like it does research — it actually writes plans to `.hermes/plans/` and forbids project edits. `requesting-code-review` sounds like it does code review — it's actually a pre-commit self-review. `skill-testing-harness` sounds like it runs tests — it validates Hermes skill packages. Always read the skill's SKILL.md before mapping it to a phase.

2. **Two reviewers with different lenses catch the same errors.** DeepSeek (skeptical/reasoning) and Kimi (code-focused) independently found the same 3 critical issues. This is the ideal council outcome — convergence on factual errors, not subjective disagreement.

3. **Skill precedence rules are necessary.** When a phase skill and the task body conflict (e.g., `plan` says "don't edit project files" but the task says "write RESEARCH.md"), the worker needs explicit precedence rules. Without them, the worker either follows the skill blindly (wrong deliverable) or ignores the skill (wrong method). The 3-tier rule (KANBAN_GUIDANCE > task body > phase skill) resolves this.

4. **File-based handoff contracts make SDLC chains debuggable.** Without explicit handoff files, each phase must re-discover what the previous phase did. With RESEARCH.md → TEST_PLAN.md → CHANGES.md → REVIEW.md → TEST_RESULTS.md, each phase has a single entry point and the orchestrator can verify chain integrity.

5. **Pre-flight validation prevents silent failures.** The script now checks that all required skills exist before creating any tasks. Without this, a typo in `--skill` would create tasks that workers can't execute — they'd sit in `ready` forever with no error.
