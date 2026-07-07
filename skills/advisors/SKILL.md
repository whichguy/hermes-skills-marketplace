---
name: advisors
description: >
  Prompt any Hermes model via `hermes chat -q` and write the output to a file.
  Single primitive (prompt-model) that composes into larger patterns:
  multi-model consensus (advisors), iterative refinement, A/B comparison,
  sequential review chains. Each call is a full Hermes agent with tools,
  skills, and multi-turn reasoning. No delegate_task, no gateway-restart risk.
version: 3.4.0
author: agent
metadata:
  hermes:
    tags: [multi-model, consensus, ensemble, reasoning, parallel, primitive]
    related_skills: [multi-model-dev-pipeline, multi-model-code-review, subagent-driven-development]
    config:
    - key: advisors.enabled
      description: Enable the advisors skill
      default: true
      prompt: Enable advisors skill?
    category: autonomous-ai-agents
---

# Advisors — Prompt Any Model, Compose Patterns

## Overview

One primitive — **prompt-model** — prompts a Hermes model via `hermes chat -q`
and writes the output to a file. Each call is a full agent with tools, skills,
and multi-turn reasoning. The controller orchestrates this primitive into
whatever pattern the task needs.

```
prompt-model:  prompt + model → file on disk

advisors:     N× prompt-model in parallel → read files → synthesize
adversarial:  advisors + hostile-auditor meta-review round (opt-in, high-stakes)
deliberation: parallel → consolidate → parallel adversarial → final synthesis
iterative:    advisors applied across plan versions (broad → targeted → features)
review-chain: prompt-model A → read → prompt-model B → read → prompt-model C
A/B:          same prompt, two models → diff the output files
```

**Why this architecture:** `delegate_task` cannot select different models per
subagent — all inherit `delegation.model` from config.yaml. Running `hermes
chat -q` as a subprocess gives per-call model selection. Output goes to a file
you can read, diff, archive, or feed into the next call.

## Data Channel Architecture (v3.4+)

**Principle: Separate the data channel from the controller's context window.**

The controller's running conversation should carry short prompts and file paths
— never the full data payload. Review data (5-15K chars per seat) is write-once,
read-once: it enters context only through the synthesis model reading from disk,
never through the controller reading raw review files.

```
WRONG (context pollution):
  Controller reads design.md (50K) → passes via --context "$(cat design.md)"
  → 50K chars now in controller context, never useful again after dispatch

RIGHT (file-referenced):
  Controller writes brief → /tmp/advisors/brief.md (on disk)
  Controller dispatches: "Read /tmp/advisors/brief.md and review X" -t file
  → Advisor reads file from disk → data never enters controller context
  → Only synthesis.md (~1-2K chars) enters controller context
```

### dispatch_advisors.py — the file-referenced dispatch helper

```
/opt/data/skills/autonomous-ai-agents/advisors/scripts/dispatch_advisors.py
```

Encapsulates the file-reference pattern. Controller writes the brief (question +
all context) to disk, dispatches seats that read the brief from disk, then
dispatches GLM synthesis that reads seat outputs from disk. The controller's
context only carries the question string and file paths.

**CLI (all-in-one):**
```bash
python3 dispatch_advisors.py run \
    --question "Should we use PostgreSQL or MongoDB? ACID required, ~100K rows." \
    --context-file /opt/data/wiki/design.md \
    --outdir /tmp/advisors \
    --toolsets file,web
```

**Python import (from execute_code — preferred for programmatic control):**
```python
import sys
sys.path.insert(0, '/opt/data/skills/autonomous-ai-agents/advisors/scripts')
from dispatch_advisors import AdvisorDispatch

ad = AdvisorDispatch(outdir='/tmp/advisors')
ad.prepare_brief(
    question="Should we use PostgreSQL or MongoDB? ACID required, ~100K rows.",
    context_file="/opt/data/wiki/design.md",
)
ad.dispatch()  # 3 seats, parallel, each reads brief from disk
ad.synthesize()  # GLM reads seat files from disk → synthesis.md
print(ad.read_synthesis())  # ~1-2K chars into controller context
```

**Testing:** Run `python3 tests/test_dispatch_advisors.py` from the skill
directory. 43 tests cover parse_seats, prepare_brief, dispatch validation,
synthesis, CLI, path resolution, auto-subdir isolation, whitespace-only
parse_seats fallback, and empty seats guard. Always run tests
after modifying `dispatch_advisors.py` — the tests catch regressions even
though they didn't catch the original 10 bugs the advisor panel found.

**Step-by-step CLI (controller wants granular control):**
```bash
# 1. Write brief to disk
python3 dispatch_advisors.py prepare \
    --question "..." --context-file design.md --outdir /tmp/advisors

# 2. Dispatch seats (each reads brief from disk)
python3 dispatch_advisors.py dispatch \
    --brief /tmp/advisors/brief.md --outdir /tmp/advisors

# 3. Synthesize (GLM reads seat files from disk)
python3 dispatch_advisors.py synthesize \
    --brief /tmp/advisors/brief.md --outdir /tmp/advisors
```

### When to use dispatch_advisors.py vs raw prompt_model.py

**Default: `dispatch_advisors.py`.** Use `prompt_model.py` directly only for
Pattern 4 (single model query) with context < 2K chars. Everything else —
panels, synthesis, multi-step chains, any context > 2K — goes through
`dispatch_advisors.py` to keep data out of the controller's transcript.

| Use dispatch_advisors.py (default) | Use raw prompt_model.py (exception) |
|---|---|
| Multi-seat panels (Pattern 1, 5, 6) | Single model query (Pattern 4) with < 2K context |
| Any context > 2K chars | Quick one-shot lookups with tiny inline context |
| Code review with source files | A/B comparison (you want diff control) |
| Any synthesis step | — |
| Sequential review chains | — |

## The Primitive: prompt-model

### Location

```
/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py
```

### Usage

```bash
# Basic — output to stdout
python3 prompt_model.py -m deepseek-v4-pro:cloud -p "What is ACID compliance?"

# Write to file
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review this architecture" \
    --context "$(cat design.md)" \
    -o /tmp/seat-1.md

# With tools and skills
python3 prompt_model.py -m kimi-k2.7-code:cloud \
    -p "Find security issues in auth.py" \
    -t file,web,terminal \
    -s github-code-review \
    -o /tmp/review-kimi.md

# Pipe context via stdin
cat design.md | python3 prompt_model.py -m glm-5.2:cloud \
    -p "Review this design" -o /tmp/review-glm.md
```

### Arguments

| Flag | Required | Description |
|---|---|---|
| `-m` / `--model` | Yes | Model name (e.g., `deepseek-v4-pro:cloud`) |
| `-p` / `--prompt` | Yes | The prompt text |
| `--context` | No | Context appended after prompt |
| `-c` / `--context-file` | No | Read context from file (overrides `--context`) |
| `-o` / `--output` | No | Output file path (default: stdout) |
| `-t` / `--toolsets` | No | Comma-separated toolsets (e.g., `file,web,terminal`) |
| `-s` / `--skills` | No | Comma-separated skills to preload |
| `--provider` | No | Provider name (default: `ollama-glm`) |
| `--max-turns` | No | Max agent turns (default: Hermes config `agent.max_turns`) |
| `--timeout` | No | Timeout in seconds (default: 300) |
| `--english-only` | No | Force English output (auto-added for known non-English models) |

### Output

- **With `-o`:** Response written to file. Progress printed to stderr:
  `✅ deepseek-v4-pro:cloud → /tmp/seat-1.md (6.7s, 2341 chars)`
- **Without `-o`:** Response printed to stdout.
- **Exit codes:** 0 = success, 1 = error, 2 = timeout.

### Non-English models

The script auto-appends "respond in English only" for known non-English models
(`glm-5.2:cloud`, `glm-5.2`). Use `--english-only` to force it for other models.

## Pattern Index

| Pattern | When to use | Details |
|---|---|---|
| Pattern 1: Advisors | Multi-model consensus for architecture, design, risk, trade-offs | [references/patterns.md#pattern-1](references/patterns.md#pattern-1) |
| Pattern 2: Sequential Review Chain | Cumulative expertise where later reviewers build on earlier findings | [references/patterns.md#pattern-2](references/patterns.md#pattern-2) |
| Pattern 3: A/B Comparison | Compare two models on the same prompt, diff outputs | [references/patterns.md#pattern-3](references/patterns.md#pattern-3) |
| Pattern 4: Single Model Query | One model is enough; no panel needed | [references/patterns.md#pattern-4](references/patterns.md#pattern-4) |
| Pattern 5: Adversarial Meta-Review | High-stakes, irreversible, or known LLM blind spots (opt-in) | [references/patterns.md#pattern-5](references/patterns.md#pattern-5) |
| Pattern 6: 4-Round Deliberation | Design docs, architecture decisions, multi-version plans | [references/patterns.md#pattern-6](references/patterns.md#pattern-6) |
| Pattern 7: Iterative Plan Refinement | Plans evolving through versions (broad → targeted → features) | [references/patterns.md#pattern-7](references/patterns.md#pattern-7) |
| Pattern 8: Advisors as Fixers | Apply patches, not just recommendations | [references/patterns.md#pattern-8](references/patterns.md#pattern-8) |
| Pattern 9: Plan → Review → Implement | User's preferred 3-phase workflow + quality review | [references/patterns.md#pattern-9](references/patterns.md#pattern-9) |

## Pitfall Categories Index

| Category | Pitfalls |
|---|---|
| Token efficiency | [Keep SKILL.md lean — extract code to scripts/](references/pitfalls.md#token-efficiency) |
| Output quality | [Logical-level output](references/pitfalls.md#output-quality), [verify findings](references/pitfalls.md#output-quality), [panel size rules](references/pitfalls.md#output-quality), [consensus model bias](references/pitfalls.md#output-quality), [DeepSeek API drops](references/pitfalls.md#output-quality) |
| Configuration | [Config deference](references/pitfalls.md#configuration-and-defaults), [stale imports](references/pitfalls.md#configuration-and-defaults), [token limits](references/pitfalls.md#execution-environment), [seat timeout](references/pitfalls.md#execution-environment) |
| Context / data channel | [Separate data channel](references/pitfalls.md#context-and-data-channel), [context threshold](references/pitfalls.md#context-and-data-channel), [file-reading toolsets](references/pitfalls.md#context-and-data-channel), [timeout on too many files](references/pitfalls.md#context-and-data-channel), [complete context files](references/pitfalls.md#context-and-data-channel), [special chars in prompts](references/pitfalls.md#context-and-data-channel), [ARG_MAX](references/pitfalls.md#context-and-data-channel), [context sources are additive](references/pitfalls.md#context-and-data-channel) |
| Execution environment | [execute_code interruption](references/pitfalls.md#execution-environment), [5-minute timeout](references/pitfalls.md#execution-environment), [sandbox persistence](references/pitfalls.md#execution-environment), [local models in loops](references/pitfalls.md#execution-environment), [gateway restarts](references/pitfalls.md#execution-environment), [stderr session ID](references/pitfalls.md#execution-environment), [concurrent limits](references/pitfalls.md#execution-environment) |
| Script-specific | [CLI subcommands](references/pitfalls.md#script-specific-behaviors), [parse_seats pipe syntax](references/pitfalls.md#script-specific-behaviors), [whitespace-only seats](references/pitfalls.md#script-specific-behaviors), [as_completed order](references/pitfalls.md#script-specific-behaviors), [seats.json manifest](references/pitfalls.md#script-specific-behaviors), [cwd-independent imports](references/pitfalls.md#script-specific-behaviors), [prepare_brief signature](references/pitfalls.md#script-specific-behaviors) |
| Synthesis | [Use foreground subprocess.run for synthesis](references/pitfalls.md#synthesis-and-workflow) |
| Meta-patterns | [Eat your own dogfood](references/pitfalls.md#meta-patterns) |
| Non-English models | [Auto English for glm-5.2:cloud](references/pitfalls.md#non-english-models) |

## Decision Table: File-Reference vs Inline Context

**Default: file-reference.** Inline is the exception, not a peer option.

| Context size | Approach | Rationale |
|---|---|---|
| < 2K chars | Inline `--context` (only for Pattern 4 single queries) | Overhead of file I/O > transcript cost |
| 2K–5K chars | File-reference (`-c` or `dispatch_advisors.py`) | Transcript pollution starts; not worth the risk |
| 5K–50K chars | File-reference + `dispatch_advisors.py` | Transcript pollution dominates |
| > 50K chars | File-reference + `-t file` (model reads from disk) | Cumulative cost over session is prohibitive |

**Rule of thumb:** File-reference for everything except single-seat Pattern 4
queries under 2K. The "2K either way" band was removed — it created ambiguity
that let inline creep into multi-seat panels. The real cost is cumulative
transcript pollution, not context-window pressure.

### Size guard: this skill practices what it preaches

This SKILL.md was 85KB before the v3.4.x refactor — the heaviest skill in the
directory. It grew because each pattern was documented with inline code blocks
that accumulated in the controller's context on every skill load. The refactor
extracted bulk content to `references/*.md`, loaded on demand via
`skill_view(file_path=...)`.

**Maintenance rule:** If SKILL.md exceeds 20KB, extract bulk content to
`references/`. The lightweight index (this file) should stay under 20KB.
Reference files are the data channel; SKILL.md is the context.

## Quick Reference

Compact cheatsheet below. Full version: [references/quick-reference.md](references/quick-reference.md).

```
# ── dispatch_advisors.py (DEFAULT — use for everything except Pattern 4 < 2K)
python3 dispatch_advisors.py run -q "question" --context-file data.md --outdir /tmp/advisors

from dispatch_advisors import AdvisorDispatch
ad = AdvisorDispatch(outdir='/tmp/advisors')
ad.prepare_brief(question="...", context_file="data.md", verify_preamble=True)
ad.dispatch(seats=[("deepseek-v4-pro:cloud", "Reasoner"), ("kimi-k2.7-code:cloud", "Coder")])
ad.synthesize()
print(ad.read_synthesis())  # ~1-2K chars into context

# ── prompt_model.py (exception — Pattern 4 single queries with < 2K context only)
python3 prompt_model.py -m <model> -p <prompt> [--context "< 2K"] -o <file>

# Patterns 1-9: see Pattern Index above and references/quick-reference.md
```

## References

- `scripts/dispatch_advisors.py` — File-referenced dispatch helper (v3.4+). Writes brief to disk, dispatches seats that read from disk, synthesizes via GLM reading from disk.
- `scripts/prompt_model.py` — The primitive: single-model query with per-call model selection.
- `tests/test_dispatch_advisors.py` — 43 persistent tests. Run with `python3 tests/test_dispatch_advisors.py` from the skill directory.
- `references/patterns.md` — Full text of all 9 patterns with complete code blocks, real-run examples, and step-by-step processes.
- `references/pitfalls.md` — Consolidated anti-patterns organized by category.
- `references/quick-reference.md` — Full quick-reference cheatsheet for all patterns.
- `references/targeted-verification-pattern.md` — Targeted single-model verification after a panel review.
- `references/self-review-dispatch-advisors-2026-07-05.md` — Self-review of v3.4 dispatch_advisors.py; found 10 confirmed bugs.
- `references/deepseek-plan-review-2026-07-05.md` — DeepSeek review of the v3.4 fix plan; corrected 5K threshold rationale.
- `references/real-run-orchestrator-plan-review-2026-06-28.md` — 3-round deliberation-like example.
- `references/real-run-v6-state-machine-design-2026-06-28.md` — Pattern 7 iterative refinement in action.
- `references/real-run-adversarial-meta-review-2026-06-28.md` — Pattern 5 adversarial review on SQLite vs DuckDB.
- `references/adversarial-self-review-2026-06-28.md` — Live test of Pattern 5 reviewing itself.
- `references/advisors-as-fixers-2026-07-05.md` — Pattern 8 full pattern and real-run example.
- `references/plan-review-implement-devloop-2026-07-05.md` — Pattern 9 real run.
- `references/token-efficiency-review-2026-07-05.md` — Cross-skill review that motivated this refactor.
- `references/real-run-usaw-event-info-review-2026-07-06.md` — Pattern 1+8: advisor review of usaw-event-info skill, 28 findings, batch-fixed 7 S-effort items.
- `references/` — Additional real-run logs and historical notes.

## Consumers

### ask
`ask` (`skills/productivity/ask/`) is the interactive wrapper — the user says
"ask deepseek What is ACID?" and gets an inline reply with a model badge. It
uses `hermes chat -q` directly (same mechanism as `prompt_model.py`) but adds
alias resolution, session memory, comparison mode, and conversational UX. Use
`ask` for interactive use; use `prompt_model.py` for programmatic orchestration.

### sdlc.py council_review()
`sdlc.py` (`skills/productivity/ask/scripts/sdlc.py`) uses the advisors pattern
for its `council_review()` phase. It dispatches the same review prompt to 3
models in parallel (DeepSeek + Kimi + GLM, all thinking=high) via
`dispatch_single()`, then merges their responses with per-seat headers. The
`COUNCIL_PANEL` constant defines the 3-seat panel. This replaced the old
single-model (DeepSeek-only) council in P11 (Jun 2026).

### dev
`dev` (`skills/software-development/dev/`) wraps `prompt_model.py` with role
aliases (planner → GLM, coder → Qwen, qa-tester → Qwen, code-debugger → Kimi)
and a pipeline mode. It's the primary consumer of this primitive for software
development work. Use `dev` when you need role-based development; use
`prompt_model.py` directly when you need custom model selection or patterns
not covered by `dev`.

### multi-model-dev-pipeline

> ⚠️ **DEPRECATED — do not use for new work.**
> That skill uses `delegate_task` with `model=` (which doesn't work — all
> subagents inherit `delegation.model` from config.yaml). This skill uses
> `prompt_model.py` instead, which actually selects different models per call.
>
> **Migration:** Use `dev.py pipeline` for full dev pipelines, or compose
> `prompt_model.py` calls manually for custom workflows.

## What Changed

### v2 → v3

| Dimension | v2 (advisors.py) | v3 (prompt_model.py + patterns) |
|---|---|---|
| Script | 414-line monolith | 150-line primitive |
| Synthesis | Coded in Python | Controller/model synthesis |
| Output | JSON (ephemeral) | Files (inspectable, diffable, archivable) |
| Patterns | Council only | 9 documented patterns |
| Composability | No | Yes — primitive + controller orchestration |

### v3.3 → v3.4

| Dimension | v3.3 | v3.4 |
|---|---|---|
| Data channel | Context inline via `--context` | Brief on disk, seats read via `-t file` |
| Controller context | Carries full data payload | Carries only prompts + file paths |
| Dispatch helper | Manual `concurrent.futures` boilerplate | `AdvisorDispatch` class |
| Synthesis | Manual prompt construction | `ad.synthesize()` one call |

### v3.4.0 → v3.4.x (this refactor)

| Dimension | Before | After |
|---|---|---|
| SKILL.md size | ~85 KB | ~8-12 KB lightweight index |
| Pattern detail | Inline in SKILL.md | Extracted to `references/patterns.md` |
| Pitfalls | Inline in SKILL.md | Extracted to `references/pitfalls.md` |
| Quick reference | Inline in SKILL.md | Extracted to `references/quick-reference.md` |
| Load cost | Full payload on every skill load | Only index loads; references loaded on demand |
