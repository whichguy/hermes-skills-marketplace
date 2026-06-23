# Email Utils Implementation Guide

**Created:** 2026-06-22
**Status:** Implemented and tested

## Overview

A shared utility module at `/opt/data/scripts/email_utils.py` provides 5 classes that integrate the personal-context relationship graph with the email-processing cron pipeline. All classes are pure Python stdlib — no external dependencies.

## Classes

### PeopleResolver

Resolves email addresses and names to person context from `people.yaml`.

```python
from email_utils import PeopleResolver
resolver = PeopleResolver()
ctx = resolver.resolve(email="knwiese2@gmail.com", name="Kristen Wiese")
# Returns: {person_id, display_name, circle_ids, sensitivity, is_self, is_known, priority_hint, style_hint}
```

**Resolution order:** email lookup in `people.yaml` aliases → name lookup → fallback to unknown.

**Pitfall:** `people.yaml` may have names but not emails for some people (e.g., family members). The resolver falls back to name-based lookup when email lookup fails. This means the `from` header's display name is important — if Gmail only shows the email without a name, resolution may fail for people without emails in `people.yaml`.

**Integration:** `enrich_message(msg)` parses the `from` header, resolves the sender, and adds `person_id`, `person_name`, `circle_ids`, `sender_is_known`, `sender_is_self`, `priority_hint`, `style_hint` to the message dict.

### RecentlySurfaced

Shared cross-cron dedup state. Prevents triage (every 30m) and sweep (daily) from double-surfacing the same thread within 12 hours.

```python
from email_utils import RecentlySurfaced
rs = RecentlySurfaced()
rs.mark("personal", "thread123", "inbox_triage")
recent = rs.check("personal", "thread123")  # Returns metadata or None
```

**State file:** `cron/state/recently_surfaced.json` (0600, atomic writes).
**Expiry:** 12 hours. Keyed by `account:threadId`.

### EpisodeStore

Lightweight episodic memory for email threads.

```python
from email_utils import EpisodeStore
ep_store = EpisodeStore()
# Create/update
ep_store.upsert("personal", "thread123", person_id="person_ed_johnson",
                subject="Spring fundraiser", status="needs_action", message_count=3)
# Query context
ctx = ep_store.get_episode_context("personal", "thread123")
# Query awaiting reply (older than 3 days)
awaiting = ep_store.query_awaiting_reply(older_than_days=3)
# Query by person
episodes = ep_store.query_by_person("person_ed_johnson", limit=10)
```

**State file:** `cron/state/email_episodes.json` (0600, atomic writes).
**Cap:** 500 active episodes. Oldest resolved archived first.
**Retention:** 365 days from creation, then auto-deleted.
**Privacy:** Class B. No raw email bodies. Metadata-level summaries only.

### ActionQualityLog

Tracks draft outcomes for the email-processing feedback loop.

```python
from email_utils import ActionQualityLog
log = ActionQualityLog()
log.record(account="personal", thread_id="t1", action="draft_created",
           outcome="pending", cron_source="inbox_triage")
stats = log.stats()  # {total, by_outcome, by_source, by_action}
```

**State file:** `cron/state/action_quality_log.json` (0600, atomic writes).
**Retention:** 90 days.
**Actions:** `draft_created`, `draft_sent`, `draft_discarded`, `draft_edited`, `alert_sent`, `alert_suppressed`.
**Outcomes:** `pending`, `sent_by_jim`, `discarded`, `edited_then_sent`, `edited_then_discarded`, `suppressed`.

### TopicClusterer

Pure-Python TF-IDF topic clustering for email subjects. No external dependencies.

```python
from email_utils import TopicClusterer
clusterer = TopicClusterer(min_similarity=0.30)
clusterer.fit(["Tax filing deadline", "IRS extension request", "Spring fundraiser"])
clusters = clusterer.cluster()  # {cluster_id: [doc_indices]}
label = clusterer.label_for_cluster([0, 1])  # "extension filing deadline"
```

**Algorithm:** TF-IDF vectorization + agglomerative clustering with average linkage.
**Stopwords:** Includes standard English stopwords + email-specific noise (`re`, `fwd`, `fw`, `hi`, `hello`, `meeting`, `update`, `reminder`, `wiese`).
**Min word length:** 4 characters (filters out short noise tokens).
**Min similarity:** 0.30 default (adjustable). Lower = more clusters, higher = fewer.

## Precheck Script Integration

### inbox_triage_precheck.py
- `PeopleResolver.enrich_message()` called in `minimal()` for each surfaced message
- `classify_thread_state()` pre-classifies as `needs_action` / `awaiting_reply` / `drafted`
- `EpisodeStore.get_episode_context()` provides prior action summary if available
- `RecentlySurfaced.mark()` called for each surfaced thread after write_state
- `EpisodeStore.upsert()` creates/updates episode records

### followup_sweep_precheck.py
- **Bug fix:** `draft_thread_ids()` function ported from triage — now checks `in:drafts` and excludes drafted threads (fail-safe: skips account on draft lookup error)
- Same PeopleResolver + EpisodeStore + RecentlySurfaced integration as triage
- `classify_thread_state()` pre-classifies threads
- Dry-run output now shows `excluded (already drafted)` and `excluded (recently surfaced by triage)` counts

### email_wiki_precheck.py
- `PeopleResolver.enrich_message()` called on anchor message of each thread
- Person context (`person_id`, `person_name`, `circle_ids`) included in wiki triage output
- `EpisodeStore.get_episode_context()` shows prior episode status in wiki output
- `EpisodeStore.upsert()` creates episode records for each processed thread

### personal_context_review_precheck.py
- `PeopleResolver` used for velocity detection (resolves emails to person_ids for known people)
- `EpisodeStore.query_by_person()` used as historical baseline for frequency comparison
- `TopicClusterer` replaces keyword-only topic detection with TF-IDF clustering
- `ActionQualityLog.stats()` included in weekly review payload
- New `velocity_signals` field: `heating_up` (2x frequency increase) and `cooling_down` (60+ day silence)
- New `topic_clusters` field: TF-IDF grouped subject clusters with labels

## Testing

All classes tested with tempfile-based isolated state files:

```bash
cd /opt/data && python -c "
import sys; sys.path.insert(0, 'scripts')
from email_utils import PeopleResolver, RecentlySurfaced, EpisodeStore, ActionQualityLog, TopicClusterer
# Tests verify: people resolution by email + name, cross-cron dedup, episode CRUD,
# action quality logging, TF-IDF clustering grouping similar subjects
"
```

Dry-run verification:
```bash
python scripts/followup_sweep_precheck.py --dry-run  # Shows new fields in payload
python scripts/inbox_triage_precheck.py --dry-run
python scripts/personal_context_review_precheck.py --dry-run
```

## Future Enhancement Path

1. **Graphiti integration** — if temporal reasoning becomes the bottleneck, evaluate Graphiti (Neo4j-backed bi-temporal KG) as a replacement for the JSON episode store. Graphiti's episode→semantic→community hierarchy maps directly to the existing people.yaml/circles.yaml architecture.
2. **Cross-channel episodes** — extend EpisodeStore to link email threads with calendar events and WhatsApp messages into unified interaction timelines.
3. **Relationship arc summaries** — maintain per-person running summaries that compress old episodes into a narrative arc ("initial outreach → negotiation → contract signed → follow-up").
4. **Semantic embeddings** — replace TF-IDF with sentence-transformer embeddings for better topic clustering (requires adding a dependency).