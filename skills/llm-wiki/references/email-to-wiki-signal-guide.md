# Email → Wiki Signal Guide

Condensed tier classification for mining email history into wiki knowledge.
Validated against Jim's personal + nonprofit inboxes (June 2026 pilot session).

## Signal Tiers

### 🟢 High Value — always mine

| Pattern | Examples | Wiki artifact |
|---|---|---|
| Active project threads (3+ reply chain, real people) | Canyon Creek Solar, Infinium contract | `concepts/<project>.md` + `raw/articles/` source |
| Org operations (vendors, payroll, compliance) | Fortified Strength Gusto/payroll, CalSavers, Charity Navigator | `entities/<org>.md` or `concepts/<topic>.md` |
| Substantive negotiations / decisions | Contract redlines, change orders, permit disputes | `raw/articles/<topic>-<date>.md` → update project page |
| People/relationship threads | USAW TOs, church leadership, donors | `entities/<person>.md` if recurring, else add to project page |
| Key one-way communications Jim wrote | Leadership briefings, board updates | High priority — these are Jim's synthesized knowledge |

### 🟡 Medium Value — selective

| Pattern | Notes |
|---|---|
| Industry newsletters (The Points Guy, Visual Capitalist) | Mine only for specific articles, not every issue. Drop URL in queue.md, let ingest cron handle. |
| Nonprofit sector newsletters (Foundation Group 501c3.org) | Mine specific articles on relevant topics (Direct Pay ITC, church tax law). |
| One-off event notifications (USAW schedule release) | Worth a quick extract if it contains data (schedules, results, rosters). |

### 🔴 Skip — never mine

- Shipping/delivery (UPS, FedEx, USPS)
- Retail promos (Rhone, Barbell Apparel, Alter Ego, Sticker Mule, Ministry of Supply)
- Auto-pay / statement notifications (Citi, Capital One, Vanguard, Apple receipts)
- Social digests (Nextdoor, Instagram suggestions)
- Spam/moderation digests (Google Groups spam reports)
- Duplicate sends (same email in both personal + nonprofit due to forwarding)
- Health/medical (per privacy policy — not stored without explicit user enable)

## Sampling Command

```bash
# Jim's accounts — use this as starting point for any backfill session
GAPI="uv run --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 python ${HERMES_HOME:-~/.hermes}/skills/productivity/google-workspace/scripts/google_api.py"

# Exclude obvious bulk mailers from sample
$GAPI --account personal gmail search "in:inbox -from:noreply -from:no-reply newer_than:60d" --max 25
$GAPI --account nonprofit gmail search "in:inbox newer_than:60d" --max 25

# Historical window (1-2 years back)
$GAPI --account personal gmail search "in:inbox -from:noreply after:2024/07/01 before:2025/07/01" --max 25
```

## Topic Clusters Found (Jim's 2-year backfill)

Approximate clusters, highest value first:

1. **Canyon Creek Solar** — complex project, $487K contract, 2 accounts involved, ITC/Direct Pay knowledge
2. **Fortified Strength operations** — payroll (Gusto), WooCommerce orders, PayPal payments, Charity Navigator, CalSavers compliance
3. **USAW weightlifting** — meet schedules, TO relationships, NCW results/participants
4. **Canyon Creek church org** — leadership (Travis Marsh, Kevin Timmons, Albert Shin), events, finance
5. **Infinium Solar** — vendor entity worth its own entity page
6. **Personal finance** — Vanguard, Capital One, Citi (LOW wiki value — skip details, just note accounts exist)
7. **Travel/logistics** — cruise ports, Colorado Springs NCW trips (Family Member involved)
8. **People entities** — Joe Monkowski (Pivotal Systems), Roger Pang (Infinium), Albert Shin, etc.

## Backfill Script

The `scripts/email_wiki_backfill.py` script automates Steps 1-2 above:

```bash
# Dry-run: classify only, no body fetch, no seen-state update
python scripts/email_wiki_backfill.py --years 2 --dry-run --summary-only

# Full fetch with bodies for one cluster
python scripts/email_wiki_backfill.py --cluster "fortified-strength-ops" --years 2

# Re-process seen threads (exploration mode)
python scripts/email_wiki_backfill.py --years 2 --no-dedup --dry-run
```

Key features:
- Writes ALL fetched threadIds to `wiki_email_seen.json` (shared with daily cron)
- `--dry-run` skips body fetch AND seen-state update (safe for exploration)
- `--no-dedup` shows all threads even if already in seen state
- Classifies into 7 topic clusters using keyword + sender matching
- Outputs JSON with thread metadata, bodies, and Gmail thread URLs

## Pilot Validated Findings (June 2026)

### Full 2-Year Quarterly Scan (June 2024 → June 2026)
- **Total messages fetched:** 2,297 (8 quarterly windows × 2 accounts × 200 max)
- **Unique threads:** 1,189
- **Noise rate after Gmail category filters:** 2.9% (34 of 1,189)
- **New (unseen) threads:** 1,155

### Cluster Distribution (full 2-year)
| Cluster | Threads | % | High-signal (multi-party 3+) |
|---|---|---|---|
| USAW | 535 | 46% | 84 |
| Fortified Strength ops | 251 | 22% | 30 |
| Unclassified | 184 | 16% | — |
| Travel/logistics | 57 | 5% | — |
| Canyon Creek church | 45 | 4% | — |
| Personal finance | 38 | 3% | — |
| Canyon Creek solar | 38 | 3% | 20 |
| People/relationships | 7 | 1% | — |

### Backfill Session Results (June 23, 2026)
- **Solar + FS ops clusters processed:** 50 high-signal threads fetched & wiki-enriched
- **Wiki growth:** 38 → 66 pages (+28 new), 17.8K → 25.3K words (+7.5K), 207 → 444 wikilinks (+237)
- **Broken links:** 16 → 9 (all 9 pre-existing in meta pages, zero new)
- **Raw article files created:** 28 with Gmail thread source URLs
- **Quality:** All pages have frontmatter ✅, all pages have ≥2 wikilinks ✅

### Key Optimizations Discovered
1. **Gmail API --max 200 cap** requires quarterly date windows for full coverage — single `--years 2` only fetches most recent 200 per account
2. **Keyword classifier has false positives** — USAW cluster catches Tesla, State Farm, insurance threads via "session"/"to" keyword matches. Need sender-domain filtering as a second pass.
3. **Body fetch is the bottleneck** — sequential `gmail get` calls take ~5s each. For 50 threads = ~4min. Parallel fetching would 3-4x throughput.
4. **Signal classification is critical** — pre-filtering to high-signal (multi-party, 3+ msgs) before body fetch saves 80% of API calls vs. fetching all threads
5. **Wiki quality is high** — subagents extract specific names, dates, dollar amounts, timelines, and decisions from email threads with proper source citations

## Raw Article Template (v2 — Rich Format)

The raw article is what the LLM writes from an email thread. The old format was
inconsistent — sometimes a bare text dump, sometimes a structured page. The new
template enforces visual hierarchy, metadata, and wiki connections.

### Template

```markdown
---
source_url: https://mail.google.com/mail/u/INDEX/#all/THREAD_ID
account: personal|nonprofit
thread_id: THREAD_ID
ingested: YYYY-MM-DD
signal_tier: high|medium|low
participants: [Name1, Name2, ...]
topics: [topic1, topic2]
---

# Descriptive Title — Topic + Date

> **TL;DR:** 1-2 sentence summary of what happened and why it matters.

## 📋 At a Glance

| Field | Value |
|-------|-------|
| Date | <date range> |
| Account | <personal/nonprofit> |
| Messages | <N> |
| Participants | <names> |
| Gmail Thread | [Open](<url>) |

## 👥 Participants

| Name | Role | Affiliation |
|------|------|-------------|
| <name> | <sender/reviewer/decision-maker> | <org/company> |

## 📜 Thread Narrative

Chronological summary — what was discussed, requested, decided.
Use sub-headings (###) for each key exchange or date milestone.

### <Date or topic milestone>
- <who said/did what>
- <key data: $ amounts, dates, contract terms>

## ✅ Decisions & Outcomes

- <Bullet list of concrete decisions, commitments, or outcomes>
- <If no decision yet, write "Pending — <what's blocking>">

## 💡 Key Insights

- <Non-obvious facts, cross-references, or context worth preserving>
- <Why this matters for the wiki / what page it connects to>

## 🔗 Wiki Connections

- Related: [[existing-wiki-slug]] — <how it relates>
- Should update: [[slug]] with <specific fact>
- May warrant new page: [[proposed-slug]] — <why>

## 🏷 Tags
`topic1` `topic2` `topic3`
```

### Key improvements over old format

| Feature | Old | New |
|---------|-----|-----|
| Summary | None or buried | TL;DR blockquote at top |
| Metadata | Inconsistent frontmatter | Structured: signal_tier, participants, topics |
| Quick scan | Read the whole thing | At a Glance table |
| People | Inline text | Participants table with role + affiliation |
| Narrative | Flat prose or bullet dump | Chronological with date milestones |
| Outcomes | Mixed into narrative | Dedicated Decisions & Outcomes section |
| Wiki links | Sometimes present, sometimes not | Mandatory Wiki Connections section |
| Tags | Sometimes present | Dedicated Tags section |

### Before/After Example

**BEFORE** (old format — `ccpc-solar-sunrun-buyout-feb2024.md`):
```markdown
---
source_url: https://mail.google.com/mail/u/0/#all/18da16ac20dced96
account: personal
thread_id: 18da16ac20dced96
ingested: 2026-06-23
---

Subject: Options to Purchase your Sunrun Solar System
From: CCD-EML Customer Care Cases (customercare@sunrun.com)
To: you@example.com
Date: Tue, 13 Feb 2024 07:42:24 +0000

Sunrun customer care contacted Jim about options to purchase his existing Sunrun solar system.
This is the earliest thread in the Canyon Creek solar cluster and relates to Jim's personal
residential Sunrun system (not the church project). Body was HTML-only (empty in text extraction).

Labels: IMPORTANT, CATEGORY_UPDATES, INBOX
```

**AFTER** (new rich format):
```markdown
---
source_url: https://mail.google.com/mail/u/0/#all/18da16ac20dced96
account: personal
thread_id: 18da16ac20dced96
ingested: 2026-06-23
signal_tier: low
participants: [Sunrun Customer Care, The User]
topics: [solar, sunrun, residential]
---

# Sunrun Buyout Offer — Feb 2024

> **TL;DR:** Sunrun offered Jim the option to purchase his residential solar system outright.
> This predates the Canyon Creek church solar project and relates to Jim's personal home system.

## 📋 At a Glance

| Field | Value |
|-------|-------|
| Date | Feb 13, 2024 |
| Account | personal |
| Messages | 1 |
| Participants | Sunrun Customer Care, The User |
| Gmail Thread | [Open](https://mail.google.com/mail/u/0/#all/18da16ac20dced96) |

## 👥 Participants

| Name | Role | Affiliation |
|------|------|-------------|
| Sunrun Customer Care | Sender | Sunrun |
| The User | Recipient | Homeowner |

## 📜 Thread Narrative

### Feb 13, 2024 — Sunrun buyout offer
- Sunrun customer care sent options to purchase the existing residential solar system
- Body was HTML-only (not extractable via text API)
- Labeled IMPORTANT by Gmail filters

## ✅ Decisions & Outcomes

- No response visible in this thread — likely a one-way notification
- Context: Jim later explored solar options for Canyon Creek church separately

## 💡 Key Insights

- This is the earliest thread in the solar cluster, establishing Jim's prior
  relationship with residential solar before the larger church project
- The Sunrun system on Jim's home is separate from the [[canyon-creek-solar-project]]

## 🔗 Wiki Connections

- Related: [[canyon-creek-solar-project]] — church solar project (different scope)
- Context: Jim's personal solar experience informed the church project evaluation

## 🏷 Tags
`solar` `sunrun` `residential` `one-way`
```

## Lint Checklist (run after each cluster)

```python
import re
from pathlib import Path
from collections import defaultdict

wiki = Path("/opt/data/wiki")
wiki_dirs = ["entities", "concepts", "comparisons", "queries"]
pages = {}
for d in wiki_dirs:
    for f in (wiki / d).rglob("*.md"):
        pages[Path(f).stem] = f.read_text()

# Broken wikilinks
all_links = defaultdict(set)
for slug, content in pages.items():
    all_links[slug] = set(re.findall(r'\[\[([^\]]+)\]\]', content))

for slug, links in all_links.items():
    for link in links:
        if link not in pages:
            print(f"BROKEN: [[{link}]] in {slug}")

# Orphans (no inbound links)
inbound = defaultdict(set)
for slug, links in all_links.items():
    for link in links: inbound[link].add(slug)
for slug in pages:
    if slug not in inbound:
        print(f"ORPHAN: {slug}")
```

Fix broken wikilinks by either: (a) creating the stub page, or (b) downgrading to plain text + "(page pending)". Don't leave broken `[[wikilinks]]` in committed pages.
