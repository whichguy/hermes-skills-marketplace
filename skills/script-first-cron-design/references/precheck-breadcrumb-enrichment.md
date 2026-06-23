# Precheck Breadcrumb Enrichment

Token-efficient signals extracted from metadata-only fields so the LLM agent
can triage WITHOUT fetching the full thread body in obvious cases. Proven on
the inbox-triage pipeline (Jun 2026): expected ~40-60% reduction in Gmail API
calls per tick for typical inbox composition.

## Problem

A precheck script that emits only metadata (id, threadId, from, subject, date,
labels) forces the LLM to fetch every thread body to make a triage decision.
For a 30-minute inbox-triage cron, that's 1 API call per thread × N threads per
tick — even when half the threads are obvious noise (newsletters, auto-confirm,
no-reply, "Jim already replied") that the LLM will immediately SKIP after
reading one line.

## Solution: Breadcrumbs

Extract compact pre-triage signals from metadata fields that are ALREADY in the
precheck payload (snippet, subject, from, labels, date). These cost zero extra
API calls — they're computed from data the precheck already fetched.

### Breadcrumb fields

| Field | Type | Source | What it tells the agent |
|---|---|---|---|
| `skip_hint` | `str \| None` | snippet+subject+from patterns | Pre-classified skip reason: `bulk/no-reply sender`, `transactional/auto-confirm`, `newsletter/digest`. If set, agent can SKIP without fetching. |
| `urgency` | `str \| None` | snippet+subject regex | `deadline` · `reminder` · `payment` · `scheduling` · `action`. If set, fetch first and prioritize. |
| `age` | `str \| None` | date field | Compact `2h` / `1d` / `3d` / `1w`. None if <6h (recent enough to not need an age breadcrumb). |
| `age_h` | `float \| None` | date field | Raw hours since send — for programmatic use. |
| `domain` | `str \| None` | from header | Sender domain for quick recognition without parsing the full From header. |
| `flags` | `list[str]` | Gmail labels | `IMPORTANT`, `STARRED`, `PROMO` subset. Fetch for context when IMPORTANT/STARRED. |
| `snippet` | `str` | Gmail snippet (120 chars) | Compacted whitespace + truncated. Just enough for triage — NOT the full body. |
| `depth` | `int` | hint (always 1) | Placeholder. Real depth requires a thread fetch. Agent should fetch when depth matters for decisions. |

### Detection patterns

**Urgency patterns** (regex on subject+snippet):
```python
URGENCY_PATTERNS = [
    (re.compile(r'\b(?:deadline|due|expires?|expiring|urgent|asap|action required)\b', re.I), 'deadline'),
    (re.compile(r'\b(?:reminder|follow.?up|past due|overdue|final notice)\b', re.I), 'reminder'),
    (re.compile(r'\b(?:invoice|payment|balance|statement|bill due|pay now)\b', re.I), 'payment'),
    (re.compile(r'\b(?:meeting|call|schedule|appointment|lunch|breakfast|coffee)\b', re.I), 'scheduling'),
    (re.compile(r'\b(?:confirm|confirmation|rsvp|please confirm|let me know|respond)\b', re.I), 'action'),
]
```

**Skip signals** (snippet patterns → obvious noise):
```python
SKIP_SNIPPET_PATTERNS = [
    re.compile(r'unsubscribe', re.I),
    re.compile(r'manage your notifications', re.I),
    re.compile(r'view this email in your browser', re.I),
    re.compile(r'no-?reply', re.I),
    re.compile(r'do not reply', re.I),
    re.compile(r'automated (message|email|notification)', re.I),
    re.compile(r'confirmation (number|code|id):', re.I),
    re.compile(r'tracking (number|id):', re.I),
    re.compile(r'your (order|shipment|delivery|statement|bill|receipt) (has been|is|was)', re.I),
]
```

**Bulk sender detection** (local part of email address):
```python
BULK_DOMAINS = {
    'noreply', 'no-reply', 'donotreply', 'do-not-reply',
    'mailer', 'notification', 'notify', 'alerts', 'auto',
    'noreply-spamdigest', 'googlegroups',
}
```

### Agent fast-path rules

Teach the agent (in the cron prompt) to use breadcrumbs as a fast-path:

1. `skip_hint` is set → SKIP without fetching (bulk/transactional/newsletter)
2. `thread_state=awaiting_reply` (latest msg from user) → SKIP (already replied)
3. `snippet` shows unsubscribe/auto-confirm → SKIP without fetching
4. `urgency` is set → fetch first, prioritize
5. `flags` includes IMPORTANT/STARRED → fetch for context
6. `depth≥3` → likely a negotiation/discussion → always fetch
7. **When in doubt, always fetch** — breadcrumbs are a fast-path, not a replacement

### Implementation pattern

Define breadcrumb functions in the primary precheck script, then import them
into sibling precheck scripts to avoid duplication:

```python
# inbox_triage_precheck.py — defines all breadcrumb functions
def compute_age_hours(msg): ...
def age_breadcrumb(hours): ...
def extract_domain(from_header): ...
def detect_urgency(snippet, subject): ...
def detect_skip_signals(snippet, subject, from_header): ...
def detect_label_flags(labels): ...
def compact_snippet(snippet, max_len=120): ...

# email_wiki_precheck.py — imports from sibling
from inbox_triage_precheck import (
    compute_age_hours, age_breadcrumb, extract_domain,
    detect_urgency, detect_skip_signals, detect_label_flags,
    compact_snippet,
)
```

### Compact snippet vs. full snippet

The Gmail API returns a `snippet` field (auto-generated preview, ~200 chars).
Previously, the inbox triage precheck omitted snippets entirely (forcing the
agent to fetch every thread). The breadcrumb pattern includes a **compacted
120-char snippet** — enough for the agent to recognize newsletter/auto-confirm
patterns without fetching, but not so much that it replaces the full body for
real triage decisions.

```python
def compact_snippet(snippet, max_len=120):
    if not snippet:
        return ''
    s = re.sub(r'\s+', ' ', snippet).strip()
    if len(s) <= max_len:
        return s
    return s[:max_len - 3].rstrip() + '…'
```

### Wake payload documentation

The `wake_payload()` note field must document every breadcrumb field so the
agent knows how to interpret them:

```python
'note': ('metadata+breadcrumbs; breadcrumb fields: depth(hint=1, fetch '
         'for real depth), age_h(hours float), age(compact 2h/1d/3d or '
         'null<6h), domain(sender domain), urgency(deadline/reminder/'
         'payment/scheduling/action or null), skip_hint(pre-classified '
         'skip reason or null — if set, likely SKIP without fetching), '
         'flags(IMPORTANT/STARRED/PROMO subset), snippet(120char compact '
         '— enough for triage); ... use breadcrumbs as fast-path: '
         'skip_hint set → SKIP without fetching; urgency set or flags '
         'IMPORTANT/STARRED → fetch first; thread_state=awaiting_reply '
         '→ SKIP (Jim already replied)'),
```

### Visual output format for triage reports

The triage prompt should specify a visual-but-compact output format using
emoji status chips:

```
📬 **Inbox Triage** · 3 thread(s)
🏠 **Jane Doe** · Re: Quick question · ✅ drafted [engagement: work/casual]
💪 **John Smith** · Contract redline review · 🚩 flagged: legal/contract
🏠 **noreply@github.com** · Your PR was merged · ⏭️ skipped: bulk/no-reply sender · 1d
_⚠️ nonprofit: draft_lookup_failed — no drafts for this account._
_Drafts only — nothing sent._
```

Status chips: ✅ drafted · 🚩 flagged · ⏭️ skipped. Age breadcrumb appended
after subject if >6h old. Errors use ⚠️ with italic. Footer in italics.

## Cross-pipeline sharing

When two precheck scripts cover overlapping territory (e.g. inbox_triage for
reply drafting and email_wiki for knowledge extraction), share the breadcrumb
functions via Python import rather than duplicating. The primary script
defines them; the sibling imports what it needs. This follows the same
shared-library pattern used for `email_utils.py` (PeopleResolver, EpisodeStore).

## Testing

Breadcrumb functions are pure (no I/O, no side effects) — test them in
isolation with `execute_code`:

```python
assert age_breadcrumb(3) is None       # <6h → None
assert age_breadcrumb(7) == '7h'
assert age_breadcrumb(25) == '1d'
assert extract_domain("John <john@example.com>") == "example.com"
assert detect_skip_signals("Click to unsubscribe", "Newsletter", "x@y.com") == 'transactional/auto-confirm'
assert detect_skip_signals("", "", "noreply@github.com") == 'bulk/no-reply sender'
```

Verify the full script compiles: `py_compile.compile('inbox_triage_precheck.py', doraise=True)`.