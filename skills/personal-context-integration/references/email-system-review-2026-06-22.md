# Email Processing Scripts + Relationship Graph + Episodic Memory Review

**Date:** 2026-06-22
**Scope:** 4 email-processing cron precheck scripts, 3 graph builder scripts, 6 planning docs, canonical data files

## Scripts reviewed

### Email-processing cron prechecks (4 scripts in /opt/data/scripts/)

1. **`inbox_triage_precheck.py`** — every 30m. Scans primary inbox for new mail (2-day lookback), dedupes against seen-state, excludes threads with pending Gmail drafts, emits metadata-only payload for agent to draft replies.

2. **`followup_sweep_precheck.py`** — daily 15:00 UTC. 7-day lookback for threads needing follow-up. Sibling of triage with wider window.

3. **`email_wiki_precheck.py`** — daily 08:00 UTC. Fetches email bodies for multi-party threads, converts to wiki pages with Gmail deep-links.

4. **`personal_context_review_precheck.py`** — weekly Sat. 28-day lookback, detects new people/topics/info-drift (domain changes for known people).

### Graph builder scripts (3 scripts in /opt/data/personal-context/)

1. **`build_profile_graph.py`** — one-shot Google Workspace discovery (Gmail/Calendar/Drive/Contacts metadata). Generates relationships.yaml, domains.yaml, review-queue.md, discovery-audit.json.

2. **`build_candidate_relationship_edges.py`** — builds local-only third-party relationship edges from discovery audit metadata. Privacy: no subject/snippet/body text in output; excludes self aliases; generic domains suppressed; sensitive topics → `unknown_association`.

3. **`build_pending_contact_review.py`** — builds review packages for pending VIP contacts. Metadata-only, includes `assert_no_raw_payloads()` safety check.

## Key findings

### Bugs found

**1. `followup_sweep_precheck.py` has no draft exclusion.** Unlike `inbox_triage_precheck.py` which checks `in:drafts` and skips threads with pending drafts, the followup sweep does NOT. This risks duplicate drafts when a thread already has a pending draft from triage. Violates the idempotency principle ("never re-do work already done").

**2. No cross-reference between triage and sweep.** A thread surfaced by triage at 2 PM can be re-surfaced by the daily sweep at 3 PM. Both have separate seen-state files and neither knows what the other already handled.

### Architectural gaps

**No relationship graph integration in any precheck.** All four scripts resolve senders as raw email strings. None check `people.yaml` or call `resolve_engagement.py`. The agent gets `from: ed@fortifiedstrength.org` but no `person_id`, `circle_id`, `priority`, or `engagement_style`.

**No thread state pre-classification.** Prechecks don't check who sent the last message. Could pre-classify as `awaiting_reply` (Jim sent last) vs `needs_action` (other party sent last) vs `drafted` (has draft).

**No episodic/temporal dimension.** The graph stores static facts (who people are, what topics) but not interaction events (when, what happened, how relationships evolve). Each email processed in isolation.

**No action history.** Agent doesn't know what it did last time for a given thread/relationship (draft created? replied? ignored?).

**No seasonal awareness.** The 28-day flat window in personal_context_review misses tax season, USAW meets, church cycles.

## Improvement recommendations (priority order)

| # | Recommendation | Effort | Risk |
|---|---|---|---|
| 1 | Fix followup sweep draft exclusion — port `draft_thread_ids()` from triage | 30 min | Low |
| 2 | Add people.yaml lookup to prechecks — resolve senders to person_id + circle | 2 hrs | Low |
| 3 | Add thread state pre-classification — who sent last message | 1 hr | Low |
| 4 | Cross-reference triage + sweep — shared "recently surfaced" state | 1 hr | Low |
| 5 | Design + build episodic memory layer — episodes.json, lifecycle, integration | 1-2 days | Medium |
| 6 | Seasonal awareness — per-person frequency trends | 4 hrs | Low |
| 7 | Action quality log — track draft outcomes for feedback loop | 3 hrs | Low |
| 8 | Semantic topic clustering — replace keyword matching with embeddings | 1 day | Medium |

## Episodic memory schema (proposed)

```yaml
episodes:
  - episode_id: ep_2026_05_03_ed_johnson_spring_fundraiser
    person_ids: [person_ed_johnson]
    thread_ids: ["gmail_thread_abc123"]
    account: nonprofit
    started_at: "2026-05-03T14:00:00Z"
    last_activity_at: "2026-05-03T18:30:00Z"
    status: awaiting_reply  # active, awaiting_reply, resolved, stale
    topic_arcs: ["spring_fundraiser", "venue_selection"]
    action_summary: "Ed proposed 3 venues; Jim asked for budget comparison"
    participants: [person_ed_johnson, jim]
    message_count: 4
    last_action_by: jim
    agent_actions:
      - action: draft_created
        at: "2026-05-03T15:00:00Z"
        draft_id: "gmail_draft_xyz"
        outcome: pending
    sensitivity: normal
    retention_expires_at: "2027-05-03T00:00:00Z"
```

**Lifecycle:** detected → active → resolved → compressed (30d) → archived (90d) → deleted (1yr)

**Privacy:** Class B (local-only, no raw bodies, never in durable memory without approval)