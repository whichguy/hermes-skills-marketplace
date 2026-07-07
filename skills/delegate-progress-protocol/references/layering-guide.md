# Behavioral Directive Layering Guide

When embedding a new behavioral requirement into Hermes, use this 3-layer pattern.
Each layer solves a different failure mode — skip one and the behavior degrades.

## The Three Layers

| Layer | What | Failure mode if skipped |
|---|---|---|
| **SOUL.md** | 4-8 line directive in the persona file | Agent forgets to load the skill → behavior silently skipped |
| **Skill** | Full SKILL.md with templates, decision matrix, pitfalls | Agent knows to "do it" but has no format reference → inconsistent output |
| **Config** | Memory/ceiling bumps if the behavior needs more context | Agent runs out of headroom mid-task → truncated reasoning |

## When to use all three

- The behavior must fire **every session**, not just when the user remembers
- The behavior has **format requirements** (tables, specific sections, polling intervals)
- The behavior needs **more context** than the default memory ceiling allows

## When SOUL.md alone is enough

- Simple tone/style directives ("be concise", "use emoji headers")
- No format templates needed
- No memory pressure

## When skill alone is enough

- Opt-in workflows the user explicitly invokes (`/skill-name`)
- One-off task classes the user triggers manually

## Concrete example: Delegation Visibility Protocol

```
SOUL.md (6 lines):
  "## Delegation Visibility Protocol — ALWAYS"
  → 3 phases listed, references skill by name
  → Loads every message, no opt-in

Skill (delegate-progress-protocol):
  → Full format templates for each phase
  → Dispatch mode decision matrix (batch vs individual)
  → Polling interval guidance, pitfalls

Config:
  → memory_char_limit: 3000 → 6000
  → user_char_limit: 4000 → 8000
  → Doubled headroom for protocol overhead
```

## Anti-patterns

- **SOUL.md with full templates** — bloats the persona file, harder to maintain
- **Skill without SOUL.md trigger** — agent may not load it for quick tasks
- **Config bump without checking actual usage** — measure first, bump second
