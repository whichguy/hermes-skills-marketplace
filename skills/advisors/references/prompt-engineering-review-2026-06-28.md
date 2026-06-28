# Prompt Engineering Review — Two-Model Pattern

> **Date:** 2026-06-28
> **Context:** SDLC pipeline prompt engineering fixes (P8)
> **Models:** DeepSeek (reasoner) + Kimi (coder, via advisors)

## Pattern

When reviewing LLM prompts for correctness, use two models with different
strengths:

1. **DeepSeek** — analytical reasoning, finds structural issues, contradictory
   directives, and prompt-design flaws (few-shot format, delimiter placement,
   rule ordering, persona bloat)
2. **Kimi** — code-focused lens, finds implementation-level issues the reasoner
   misses (injection risk, hardcoded language assumptions, role ordering in
   code, parser robustness)

Dispatch both with the same prompt corpus (all prompt-related code from the
target files), then synthesize their findings into a unified fix plan.

## Proven Results

On the SDLC pipeline's triage/pipeline/model_utils prompts (~500 lines of
prompt code across 3 files):

| Reviewer | Findings | Unique catches |
|----------|----------|----------------|
| DeepSeek | 12 issues (4 P0, 4 P1, 4 P2) | Contradictory directives (P0-A), few-shot format mismatch (P0-B), rule ordering (P2-C), persona bloat (P2-E) |
| Kimi | 8 issues (validated all 12 + 4 new) | Injection risk (P0-C), hardcoded Python (P1-B), role ordering in code (P1-D), parser robustness (P1-E) |

**Combined:** 16 issues, all fixed, 261 tests pass, 5/5 live E2E pass.

## Why Two Models

- DeepSeek catches *what the prompt says* (contradictions, format, structure)
- Kimi catches *what the code does with the prompt* (injection, language
  assumptions, parser edge cases)
- Neither alone would have found all 16 issues
- The overlap (12 issues both found) provides validation confidence

## Dispatch Pattern

```python
# Use prompt_model.py (advisors skill) for per-call model diversity
# NOT delegate_task — model overrides are unreliable due to config cache

# Seat 1: DeepSeek (reasoner)
subprocess.run([sys.executable, PROMPT_MODEL,
    "-m", "deepseek-v4-pro:cloud",
    "-p", "Review these LLM prompts for structural issues...",
    "--context", prompt_corpus,
    "-o", "/tmp/review-deepseek.md"
], timeout=180)

# Seat 2: Kimi (coder, via ask)
subprocess.run([sys.executable, ASK_PY,
    "kimi", "--prompt", "Review these LLM prompts for implementation issues...",
    "--context-file", "/tmp/prompt-corpus.md",
    "--mode", "agent", "--thinking", "low",
    "--max-turns", "15", "--timeout", "180",
    "--toolsets", "file,terminal",
    "-o", "/tmp/review-kimi.md"
], timeout=180)
```

## Synthesis

Read both reviews, cross-reference findings, produce a unified fix plan
organized by priority (P0 → P1 → P2). Both reviewers should agree on P0
bugs; disagreements on P1/P2 items need controller judgment.
