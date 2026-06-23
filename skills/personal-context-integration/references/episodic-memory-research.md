# Episodic Memory Research for Email — Key Findings

**Researched:** 2026-06-22
**Purpose:** Reference for future sessions considering episodic memory enhancements to the personal-context system.

## Academic Papers

### Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv:2501.13956)
- **URL:** https://arxiv.org/html/2501.13956v1
- **Most directly relevant architecture.** Three-tier knowledge graph:
  - Episode Subgraph (𝒢ₑ): Raw input data stored non-lossily as episodic nodes
  - Semantic Entity Subgraph (𝒢ₛ): Entities extracted from episodes with resolved identities
  - Community Subgraph (𝒢𝒸): Clusters of connected entities with map-reduce summarizations
- **Bi-temporal model:** Two timelines — T (event timeline: when facts held true) and T' (transactional: when data was ingested). Each edge has 4 timestamps: `t_created`, `t_expired`, `t_valid`, `t_invalid`.
- **Performance:** 94.8% accuracy on DMR benchmark; 18.5% improvement on LongMemEval; context tokens reduced 115k→1.6k.

### Episodic memory in AI agents poses risks (arXiv:2501.11739, SaTML 2025)
- **URL:** https://arxiv.org/html/2501.11739v2
- Defines episodic memory as combining **what, when, and where** (Tulving's distinction).
- Key insight: episodic memory enables planning, imagination, problem-solving, decision-making — not just recall.
- Four safety principles: monitoring, control, explainability, unique controllability.

### Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (arXiv:2504.19413)
- **URL:** https://arxiv.org/html/2504.19413v1
- Hybrid architecture: vector store + optional graph memory (Mem0g).
- 26% relative improvement over OpenAI's memory on LOCOMO benchmark.

## Open-Source Frameworks

| Framework | Episodic Support | URL | Key Architecture |
|-----------|-----------------|-----|-----------------|
| Graphiti (by Zep) | ✅ Native episode subgraph | https://github.com/getzep/graphiti | Neo4j-backed bi-temporal KG: episodic→semantic→community |
| Zep | ✅ Episode-based temporal | https://help.getzep.com | Managed service wrapping Graphiti |
| Mem0 | ✅ Temporal queries (graph on Pro) | https://github.com/mem0ai/mem0 | Vector-first + optional graph; LLM-driven extraction |
| Letta (MemGPT) | ✅ Memory tiers | https://github.com/letta-ai/letta | OS-inspired: agent manages own memory |
| LangMem | ✅ Explicit Episode schema | https://github.com/langchain-ai/langmem | Pydantic Episode schema (observation/thoughts/action/result) |
| Memobase | ✅ User event tracking | https://github.com/memodb-io/memobase | Profile-based with batch processing |
| Honcho | ✅ Long-term + social | https://github.com/plastic-labs/honcho | Agent social context; managed |
| Cognee | ✅ KG from multimodal | https://github.com/topoteretes/cognee | Pipeline: ingest→extract→graph→query; MCP-compatible |
| Charlie Mnemonic | ✅ LTM + STM + episodic | https://github.com/GoodAI/charlie-mnemonic | Personal assistant that writes differently to different people based on accumulated relationship memory |

## Email-Specific Memory Mapping (Nylas CLI guide)

| Memory Type | Email Equivalent |
|------------|------------------|
| Semantic | Searchable facts: contacts, pricing, specs, agreed terms |
| Episodic | Timestamped thread narratives — negotiations, decisions, incidents |
| Procedural | Sent emails containing proven response patterns, templates, tone |

**Key insight:** RFC 5322 `References` and `In-Reply-To` headers create reliable chains for reconstructing interaction timelines. Gmail's `threadId` is the equivalent.

**Gap identified:** No existing system specifically compiles email history into a navigable episodic timeline with graph-based exploration. The components exist but nobody has integrated them for this purpose. This is an integration opportunity.

## Architecture Mapping: Graphiti → Existing System

| Graphiti Layer | Jim's Existing System |
|---------------|----------------------|
| Episode Subgraph (raw messages) | `EpisodeStore` in `email_utils.py` (implemented) |
| Semantic Entity Subgraph (extracted facts) | `people.yaml`, `relationships-reviewed.yaml` |
| Community Subgraph (entity clusters) | `circles.yaml` |
| Bi-temporal model | Partial — episodes track `started_at` + `last_activity_at`; full bi-temporal (when facts held true vs when ingested) is a future enhancement |

## Implementation Path Chosen

**Near-term (implemented):** Lightweight custom layer using local JSON state files. No Neo4j dependency. Integrates with existing people.yaml for person resolution. Temporal decay built into EpisodeStore (365-day retention, 500-episode cap).

**Long-term (evaluation):** Graphiti (Neo4j-backed bi-temporal KG) if temporal reasoning becomes the bottleneck. Graphiti's YAML-to-Graphiti sync bridge would load people.yaml, circles.yaml as pre-seeded entities. New email episodes would resolve against existing entities via hybrid cosine + BM25 search.

## Temporal Decay Retrieval Scoring

```
score = similarity_score * recency_weight * frequency_weight * importance_weight

recency_weight = exp(-days_since_episode / 30)  # 30-day half-life
frequency_weight = log(1 + episode_count_for_person)
importance_weight = LLM-assigned during extraction (0.1-1.0)
```

## Relationship Arc Summarization (Future)

For each person, maintain an evolving "relationship arc" — a running summary that incorporates each new episode:
```
Arc(t₀): "Initial outreach about spring fundraiser"
Arc(t₁): "Venue options discussed, 3 candidates proposed"
Arc(t₂): "Budget comparison requested by Jim"
Arc(t₃): "Venue selected, contract sent"
Arc(t₄): "Contract signed, planning phase started"
```
This is Graphiti's community subgraph summarization applied per-person.