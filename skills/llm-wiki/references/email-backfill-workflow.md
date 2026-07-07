# Email-to-Wiki Backfill Workflow

Proven workflow for mining 2 years of email history into the wiki. Validated June 2026
on Jim's deployment (2 Gmail accounts, 2,297 messages, 1,189 threads → 66 wiki pages).

## Phase 1: Landscape Scan (zero token cost)

Run quarterly windows to bypass the Gmail API 200-per-call cap. This maps the full
corpus without fetching any thread bodies or mutating seen state.

```bash
export HERMES_HOME=/opt/data
SCRIPT="$HERMES_HOME/scripts/email_wiki_backfill.py"

# 8 quarterly windows × 2 accounts = ~5min total
for Q in "2024/06/01 2024/09/01" "2024/09/01 2024/12/01" "2024/12/01 2025/03/01" \
         "2025/03/01 2025/06/01" "2025/06/01 2025/09/01" "2025/09/01 2025/12/01" \
         "2025/12/01 2026/03/01" "2026/03/01 2026/06/01"; do
    AFTER=$(echo $Q | cut -d' ' -f1)
    BEFORE=$(echo $Q | cut -d' ' -f2)
    python3 $SCRIPT --after "$AFTER" --before "$BEFORE" --dry-run --summary-only --no-dedup
done
```

Key flags:
- `--dry-run` — no body fetch, no seen-state mutation (safe for exploration)
- `--summary-only` — cluster counts only, no thread details
- `--no-dedup` — show all threads even if already in seen state

## Phase 2: Signal Classification (Python, no API calls)

Classify each thread into signal tiers using metadata only (subject, from, snippet,
message count, multi-party flag). This determines which threads get body-fetched.

```python
# High-signal (fetch body): multi-party AND 3+ messages, OR 5+ messages total
# Medium-signal (fetch if time): from known project domain, 2+ messages
# Skip: WooCommerce orders, form submissions, OOO, vendor marketing, false positives
```

False positive patterns to filter out:
- USAW cluster catches Tesla/insurance via "session"/"to" keyword matches
- Solar cluster catches Uber rides, dinner reservations via "panel"/"grid" matches
- Always do a second-pass domain/subject filter after keyword classification

## Phase 3: Per-Cluster Wiki Enrichment (subagent delegation)

Dispatch one subagent per topic cluster using `delegate_task`. Each subagent:

1. **Orients**: reads `SCHEMA.md`, `index.md`, existing pages for its cluster
2. **Fetches thread bodies**: `gmail get <message_id>` per thread (sequential, ~5s each)
3. **Extracts knowledge**: people, orgs, decisions, timelines, dollar amounts, technical specs
4. **Updates existing pages**: adds new info, bumps `updated` date, adds source citations
5. **Creates new pages**: entity pages for people/orgs, concept pages for projects/topics
6. **Creates raw article files**: `raw/articles/<topic>-<date>.md` with Gmail thread source URL
7. **Updates navigation**: `index.md` (new entries + page count) and `log.md` (action entry)
8. **Lints**: checks for broken wikilinks, orphans, missing frontmatter

Two subagents in parallel processed 50 threads → 28 wiki pages + 28 raw articles in ~10min.

**Pitfall — subagent 600s timeout catches post-processing:**
Both subagents timed out at 600s (33 and 51 API calls respectively) but had already
created all wiki pages and raw articles. The timeout caught them BEFORE they finished:
index.md updates (25 new pages not indexed), orphan link fixes (scott-cler), and log.md
entries. The parent agent must verify and complete these post-processing steps after
subagent results return. Specifically check:
1. **index.md completeness** — diff actual page slugs vs indexed slugs, add missing entries
2. **Orphan pages** — run lint, add inbound `[[wikilinks]]` from related pages to new orphans
3. **log.md** — append a session entry if the subagent didn't (subagents often skip this)
4. **Page count** — update the "Total pages: N" header in index.md

This is not a failure — the subagents do the expensive work (API calls + wiki page
authoring). The post-processing is cheap and fast (~2min of parent time).

## Phase 4: Quality Evaluation

Run the wiki lint script after all subagents complete:

```python
# Check: broken wikilinks, orphans, frontmatter, page sizes, tag audit
# Compare against pre-backfill baseline (save page count, word count, link count, broken links)
```

Key metrics to track:
- Page count delta (before → after)
- Word count delta (measures content depth, not just page count)
- Wikilink count delta (measures interconnection)
- Broken wikilink count (should not increase — all new links should resolve)
- Orphan count (new pages should have inbound links from related pages)

## Phase 5: Remaining Clusters

After the highest-value clusters are processed, continue with remaining clusters:

| Priority | Cluster | Threads | High-signal | Notes |
|----------|---------|---------|-------------|-------|
| 1 | USAW | 535 | 84 | Largest cluster, high project value |
| 2 | Canyon Creek church | 45 | ~15 | Leadership, events, finance |
| 3 | Travel/logistics | 57 | ~10 | NCW trips, cruises |
| 4 | Personal finance | 38 | ~5 | Low wiki value (accounts exist) |
| 5 | Unclassified | 184 | — | Needs manual review for missed clusters |

## Timing

- Phase 1 (landscape scan): ~5min (8 quarters × 2 accounts, sequential API)
- Phase 2 (classification): ~30s (Python, no API)
- Phase 3 (wiki enrichment): ~10min per cluster pair (2 subagents in parallel)
- Phase 4 (evaluation): ~30s (Python lint)
- Total for 2 clusters: ~15min end-to-end

## State Integration

The backfill script shares `wiki_email_seen.json` with the daily email-to-wiki cron
(`email_wiki_precheck.py`). Non-dry-run runs mark all fetched threadIds as seen,
preventing the daily cron from reprocessing backfilled threads. Dry-run runs do NOT
update seen state (safe for repeated exploration).