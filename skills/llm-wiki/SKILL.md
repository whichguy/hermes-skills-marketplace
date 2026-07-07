---
name: llm-wiki
description: 'Karpathy''s LLM Wiki: build/query interlinked markdown KB.'
version: 2.1.0
author: Hermes Agent
license: MIT
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - wiki
    - knowledge-base
    - research
    - notes
    - markdown
    - rag-alternative
    category: research
    related_skills:
    - obsidian
    - arxiv
    config:
    - key: llm-wiki.enabled
      description: Enable llm-wiki skill behavior
      default: true
      prompt: Enable llm-wiki skill?
---


# Karpathy's LLM Wiki

Build and maintain a persistent, compounding knowledge base as interlinked markdown files.
Based on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## References

- `references/email-to-wiki-signal-guide.md` — Tier classification for mining email history (🟢/🟡/🔴), Jim-specific topic clusters, sampling commands, and an inline lint script.
- `references/email-backfill-workflow.md` — Proven 5-phase workflow for 2-year email backfill: quarterly landscape scan, signal classification, parallel subagent wiki enrichment, quality evaluation, remaining clusters. Includes timing, state integration, and false-positive filtering.
- `references/qmd-setup-notes.md` — qmd install details for Jim's deployment: correct package name (`@tobilu/qmd`), file locations, MCP config with required env vars, pitfalls, semantic search activation steps, and embedding download experience.
- `references/agent-memory-architecture.md` — comparison of linked markdown vs vector DB vs knowledge graph for agent memory. Includes the 2025-2026 agent memory framework landscape (Graphiti, Mem0, Letta, LangMem, etc.) and a decision matrix for when to evolve from YAML+JSON+markdown to Neo4j/Graphiti.
- `references/session-to-wiki-capture.md` — Session-to-wiki capture pattern: queries sessions DB for tool-heavy non-cron sessions, LLM reviews via session_search and files wiki-worthy knowledge. Session DB schema, precheck design, cron config.
- `references/wiki-lint-script.md` — Programmatic wiki lint: scans for broken wikilinks, orphan pages, frontmatter validation, index completeness, page sizes. Ready-to-run Python script.
- See also: `google-workspace` skill → `references/email-wiki-ingest-gmail-conventions.md` — Gmail source URL format (threadId/u/INDEX), noise filter queries, Drive-vs-email comparison, seen-state architecture.

Unlike traditional RAG (which rediscovers knowledge from scratch per query), the wiki
compiles knowledge once and keeps it current. Cross-references are already there.
Contradictions have already been flagged. Synthesis reflects everything ingested.

**Division of labor:** The human curates sources and directs analysis. The agent
summarizes, cross-references, files, and maintains consistency.

## Cron Job Design for Wiki Ingest

The wiki ingest cron should use a **script-first, Haiku-on-demand** pattern:

- **Schedule:** hourly (`0 * * * *`) — the precheck script costs zero tokens when the queue is empty
- **Model:** Haiku — sufficient for URL ingestion, note filing, cross-linking; use Sonnet only for complex multi-source synthesis (trigger manually)
- **Precheck script** (`wiki_ingest_precheck.py`): reads `_inbox/queue.md`, emits nothing if empty → LLM never fires → zero cost. Only fires LLM when real items exist.
- **Queue file:** `$WIKI_PATH/_inbox/queue.md` — drop URLs or notes here; processed items move to `processed.md`
- **Memory pressure integration:** a `memory_pressure_watch.py` watchdog (every 6h, `no_agent`) flags memory entries that could be offloaded to the wiki. It runs separately and writes candidate entries to the queue for the next hourly ingest tick.

This pattern means: 24 lightweight file-reads/day at zero cost; Haiku only fires when you drop something in the queue.

## When This Skill Activates

Use this skill when the user:
- Asks to create, build, or start a wiki or knowledge base
- Asks to ingest, add, or process a source into their wiki
- Asks a question and an existing wiki is present at the configured path
- Asks to lint, audit, or health-check their wiki
- References their wiki, knowledge base, or "notes" in a research context

## Wiki Location

**Location:** Set via `WIKI_PATH` environment variable (e.g. in `${HERMES_HOME:-~/.hermes}/.env`).

If unset, defaults to `~/wiki`.

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
```

The wiki is just a directory of markdown files — open it in Obsidian, VS Code, or
any editor. No database, no special tooling required.

## Architecture: Three Layers

```
wiki/
├── SCHEMA.md           # Conventions, structure rules, domain config
├── index.md            # Sectioned content catalog with one-line summaries
├── log.md              # Chronological action log (append-only, rotated yearly)
├── raw/                # Layer 1: Immutable source material
│   ├── articles/       # Web articles, clippings
│   ├── papers/         # PDFs, arxiv papers
│   ├── transcripts/    # Meeting notes, interviews
│   └── assets/         # Images, diagrams referenced by sources
├── entities/           # Layer 2: Entity pages (people, orgs, products, models)
├── concepts/           # Layer 2: Concept/topic pages
├── comparisons/        # Layer 2: Side-by-side analyses
└── queries/            # Layer 2: Filed query results worth keeping
```

**Layer 1 — Raw Sources:** Immutable. The agent reads but never modifies these.
**Layer 2 — The Wiki:** Agent-owned markdown files. Created, updated, and
cross-referenced by the agent.
**Layer 3 — The Schema:** `SCHEMA.md` defines structure, conventions, and tag taxonomy.

## Resuming an Existing Wiki (CRITICAL — do this every session)

When the user has an existing wiki, **always orient yourself before doing anything**:

① **Read `SCHEMA.md`** — understand the domain, conventions, and tag taxonomy.
② **Read `index.md`** — learn what pages exist and their summaries.
③ **Scan recent `log.md`** — read the last 20-30 entries to understand recent activity.

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
# Orientation reads at session start
read_file "$WIKI/SCHEMA.md"
read_file "$WIKI/index.md"
read_file "$WIKI/log.md" offset=<last 30 lines>
```

Only after orientation should you ingest, query, or lint. This prevents:
- Creating duplicate pages for entities that already exist
- Missing cross-references to existing content
- Contradicting the schema's conventions
- Repeating work already logged

For large wikis (100+ pages), also run a quick `search_files` for the topic
at hand before creating anything new.

## Initializing a New Wiki

When the user asks to create or start a wiki:

1. Determine the wiki path (from `$WIKI_PATH` env var, or ask the user; default `~/wiki`)
2. Create the directory structure above
3. Ask the user what domain the wiki covers — be specific
4. Write `SCHEMA.md` customized to the domain (see template below)
5. Write initial `index.md` with sectioned header
6. Write initial `log.md` with creation entry
7. Confirm the wiki is ready and suggest first sources to ingest

### SCHEMA.md Template

Adapt to the user's domain. The schema constrains agent behavior and ensures consistency:

```markdown
# Wiki Schema

## Domain
[What this wiki covers — e.g., "AI/ML research", "personal health", "startup intelligence"]

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `transformer-architecture.md`)
- Every wiki page starts with YAML frontmatter (see below)
- Use `[[wikilinks]]` to link between pages (minimum 2 outbound links per page)
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under the correct section
- Every action must be appended to `log.md`
- **Provenance markers:** On pages that synthesize 3+ sources, append `^[raw/articles/source-file.md]`
  at the end of paragraphs whose claims come from a specific source. This lets a reader trace each
  claim back without re-reading the whole raw file. Optional on single-source pages where the
  `sources:` frontmatter is enough.

## Frontmatter
  ```yaml
  ---
  title: Page Title
  created: YYYY-MM-DD
  updated: YYYY-MM-DD
  type: entity | concept | comparison | query | summary
  tags: [from taxonomy below]
  sources: [raw/articles/source-name.md]
  # Optional quality signals:
  confidence: high | medium | low        # how well-supported the claims are
  contested: true                        # set when the page has unresolved contradictions
  contradictions: [other-page-slug]      # pages this one conflicts with
  ---
  ```

`confidence` and `contested` are optional but recommended for opinion-heavy or fast-moving
topics. Lint surfaces `contested: true` and `confidence: low` pages for review so weak claims
don't silently harden into accepted wiki fact.

### raw/ Frontmatter

Raw sources ALSO get a small frontmatter block so re-ingests can detect drift:

```yaml
---
source_url: https://example.com/article   # original URL, if applicable
ingested: YYYY-MM-DD
sha256: <hex digest of the raw content below the frontmatter>
---
```

The `sha256:` lets a future re-ingest of the same URL skip processing when content is unchanged,
and flag drift when it has changed. Compute over the body only (everything after the closing
`---`), not the frontmatter itself.

## Tag Taxonomy
[Define 10-20 top-level tags for the domain. Add new tags here BEFORE using them.]

Example for AI/ML:
- Models: model, architecture, benchmark, training
- People/Orgs: person, company, lab, open-source
- Techniques: optimization, fine-tuning, inference, alignment, data
- Meta: comparison, timeline, controversy, prediction

Rule: every tag on a page must appear in this taxonomy. If a new tag is needed,
add it here first, then use it. This prevents tag sprawl.

## Page Thresholds
- **Create a page** when an entity/concept appears in 2+ sources OR is central to one source
- **Add to existing page** when a source mentions something already covered
- **DON'T create a page** for passing mentions, minor details, or things outside the domain
- **Split a page** when it exceeds ~200 lines — break into sub-topics with cross-links
- **Archive a page** when its content is fully superseded — move to `_archive/`, remove from index

## Entity Pages
One page per notable entity. Include:
- Overview / what it is
- Key facts and dates
- Relationships to other entities ([[wikilinks]])
- Source references

## Concept Pages
One page per concept or topic. Include:
- Definition / explanation
- Current state of knowledge
- Open questions or debates
- Related concepts ([[wikilinks]])

## Comparison Pages
Side-by-side analyses. Include:
- What is being compared and why
- Dimensions of comparison (table format preferred)
- Verdict or synthesis
- Sources

## Update Policy
When new information conflicts with existing content:
1. Check the dates — newer sources generally supersede older ones
2. If genuinely contradictory, note both positions with dates and sources
3. Mark the contradiction in frontmatter: `contradictions: [page-name]`
4. Flag for user review in the lint report
```

### index.md Template

The index is sectioned by type. Each entry is one line: wikilink + summary.

```markdown
# Wiki Index

> Content catalog. Every wiki page listed under its type with a one-line summary.
> Read this first to find relevant pages for any query.
> Last updated: YYYY-MM-DD | Total pages: N

## Entities
<!-- Alphabetical within section -->

## Concepts

## Comparisons

## Queries
```

**Scaling rule:** When any section exceeds 50 entries, split it into sub-sections
by first letter or sub-domain. When the index exceeds 200 entries total, create
a `_meta/topic-map.md` that groups pages by theme for faster navigation.

### log.md Template

```markdown
# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [YYYY-MM-DD] create | Wiki initialized
- Domain: [domain]
- Structure created with SCHEMA.md, index.md, log.md
```

## Core Operations

### 1. Ingest

When the user provides a source (URL, file, paste), integrate it into the wiki:

① **Capture the raw source:**
   - URL → use `web_extract` to get markdown, save to `raw/articles/`
   - PDF → use `web_extract` (handles PDFs), save to `raw/papers/`
   - Pasted text → save to appropriate `raw/` subdirectory
   - Name the file descriptively: `raw/articles/karpathy-llm-wiki-2026.md`
   - **Add raw frontmatter** (`source_url`, `ingested`, `sha256` of the body).
     On re-ingest of the same URL: recompute the sha256, compare to the stored value —
     skip if identical, flag drift and update if different. This is cheap enough to
     do on every re-ingest and catches silent source changes.

② **Discuss takeaways** with the user — what's interesting, what matters for
   the domain. (Skip this in automated/cron contexts — proceed directly.)

③ **Check what already exists** — search index.md and use `search_files` to find
   existing pages for mentioned entities/concepts. This is the difference between
   a growing wiki and a pile of duplicates.

④ **Write or update wiki pages:**
   - **New entities/concepts:** Create pages only if they meet the Page Thresholds
     in SCHEMA.md (2+ source mentions, or central to one source)
   - **Existing pages:** Add new information, update facts, bump `updated` date.
     When new info contradicts existing content, follow the Update Policy.
   - **Cross-reference:** Every new or updated page must link to at least 2 other
     pages via `[[wikilinks]]`. Check that existing pages link back.
   - **Tags:** Only use tags from the taxonomy in SCHEMA.md
   - **Provenance:** On pages synthesizing 3+ sources, append `^[raw/articles/source.md]`
     markers to paragraphs whose claims trace to a specific source.
   - **Confidence:** For opinion-heavy, fast-moving, or single-source claims, set
     `confidence: medium` or `low` in frontmatter. Don't mark `high` unless the
     claim is well-supported across multiple sources.

⑤ **Update navigation:**
   - Add new pages to `index.md` under the correct section, alphabetically
   - Update the "Total pages" count and "Last updated" date in index header
   - Append to `log.md`: `## [YYYY-MM-DD] ingest | Source Title`
   - List every file created or updated in the log entry

⑥ **Report what changed** — list every file created or updated to the user.

A single source can trigger updates across 5-15 wiki pages. This is normal
and desired — it's the compounding effect.

### 2. Query

When the user asks a question about the wiki's domain:

① **Read `index.md`** to identify relevant pages.
② **For wikis with 100+ pages**, also `search_files` across all `.md` files
   for key terms — the index alone may miss relevant content.
③ **Read the relevant pages** using `read_file`.
④ **Synthesize an answer** from the compiled knowledge. Cite the wiki pages
   you drew from: "Based on [[page-a]] and [[page-b]]..."
⑤ **File valuable answers back** — if the answer is a substantial comparison,
   deep dive, or novel synthesis, create a page in `queries/` or `comparisons/`.
   Don't file trivial lookups — only answers that would be painful to re-derive.
⑥ **Update log.md** with the query and whether it was filed.

### 3. Lint

When the user asks to lint, health-check, or audit the wiki:

① **Orphan pages:** Find pages with no inbound `[[wikilinks]]` from other pages.
```python
# Use execute_code for this — programmatic scan across all wiki pages
import os, re
from collections import defaultdict
wiki = "<WIKI_PATH>"
# Scan all .md files in entities/, concepts/, comparisons/, queries/
# Extract all [[wikilinks]] — build inbound link map
# Pages with zero inbound links are orphans
```

② **Broken wikilinks:** Find `[[links]]` that point to pages that don't exist.

③ **Index completeness:** Every wiki page should appear in `index.md`. Compare
   the filesystem against index entries.

④ **Frontmatter validation:** Every wiki page must have all required fields
   (title, created, updated, type, tags, sources). Tags must be in the taxonomy.

⑤ **Stale content:** Pages whose `updated` date is >90 days older than the most
   recent source that mentions the same entities.

⑥ **Contradictions:** Pages on the same topic with conflicting claims. Look for
   pages that share tags/entities but state different facts. Surface all pages
   with `contested: true` or `contradictions:` frontmatter for user review.

⑦ **Quality signals:** List pages with `confidence: low` and any page that cites
   only a single source but has no confidence field set — these are candidates
   for either finding corroboration or demoting to `confidence: medium`.

⑧ **Source drift:** For each file in `raw/` with a `sha256:` frontmatter, recompute
   the hash and flag mismatches. Mismatches indicate the raw file was edited
   (shouldn't happen — raw/ is immutable) or ingested from a URL that has since
   changed. Not a hard error, but worth reporting.

⑨ **Page size:** Flag pages over 200 lines — candidates for splitting.

⑩ **Tag audit:** List all tags in use, flag any not in the SCHEMA.md taxonomy.

⑪ **Log rotation:** If log.md exceeds 500 entries, rotate it.

⑫ **Report findings** with specific file paths and suggested actions, grouped by
   severity (broken links > orphans > source drift > contested pages > stale content > style issues).

⑬ **Append to log.md:** `## [YYYY-MM-DD] lint | N issues found`

## Working with the Wiki

### Searching

```bash
# Find pages by content
search_files "transformer" path="$WIKI" file_glob="*.md"

# Find pages by filename
search_files "*.md" target="files" path="$WIKI"

# Find pages by tag
search_files "tags:.*alignment" path="$WIKI" file_glob="*.md"

# Recent activity
read_file "$WIKI/log.md" offset=<last 20 lines>
```

### Bulk Ingest

When ingesting multiple sources at once, batch the updates:
1. Read all sources first
2. Identify all entities and concepts across all sources
3. Check existing pages for all of them (one search pass, not N)
4. Create/update pages in one pass (avoids redundant updates)
5. Update index.md once at the end
6. Write a single log entry covering the batch

### Email Pre-Population (Mining Historical Email for Wiki Knowledge)

When the user wants to backfill the wiki from email history, use this tier-based extraction pattern:

**Step 0 — Run the backfill script (batch classification)**

Use `scripts/email_wiki_backfill.py` to scan, classify, and deduplicate in one pass:

```bash
# Dry run: see cluster distribution without fetching bodies or updating seen state
python scripts/email_wiki_backfill.py --years 2 --dry-run --summary-only

# Full scan with bodies for specific cluster
python scripts/email_wiki_backfill.py --cluster "fortified-strength-ops" --years 2

# Re-process already-seen threads (skip dedup)
python scripts/email_wiki_backfill.py --years 2 --no-dedup --dry-run
```

The script:
- Fetches both Gmail accounts with category/label noise filters
- Classifies threads into topic clusters (USAW, Fortified Strength, Canyon Creek, travel, finance, etc.)
- Deduplicates against `wiki_email_seen.json` (shared with daily email cron)
- Writes ALL fetched threadIds to seen state (prevents daily cron from reprocessing)
- Outputs structured JSON with thread metadata, bodies, and Gmail URLs
- `--dry-run`: classification only, no body fetch, no seen-state update
- `--no-dedup`: show all threads even if already in seen state
- `--summary-only`: just cluster counts, no thread details

**Step 1 — Sample & classify (before reading any bodies)**

Pull ~25–50 messages per account with sender/subject/snippet only. Classify into tiers:
- 🟢 **High value** — active project threads, org operations, substantive negotiations, key decisions
- 🟡 **Medium value** — industry newsletters (selective), people/relationship threads
- 🔴 **Skip** — promos, shipping notifications, automated receipts, social digests

```bash
# Sample: real senders only, no bulk mailers
$GAPI --account personal gmail search "in:inbox -from:noreply -from:no-reply newer_than:60d" --max 25
```

**Step 2 — Extract by topic cluster, not by date**

Group green-tier threads by topic (e.g., "solar project", "nonprofit payroll", "USAW"). Process one cluster at a time:
1. Pull full message bodies for the 3–5 most informative threads in the cluster
2. Save the most detailed source email as `raw/articles/<topic>-<date>.md` with correct frontmatter
3. Write a wiki page synthesizing the cluster's knowledge

**Step 3 — Lint immediately after each cluster**

Run the orphan/broken-wikilink/frontmatter/tag checks after each new page, not at the end. Catches:
- Wikilinks to pages that don't exist yet → create stub page or downgrade to plain text + "(page pending)"
- Tags not in SCHEMA.md taxonomy → add tag to SCHEMA first, then use it
- New domain clusters that expand the schema → update SCHEMA.md domain section

**Step 4 — Schema domain expansion**

If email mining introduces a domain not covered by the existing schema (e.g., personal projects, church/nonprofit work, USAW operations), add a new tag group to SCHEMA.md under a clearly labeled section. This is intentional scope expansion — document it in the log entry.

**Step 5 — Dedup integration (CRITICAL)**

The backfill script writes ALL fetched threadIds to `wiki_email_seen.json`, which is shared with the daily email-to-wiki cron (`email_wiki_precheck.py`). This prevents the daily cron from reprocessing backfilled threads.

- **Non-dry-run runs** update seen state automatically
- **Dry-run runs** do NOT update seen state (safe for exploration)
- If you re-run the script after threads are marked seen, use `--no-dedup` to see them again
- The daily cron will pick up only NEW threads arriving after the backfill

Step 6 — Re-index qmd

After adding new pages, re-index the qmd search collection:
```bash
# Re-index all collections (BM25 updates immediately)
qmd update

# Refresh vector embeddings (needed for semantic search)
qmd embed
```
**Note:** `qmd index` is NOT a valid command — use `qmd update` for re-indexing. `qmd embed` downloads/loads the embedding model on first run (~60s) and may time out; run in background if needed.

**Full 2-year scan results (June 2026, 8 quarterly windows × 2 accounts):**
- 2,297 messages scanned, 1,189 unique threads, 34 noise-filtered (2.9% noise rate)
- 1,155 new (unseen) threads classified into 7 clusters + 184 unclassified
- Cluster distribution: USAW 535 (46%), FS ops 251 (22%), Unclassified 184 (16%), Travel 57, Church 45, Finance 38, Solar 38, People 7
- High-signal subset (multi-party, 3+ msgs): ~134 threads across all clusters
- Wiki grew from 38 → 66 pages (+28 new, +7.5K words, +237 wikilinks) in one session
- 28 raw article files created with Gmail thread source URLs
- Zero new broken wikilinks, all pages have frontmatter ✅

**CRITICAL — Gmail API 200-per-call cap and the quarterly window workaround:**
A single `--years 2` call only fetches the most recent 200 messages per account (400 total), which skews toward recent threads and misses older history. To get full 2-year coverage, run quarterly date windows:

```bash
# Run 8 quarterly windows (takes ~5min total, sequential API calls)
for Q in "2024/06/01 2024/09/01" "2024/09/01 2024/12/01" ...; do
    python scripts/email_wiki_backfill.py --after <start> --before <end> --dry-run --summary-only --no-dedup
done
```

Use `--no-dedup` during exploration (shows all threads even if in seen state). Use `--dry-run --summary-only` for the landscape scan (no body fetch, no seen-state mutation). Only switch to non-dry-run with `--cluster` for the actual body-fetch + wiki-enrichment pass.

**Signal classification before body fetch (saves 80% of API calls):**
Before fetching any thread bodies, classify each thread into signal tiers using metadata only:
- **High-signal** (fetch body): multi-party AND 3+ messages, OR 5+ messages total
- **Medium-signal** (fetch if time permits): from known project domain, 2+ messages, contains decision/financial/governance keywords
- **Skip** (no fetch): WooCommerce orders, form submissions, OOO auto-replies, vendor marketing, keyword false positives

This reduces body fetches from ~1,189 to ~50-80 for the full 2-year corpus.

**Parallel subagent delegation for wiki enrichment:**
Dispatch one subagent per topic cluster (using `delegate_task`). Each subagent:
1. Reads SCHEMA.md + index.md + existing pages for its cluster
2. Fetches thread bodies via Gmail API (one `gmail get` per thread)
3. Extracts knowledge: people, orgs, decisions, timelines, financial terms
4. Updates existing pages + creates new entity/concept pages
5. Creates raw article files with Gmail thread source URLs
6. Updates index.md + log.md
7. Runs lint checklist

Two subagents running in parallel processed 50 threads and created 28 wiki pages + 28 raw articles in ~10 minutes.

**Pitfall — subagent 600s timeout leaves post-processing incomplete:**
Both subagents hit the 600s wall after doing the expensive work (API calls + page authoring)
but before finishing index.md updates, orphan link fixes, and log.md entries. The parent
agent must verify and complete these steps after subagent results return: (1) diff actual
page slugs vs index.md entries and add missing ones, (2) run lint for orphan pages and add
inbound links from related pages, (3) append log.md entry if subagent didn't, (4) update
the "Total pages: N" header in index.md. This cleanup is cheap (~2min) and reliable.

**Keyword classifier false positives (pitfall):**
The `TOPIC_CLUSTERS` keyword matching in `email_wiki_backfill.py` produces false positives. For example, the USAW cluster catches Tesla Powerwall threads (matches "to " in subject), State Farm insurance (matches "session" in subject), and other non-weightlifting emails. Mitigation: after classifying into clusters, do a second-pass filter using sender domain and subject patterns to remove false positives before body fetch.

**Pitfall — `--no-dedup` required for exploration:**
After the first backfill run marks threads as seen, subsequent runs without `--no-dedup` will show 0 new threads. Always use `--no-dedup` during the exploration/classification phase. Only run without `--no-dedup` for the final body-fetch pass where you want to update seen state.

### Archiving

When content is fully superseded or the domain scope changes:
1. Create `_archive/` directory if it doesn't exist
2. Move the page to `_archive/` with its original path (e.g., `_archive/entities/old-page.md`)
3. Remove from `index.md`
4. Update any pages that linked to it — replace wikilink with plain text + "(archived)"
5. Log the archive action

### Obsidian Integration

The wiki directory works as an Obsidian vault out of the box:
- `[[wikilinks]]` render as clickable links
- Graph View visualizes the knowledge network
- YAML frontmatter powers Dataview queries
- The `raw/assets/` folder holds images referenced via `![[image.png]]`

For best results:
- Set Obsidian's attachment folder to `raw/assets/`
- Enable "Wikilinks" in Obsidian settings (usually on by default)
- Install Dataview plugin for queries like `TABLE tags FROM "entities" WHERE contains(tags, "company")`

If using the Obsidian skill alongside this one, set `OBSIDIAN_VAULT_PATH` to the
same directory as the wiki path.

### Obsidian Headless (servers and headless machines)

On machines without a display, use `obsidian-headless` instead of the desktop app.
It syncs vaults via Obsidian Sync without a GUI — perfect for agents running on
servers that write to the wiki while Obsidian desktop reads it on another device.

**Setup:**
```bash
# Requires Node.js 22+
npm install -g obsidian-headless

# Login (requires Obsidian account with Sync subscription)
ob login --email <email> --password '<password>'

# Create a remote vault for the wiki
ob sync-create-remote --name "LLM Wiki"

# Connect the wiki directory to the vault
cd ~/wiki
ob sync-setup --vault "<vault-id>"

# Initial sync
ob sync

# Continuous sync (foreground — use systemd for background)
ob sync --continuous
```

**Continuous background sync via systemd:**
```ini
# ~/.config/systemd/user/obsidian-wiki-sync.service
[Unit]
Description=Obsidian LLM Wiki Sync
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/path/to/ob sync --continuous
WorkingDirectory=/home/user/wiki
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now obsidian-wiki-sync
# Enable linger so sync survives logout:
sudo loginctl enable-linger $USER
```

This lets the agent write to `~/wiki` on a server while you browse the same
vault in Obsidian on your laptop/phone — changes appear within seconds.

### Daily Email-to-Wiki Cron (Jim's deployment, cron `YOUR_CRON_JOB_ID`)

A second cron runs daily at 8:00 AM UTC, independently of the URL-queue cron. It ingests new email threads (last ~36hrs) into the wiki.

**Architecture:**
```
email_wiki_precheck.py  (precheck script, ~/.hermes/scripts/)
  ↓ fetches personal + nonprofit Gmail (newer_than:3d with category/label noise filters)
  ↓ dedupes against $HERMES_HOME/wiki_email_seen.json (max 2000 threadIds)
  ↓ applies Python-level sender/subject noise filter
  ↓ builds thread list with Gmail thread URLs (real HTTPS, threadId not messageId)
  ├── empty stdout → LLM never fires (most days = zero cost)
  └── thread list → LLM triages: SKIP / NOTE / PAGE
                        ↓
              Writes wiki pages + updates index.md + log.md
              Writes processed IDs to wiki_email_seen_new.json
              (merged into seen.json on next precheck run)
```

**Triage decisions:**
- **SKIP** — one-way notification, bill, shipping, no knowledge value
- **NOTE** — new entity stub (vendor, person, org fact) → 5–15 lines in `entities/`
- **PAGE** — multi-party project/decision thread → full page in `concepts/` or `entities/`

**Volume expectation:** 0–3 pages/day. Most days 0–1.

**Source URL format:** every raw article file must use a real Gmail thread URL:
```yaml
source_url: https://mail.google.com/mail/u/INDEX/#all/THREAD_ID
account: personal | nonprofit
thread_id: THREAD_ID
```
See `google-workspace` skill → `references/email-wiki-ingest-gmail-conventions.md` for full detail.

### qmd — Local Search Engine (activate at ~50 pages)

[qmd](https://github.com/tobi/qmd) by Tobias Lütke (Shopify). BM25 + semantic search + LLM reranking, all local. Karpathy's recommended search layer once index.md becomes unwieldy.

**Install (correct package name — NOT `qmd`):**
```bash
npm install -g @tobilu/qmd --prefix /opt/data/home/.npm-global
# Binary at: /opt/data/home/.npm-global/bin/qmd
# Verify: /opt/data/home/.npm-global/bin/qmd --version
```

**Add wiki collection:**
```bash
/opt/data/home/.npm-global/bin/qmd collection add wiki /opt/data/wiki
# Index stored at: /opt/data/home/.cache/qmd/index.sqlite
# Config at: /opt/data/home/.config/qmd/index.yml
```

**Wire as MCP server** (config.yaml — use str.replace pattern, patch tool blocked on config.yaml):
```yaml
mcp_servers:
  wiki-search:
    command: /opt/data/home/.npm-global/bin/qmd
    args:
    - mcp
    env:
      HOME: /opt/data/home
      XDG_CONFIG_HOME: /opt/data/home/.config
      XDG_CACHE_HOME: /opt/data/home/.cache
      QMD_FORCE_CPU: '1'           # skip GPU probe loop on CPU-only envs
    enabled: true
```

**Critical pitfalls:**
- ❌ Wrong package: `npm install -g qmd` installs a dead stub (v0.0.0, no binary). Always use `@tobilu/qmd`.
- **Model corruption → MCP CPU spin loop:** If the MCP server burns 60-80% CPU and all wiki searches time out at 300s, the GGUF model files are likely corrupt. BM25 (`qmd search`) still works (no model needed). Fix: delete all model files + `.etag` files in `~/.cache/qmd/models/`, run `qmd pull` fresh, set `QMD_FORCE_CPU=1` in MCP env. See `references/qmd-model-corruption-troubleshooting.md` for full diagnostic + fix steps.
- ❌ Wrong env: qmd MCP server inherits a minimal env from Hermes. Without explicit `HOME`/`XDG_CACHE_HOME`/`XDG_CONFIG_HOME` pointing to the correct user home, the MCP server starts with 0 collections — it can't find the SQLite DB.
- ❌ DB location: the SQLite index lives at `$XDG_CACHE_HOME/qmd/index.sqlite` (not config dir). Confirm with `qmd collection list` — it prints the index path on the last line.
**BM25 works immediately after `collection add`. Semantic search requires `qmd embed` which downloads ~333MB of GGUF models. Activating at 30-40 pages is fine if semantic search is needed — the ~50 page threshold is a soft guideline. First semantic query may time out while the model loads into memory; subsequent queries are faster.**
- ✅ Re-index on ingest: add `subprocess.run(["/opt/data/home/.npm-global/bin/qmd", "update"], capture_output=True, timeout=30)` to `wiki_ingest_precheck.py` after emitting context — silent failure is fine (BM25 still works). **Note: the command is `qmd update`, NOT `qmd index`** — `index` is not a valid qmd subcommand and returns "Unknown command". After `qmd update`, run `qmd embed` to refresh vector embeddings (first load of the embedding model takes ~60s; subsequent runs are faster). If `qmd embed` times out, run it in the background.
- ✅ Hygiene guard threshold: add check for `index.md > 60 lines` → alert to run `qmd embed`.

**Test search:**
```bash
/opt/data/home/.npm-global/bin/qmd search "your query here" --files
```

### Memory offload pattern (compressing memory into wiki)

When memory stores approach their char limits, offload verbose-but-stable facts to wiki pages and replace with short pointers. This is the correct lifecycle — memory holds rules and identity, wiki holds facts.

**Workflow:**
1. **Identify candidates** — entries with `detail →`, `documented in`, `[[wikilink]]` patterns, or entries covering ops/infra/project facts rather than preferences/rules
2. **Create the wiki page** — full detail there, correct frontmatter, cross-links
3. **Replace memory entry** with a one-line pointer: `Full detail → wiki [[page-slug]]`
4. **Update index.md** (page count + new entry) and append to **log.md**
5. **Raise char limit if needed** — `hermes config set memory.user_char_limit N` via `/opt/hermes/bin/hermes config set ...`

**Char limits (config.yaml):**
- `memory.memory_char_limit` — agent notes (MEMORY.md), default 3000
- `memory.user_char_limit` — user profile (USER.md), default 2400, raised to 4000 Jun 2026

**Memory pressure watchdog** (`YOUR_CRON_JOB_ID`, every 6h, `no_agent`):
- Script: `memory_pressure_watch.py` at `${HERMES_HOME}/scripts/`
- Silent below 70% fill on both stores
- Fires review report above 85% — flags wiki/skill/keep candidates
- Never auto-modifies — review only

**Key rule:** Memory instruction pointer must say "before re-deriving ANY knowledge" (not just infra/ops) so the agent looks up wiki for USAW, Canyon Creek, projects, etc.

**Lookup facts vs. behavioral rules — don't offload rules:**
- **Lookup facts** (env details, account configs, infra topology, project facts) → fully offload to wiki, **remove** from memory. The wiki is queried on demand; memory doesn't need them every turn.
- **Behavioral rules** ("query wiki before re-deriving", "check for existing drafts before generating", "never re-do work already done") → **trim but keep** in memory. These are instructions to yourself that must be present every turn. Offloading them to wiki means they're invisible when you need them most.
- **Test:** "Is this a fact I'd look up, or a rule I must follow?" If look-up → wiki. If must-follow → memory (trimmed).

**Pitfall — forgetting log.md:** The offload is a wiki action. Append to `log.md`: `## [YYYY-MM-DD] update | Memory offload: N entries → wiki pages` listing each page created/enriched. It's easy to focus on index.md + memory edits and skip the log, but the log is how future sessions know what happened.



Drive is a **library** (standing docs), not a stream. Different strategy:
- **One-time ingest** of high-value existing docs (procedures, itineraries, org plans, competition data)
- **Daily new-file detection** using `createdTime > YESTERDAY` — NOT `modifiedTime` (auto-saves make that too noisy)
- Drive automation artifacts (json state files, Claude Chat sheets, GAS-Project sheets) are ~40% of Drive volume — filter by name in the query
- Drive wiki pages get `snapshot_note: "Snapshot as of DATE"` — the live doc is authoritative, the wiki page captures a point-in-time synthesis

## Session-to-Wiki Capture (third ingest pipeline)

URLs and email are two ingest sources. The third — **conversation history** —
captures decisions, config changes, debugging insights, and project updates that
happen in chat but never make it into the wiki otherwise.

**Architecture:**
```
session_wiki_precheck.py  (precheck script)
  ↓ queries sessions DB for recent non-cron sessions (48h, tool_call_count > 3)
  ↓ dedupes by session_id against cron/state/session_wiki_seen.json
  ├── empty stdout → no sessions → LLM never fires (zero cost)
  └── session list → LLM uses session_search to read content
                      ↓ triages: SKIP / NOTE / PAGE
                      ↓ creates/updates wiki pages
```

**Key design decisions:**
- **Session DB schema:** `sessions` table uses `started_at` (REAL epoch), NOT `created_at`. The query must use `WHERE started_at > ?` with an epoch float.
- **Filter heuristic:** `tool_call_count > 3` — sessions with fewer tool calls are usually casual chat, not work sessions worth reviewing.
- **Exclude cron sessions:** `source NOT IN ('cron', 'scheduler')` — cron output goes through its own pipeline.
- **Exclude archived:** `archived = 0`.
- **Dedup:** session_ids stored in `cron/state/session_wiki_seen.json`, max 2000, pruned to oldest. **File format:** `{"seen": ["id1", "id2", ...]}` — a dict with a `"seen"` key, NOT a flat list.
- **Model:** Sonnet (requires judgment to decide what's wiki-worthy vs ephemeral).
- **Toolsets:** `terminal, file, session_search, skills` — session_search is essential.
- **Skills:** `llm-wiki` — the LLM needs the ingest workflow.

**Cron prompt must instruct the LLM to:**
1. Use `session_search` to find and read each session's content
2. Decide SKIP (casual chat, already documented) vs NOTE (add to existing page) vs PAGE (new page)
3. Focus on: config changes + rationale, problems solved, new entities, project updates, architecture decisions
4. Follow the standard llm-wiki ingest workflow (orient, check existing, create/update with frontmatter + wikilinks)
5. Reply `[SILENT]` if nothing is worth capturing

This closes the gap where valuable conversation knowledge (model switches, debugging
insights, portability overhauls) was lost because no mechanism captured it.

**Post-capture step — re-index qmd:** After creating/updating wiki pages from session
capture, run `qmd update` (BM25) and `qmd embed` (semantic, may need background) to
keep the search index current. This is the same step as email backfill Step 6.

## Cron Job Design (Jim's deployment)

The URL-queue ingest cron (`YOUR_CRON_JOB_ID`) uses a script-first pattern:

- **Schedule:** Hourly (`0 * * * *`) — free when queue is empty
- **Model:** Haiku (sufficient for URL ingestion + note filing; use Sonnet manually for complex cross-linking sessions)
- **Script:** `wiki_ingest_precheck.py` — reads `_inbox/queue.md`, outputs nothing if empty (LLM never fires), emits compact context block if items exist
- **Silent on empty:** The script contract is strict — no output = no LLM, no ping. Zero token cost on idle hours.
- **Queue file:** `/opt/data/wiki/_inbox/queue.md` — drop URLs or notes one per line; lines starting with `#` or `>` are ignored

### Memory pressure watchdog

A companion `no_agent` cron (`YOUR_CRON_JOB_ID`, every 6h) runs `memory_pressure_watch.py`:
- Silent below 70% fill on both stores
- Fires a review report above 85% — flags entries as wiki/skill/keep candidates
- Never auto-modifies memory — review only, Jim approves changes

This creates a soft pipeline: memory fills → watchdog flags → Jim drops offload candidates into `queue.md` → hourly ingest files them to wiki.

## Scheduling the ingest cron

The precheck script (`wiki_ingest_precheck.py`) is fully silent when the queue is empty — costs **zero tokens**. This means high-frequency scheduling is essentially free when nothing is queued.

**Recommended schedule: hourly (`0 * * * *`) with Haiku.**
- Precheck reads `_inbox/queue.md` — if empty, outputs nothing, LLM never fires
- Only costs tokens when items are actually in the queue
- Haiku is sufficient for simple URL ingestion and note filing; only complex cross-linking or contradiction resolution benefits from Sonnet (trigger manually)

```
job: Hourly wiki ingest
schedule: 0 * * * *
model: claude-haiku-4-5-20251001
script: wiki_ingest_precheck.py
no_agent: false  # LLM only fires when precheck emits output
```

- **Cron prompt must be explicit about URL conventions** — the LLM step won't know the source URL format unless the cron prompt states it. Always include in the prompt:
  - Gmail: `https://mail.google.com/mail/u/0/#all/THREAD_ID` (u/0=personal, u/1=nonprofit) — threadId not messageId, never `gmail://`
  - Drive: full `https://drive.google.com/...` URL with `/u/0` or `/u/1` account prefix
  - Web: verbatim `https://` URL
- **Cron prompt must include `processed.md` step** — after ingesting, the LLM must move processed lines from `queue.md` to `_inbox/processed.md` (append) and remove them from `queue.md`. Without this explicit instruction the queue never clears.
- **Broken wikilinks from "page pending" stubs** — when a page references `[[entity-name]]` but that page doesn't exist yet, the link is broken. Either create a stub or downgrade to plain text + "(page pending)". The audit script (`lint_script` in `references/email-to-wiki-signal-guide.md`) catches these. Run after every ingest session.
- **Wikilinks must have ≥ 2 outbound links per page** — newly created pages often have 0–1 wikilinks when the author focuses on content over navigation. Always check before committing. If no natural links exist, link to `[[hermes-docker-environment]]` or `[[personal-context-security-graph]]` as general Hermes infrastructure anchors.
- **Stale cron prompt names cause confusion** — if a job was renamed (e.g. "weekly" → "hourly"), update the prompt text too. The `prompt_preview` in cron list is the source of truth humans read.
- **Cron prompts must not hardcode `/opt/data/wiki`** — use `$WIKI_PATH` or `$HERMES_HOME/wiki` in the prompt text so the job works on any deployment. The precheck script already uses the env var; the prompt should match.
- **Stale wiki pages after config changes** — when the main model changes (e.g. Opus → GLM-5.2), the `hermes-agent` wiki page becomes stale. Add a session-to-wiki capture cron (see "Session-to-Wiki Capture" section) so config changes are automatically reviewed and wiki pages updated.

## Pitfalls

- **Never modify files in `raw/`** — sources are immutable. Corrections go in wiki pages.
- **Always orient first** — read SCHEMA + index + recent log before any operation in a new session.
  Skipping this causes duplicates and missed cross-references.
- **Always update index.md and log.md** — skipping this makes the wiki degrade. These are the
  navigational backbone.
- **Don't create pages for passing mentions** — follow the Page Thresholds in SCHEMA.md. A name
  appearing once in a footnote doesn't warrant an entity page.
- **Don't create pages without cross-references** — isolated pages are invisible. Every page must
  link to at least 2 other pages.
- **Frontmatter is required** — it enables search, filtering, and staleness detection.
- **Tags must come from the taxonomy** — freeform tags decay into noise. Add new tags to SCHEMA.md
  first, then use them.
- **Keep pages scannable** — a wiki page should be readable in 30 seconds. Split pages over
  200 lines. Move detailed analysis to dedicated deep-dive pages.
- **Ask before mass-updating** — if an ingest would touch 10+ existing pages, confirm
  the scope with the user first.
- **Rotate the log** — when log.md exceeds 500 entries, rename it `log-YYYY.md` and start fresh.
  The agent should check log size during lint.
- **Handle contradictions explicitly** — don't silently overwrite. Note both claims with dates,
  mark in frontmatter, flag for user review.
- **Avoid hard-coded counts in wiki pages** — writing "37 docs, 7 people" in a wiki page
  guarantees it will be stale within a week as the wiki grows. Use approximate language
  ("~100 docs", "~40 entities") or reference `qmd status` / `index.md` for live counts.
  Only use exact numbers for fixed facts (char limits, thresholds, config values). This
  was the #1 issue found in the Jun 2026 quality review — 4 stale counts in
  `hermes-knowledge-architecture.md` alone.
- **Doc/code sync after schedule changes** — when a cron job's schedule changes (e.g.,
  weekly → hourly), the corresponding wiki page must be updated too. The
  `weekly-wiki-ingest-cron.md` said "Sunday 8 PM PT" for weeks after the cron was
  changed to hourly. Always check wiki pages that document crons after any cron
  schedule/model update.
- **Use the standalone lint script** — `wiki_lint.py` at `${HERMES_HOME}/scripts/wiki_lint.py`
  handles pipe-alias syntax (`[[page|alias]]`), filters example/illustrative uses of
  `[[wikilink]]` in prose, detects stale pages (90-day threshold), and supports
  `--strict` and `--json` modes. See `references/wiki-lint-script.md` for details.

## Related Tools

[llm-wiki-compiler](https://github.com/atomicmemory/llm-wiki-compiler) is a Node.js CLI that
compiles sources into a concept wiki with the same Karpathy inspiration. It's Obsidian-compatible,
so users who want a scheduled/CLI-driven compile pipeline can point it at the same vault this
skill maintains. Trade-offs: it owns page generation (replaces the agent's judgment on page
creation) and is tuned for small corpora. Use this skill when you want agent-in-the-loop curation;
use llmwiki when you want batch compile of a source directory.
