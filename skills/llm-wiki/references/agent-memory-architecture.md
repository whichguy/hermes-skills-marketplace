# Agent Memory Architecture: Linked Markdown vs Vector DB vs Knowledge Graph

**Researched:** 2026-06-22
**Purpose:** Reference for sessions where the user asks about semantic data structures, Obsidian, or agent memory architecture.

## The Three-Tier Knowledge System (Jim's deployed architecture)

Jim's system is already a semantic model — it uses three complementary tiers:

| Tier | Tool | Data Structure | Semantic? | Cost Model |
|------|------|---------------|-----------|------------|
| Memory (MEMORY.md/USER.md) | Hermes built-in | Flat text, injected every turn | No — always-on context | Per-turn token cost |
| Wiki (/opt/data/wiki) | Karpathy LLM Wiki | Linked markdown with `[[wikilinks]]`, frontmatter, tags | Yes — bidirectional links form a knowledge graph | Zero cost until read |
| Personal-context | YAML/JSON files | Structured graph: person_ids, circle_ids, edges, policies | Yes — semantic relationship graph | Zero cost until loaded |

Plus a semantic search layer (qmd) that provides BM25 + vector embeddings across the wiki.

## Is Obsidian what people use?

**Yes — as the human-facing viewer, not the agent-facing memory system.**

- Obsidian reads `[[wikilinks]]` and shows them as a visual network graph
- The wiki at `/opt/data/wiki` is already an Obsidian vault — set `OBSIDIAN_VAULT_PATH=/opt/data/wiki`
- Obsidian adds: graph visualization, Dataview queries, mobile sync, plugins
- Obsidian does NOT add: agent query capability, temporal tracking, privacy enforcement, cron-driven ingestion

**Key distinction:** Obsidian is a viewer. The agent reads/writes files. The agent doesn't need Obsidian — it needs the linked markdown structure, which it already has.

## Is there something better for agents?

### Purpose-built agent memory systems (2025-2026 landscape)

| System | Type | Semantic Model | Best For | URL |
|--------|------|---------------|----------|-----|
| Graphiti (Zep) | Temporal KG | Bi-temporal knowledge graph (Neo4j) | Relationship evolution, temporal queries | https://github.com/getzep/graphiti |
| Mem0 | Hybrid | Vector + optional graph | General agent memory, easy setup | https://github.com/mem0ai/mem0 |
| Letta (MemGPT) | Agent runtime | Self-managed memory tiers | Agent self-edits its own memory | https://github.com/letta-ai/letta |
| LangMem | SDK | Episode schema + vector | LangGraph integration | https://github.com/langchain-ai/langmem |
| Cognee | Pipeline | KG from multimodal data | MCP-compatible ingestion | https://github.com/topoteretes/cognee |
| Honcho | Managed | Social context memory | Agent social interactions | https://github.com/plastic-labs/honcho |

### When to evaluate Graphiti (the gold standard)

Graphiti's three-tier architecture (episode → semantic → community) maps directly to Jim's system:

| Graphiti Layer | Jim's Equivalent |
|---------------|-----------------|
| Episode Subgraph | `EpisodeStore` in `email_utils.py` |
| Semantic Entity Subgraph | `people.yaml`, `relationships-reviewed.yaml` |
| Community Subgraph | `circles.yaml` |
| Bi-temporal model | Partial (episodes track timestamps; full bi-temporal is future) |

**Threshold for evaluation:** Graphiti requires Neo4j and is designed for thousands of entities. Jim's current scale (7 people, 23 wiki pages, 288 episodes) is well-served by YAML + JSON + linked markdown + qmd. Evaluate Graphiti at 500+ people and 200+ wiki pages.

### The "linked markdown" approach (what Jim uses)

This is a legitimate semantic data structure, not just "text files":
- `[[wikilinks]]` create bidirectional edges (like RDF triples but human-readable)
- YAML frontmatter provides typed metadata (type, tags, sources, confidence, contested)
- qmd adds vector embeddings + BM25 hybrid search
- The graph is portable (any markdown editor can read it), version-controllable, and agent-readable

**Advantages over Neo4j/Graphiti at current scale:**
- No database dependency
- Human-readable and human-editable
- Works with Obsidian as a viewer
- Version-controllable via git
- Zero infrastructure cost

**Disadvantages at scale (500+ entities):**
- No bi-temporal model (can't track when facts held true vs when ingested)
- No automatic entity resolution (Graphiti does hybrid cosine + BM25 entity matching)
- No community detection algorithm (circles are manually defined, not auto-clustered)
- No edge invalidation (new facts can't automatically invalidate old ones)

## Decision matrix: when to evolve

| Signal | Action |
|--------|--------|
| <100 people, <100 wiki pages | Stay with YAML + JSON + linked markdown + qmd |
| Need temporal reasoning ("when did this fact become true?") | Evaluate Graphiti |
| Need automatic entity resolution across data sources | Evaluate Graphiti or Mem0 |
| Need agent to self-manage memory | Evaluate Letta |
| Want Obsidian graph view | Set `OBSIDIAN_VAULT_PATH=/opt/data/wiki` — already compatible |
| Need semantic search | `qmd embed` — already active |
| Need episodic memory | `EpisodeStore` in `email_utils.py` — already implemented |

## qmd semantic search (activated Jun 2026)

- 37 documents, 56 chunks embedded
- Vector index: active
- BM25 + semantic hybrid search
- MCP server wired (`mcp_wiki_search_query`, `mcp_wiki_search_get`, etc.)
- First query may time out while model loads; subsequent queries are faster