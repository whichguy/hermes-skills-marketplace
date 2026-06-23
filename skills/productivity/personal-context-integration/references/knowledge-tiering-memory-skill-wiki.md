# Knowledge tiering: memory vs. skill vs. wiki

A reusable decision model for *where a durable fact belongs* in Hermes, plus the
verify-before-trim discipline for moving knowledge between tiers. Derived from a session that
audited Jim's memory, reclassified 3 entries, and stood up the llm-wiki knowledge tier.

## The three tiers

| Tier | Holds | Trigger | Cost | Location |
|---|---|---|---|---|
| **Memory** (`MEMORY.md` / `USER.md`) | Identity & preferences — *who the user is / how they want things* | Injected **every turn** | Recurring per-turn tokens | `$HERMES_HOME/memories/` |
| **Skills** | Procedures — *the steps to do task X* | Loaded **on-demand** when relevant | Only when loaded | `$HERMES_HOME/skills/` |
| **Wiki** (`llm-wiki`) | Knowledge — *facts about topic Y I look up* | **Queried** explicitly | Zero until read | `$WIKI_PATH` |

## Decision rule

- "who the user is / how they want it" → **Memory** (must be present unprompted)
- "the steps to do task X" → **Skill** (loaded on-demand)
- "facts about topic Y I'll look up" → **Wiki** (compounds, queried)

## Why it matters

Memory has a hard char ceiling (config-driven; see `write-approval-queue-and-store-limits.md`).
Procedures duplicated into memory pay recurring per-turn token cost to duplicate what a skill
loads for free. Occasionally-looked-up knowledge (model comparisons, vendor intel, detailed
architecture) belongs in neither memory nor a procedure skill — it belongs in the wiki, where
it costs nothing until queried and compounds rather than being rediscovered per query (the
Karpathy LLM-wiki insight).

## Trimming / reclassifying: verify coverage FIRST

When auditing memory and a procedural entry looks like "a skill already covers this":

1. **Grep the target skill** for the specific facts before removing them from memory. Coverage
   of the *topic* is not coverage of the *fact*.
2. **If the fact is NOT in a skill yet, add it to the skill FIRST**, then remove from memory.
   Never drop an uncovered fact.
3. **Split entries** when part is identity (keep in memory) and part is procedure (move to skill).

### Session examples
- **WhatsApp entry** → kept the trust-anchor phone numbers in memory (identity), moved the
  pairing/QR/allowlist procedure to the `hermes-whatsapp-gateway` skill (which used placeholder
  numbers — so the numbers genuinely had to stay in memory).
- **Google Workspace entry** → kept account names (`personal`/`nonprofit`) in memory; the
  `uv run --with ...` dependency-wrapper quirk was already fully documented in the
  `google-workspace` skill, so it was trimmed out of memory.
- **Cron prompt-freeze entry** → was in NO skill; added as a pitfall in `script-first-cron-design`
  FIRST, then removed from memory.

## Initializing the wiki tier (llm-wiki)

The Karpathy LLM-wiki pattern is implemented by the `llm-wiki` skill — don't build a parallel
system. To stand it up:

1. Create the dir structure: `raw/{articles,papers,transcripts,assets}/`, `entities/`,
   `concepts/`, `comparisons/`, `queries/`.
2. Write `SCHEMA.md` (domain, conventions, frontmatter, tag taxonomy, page thresholds), plus
   `index.md` and an append-only `log.md`.
3. Set `WIKI_PATH=<dir>` in `$HERMES_HOME/.env`.
4. Seed 2+ concept pages with **reciprocal `[[wikilinks]]`** so nothing is an orphan, and list
   them in `index.md`.
5. Lint: 0 orphans, 0 broken wikilinks, all frontmatter present. A broken wikilink is the most
   common seed mistake (referencing a page slug you didn't create).

Tier note: the wiki is the right home for "look-up knowledge" that's too detailed for always-on
memory and isn't a procedure — e.g. an `entities/hermes-agent` page or `concepts/<technique>`
pages. Memory and skills stay lean as a result.
