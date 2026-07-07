# Memory Pressure Watchdog Pattern

**Established:** 2026-06-21 session · **Updated:** 2026-07-04 (skill-matching overhaul + quality review)

## Pattern

A `no_agent` Python script that reads Hermes memory files directly, classifies entries
by offload destination, and **auto-offloads** candidates when pressure exceeds the high
threshold. Silent when stores are comfortable — costs zero tokens on most runs.

## Key design decisions

- **Two thresholds:** `LOW_THRESHOLD = 0.70` (stay silent below) and `HIGH_THRESHOLD = 0.85` (auto-offload above). Both must be evaluated — only act when at least one store exceeds HIGH.
- **Classification heuristics (simplified 2026-07-04):**
  - `WIKI_SIGNALS`: `["detail →", "documented in", "wiki concept", "[[", "see wiki", "ops notes", "deploy", "runtime", "qmd", "binary:", "version:", "v0.1", "v0.2"]`
  - `classify()` now returns only `"wiki"` or `"keep"` — the `"skill"` classification was removed. Skill matching runs against ALL entries via `match_skill_entry()`, not just "skill"-classified ones. The old `SKILL_SIGNALS` list (`["skill", "procedure", "workflow", ...]`) was dead code — it missed most procedural entries (they say "delegate", "verification", "kanban" — not "skill", "procedure", "workflow").
  - `PROCESS_SIGNALS` (module-level constant): `["delegate", "verification", "sdlc", "kanban", "eod", "cron", "google_api", "pragmatic", "long-running", "poll", "bitwarden", "profile sync", "config deference", "upstream", "deliberation"]` — used to identify procedural entries in the "kept in memory" report.
- **Auto-offload policy (2026-07-04):**
  - **Wiki-classified entries** above HIGH_THRESHOLD → **auto-removed** from MEMORY.md (QMD makes them searchable after removal). No user confirmation needed.
  - **All entries** (not just "skill"-classified) → matched against `SKILL_MATCHES` table (curated keyword→skill mapping):
    - **MATCH FOUND** → **auto-removed** (the skill already encodes this knowledge — no agent judgment needed)
    - **NO MATCH** → **kept in memory** (it's operational config, not a skill candidate — e.g. cron job IDs, bug fix history, Jim-specific workflow preferences)
  - **Keep entries** → never touched.
- **SKILL_MATCHES table (added 2026-07-04):** A curated list of `(keyword_phrases, [skill_names])` tuples at module level. Uses multi-word phrases (not single words like "dispatch") to avoid false positives. When a memory entry contains any keyword phrase AND the named skills exist on disk (checked via `skills_exist()` which searches both `skills/` and `hermes-agent/_skills/`), the entry is auto-offloaded. Currently 11 match rules covering delegate, verification, upstream-first, Kanban, SDLC, multi-model review, pragmatic momentum, long-running polling, and skill resolution ambiguity entries.
- **`skills_exist()` function:** Checks for `SKILL.md` on disk via `rglob` in both the user skills directory and the bundled `hermes-agent/_skills/` directory. Returns only skill names that actually exist — prevents offloading entries whose matching skills were deleted.
- **`offload_entries()` (renamed from `offload_wiki_entries`):** Generic function that removes entries at given indices from memory text. Handles both wiki and skill-matched offloads through a single code path.
- **User preference:** Jim explicitly requested auto-offload, not asking permission. The script was converted from report-only to auto-offload on 2026-06-25.
- **Schedule:** every 6 hours (`every 360m`), `no_agent=True`, `deliver=origin`

## QMD-aware wiki offload (added 2026-06-23)

The script checks if QMD semantic search is live before printing wiki offload candidates.
If QMD is active (vectors embedded > 0), the wiki offload header notes that candidates
remain searchable via QMD after removal from MEMORY.md — offloading is safe, not lossy.
If QMD is offline, a ⚠️ warning tells the user to verify wiki coverage first.

- **QMD binary:** `/opt/data/home/.npm-global/lib/node_modules/@tobilu/qmd/bin/qmd`
- **Detection:** runs `qmd status`, parses plain text for `Vectors: N embedded` where N > 0
- **Graceful degradation:** any error/timeout → `False` → shows offline warning
- **Why this matters:** makes the report actionable — Jim knows whether offloading a memory
  entry to the wiki means "still instantly retrievable via semantic search" or "verify
  coverage first." Without QMD awareness, every offload recommendation carries hidden risk.

## Fixes applied

- **2026-07-04 — Skill-matching overhaul + quality review:**
  - **"Flag but don't act" anti-pattern fixed:** Old script flagged skill-classified entries as "candidates" but never acted on them — a dead-end. New behavior: match ALL entries against `SKILL_MATCHES` table; auto-offload matches; keep non-matches as operational config (not "candidates").
  - **`SKILL_SIGNALS` removed** — dead code. The generic keywords ("skill", "procedure", "workflow") missed most procedural entries. Skill matching now runs against ALL entries via `match_skill_entry()`.
  - **`classify()` simplified** — returns only `"wiki"` or `"keep"`. The `"skill"` classification was unused.
  - **`PROCESS_SIGNALS` moved to module level** — was defined inside `main()` despite being a constant.
  - **Dead `skill_unmatched = []` removed** — leftover from earlier iteration, never populated.
  - **`offload_entries()` renamed** from `offload_wiki_entries` — now handles both wiki and skill-matched offloads.
  - **`skills_exist()` added** — checks for `SKILL.md` on disk before offloading. Prevents offloading entries whose matching skills were deleted.
  - **Test harness created:** `${HERMES_HOME}/scripts/test_memory_pressure_watch.py` — sandboxed, 3 test cases (wiki offload, skill match offload, keep operational config). Run: `python3 ${HERMES_HOME}/scripts/test_memory_pressure_watch.py`
- **2026-06-23:**
  - **USER_LIMIT corrected** 2400 → 4000 to match actual Hermes memory budget (was causing false 128% alerts).
  - **Bar clamped at 100%** — `min(used, limit)` in `fill_bar()` prevents bar overflow past 20 chars when usage exceeds limit.
  - **QMD-aware wiki offload** — checks QMD status before reporting wiki candidates.
  - **QMD refresh cron** — daily `0 4 * * *` no-agent job (`qmd_refresh.py`) keeps embeddings fresh. See SKILL.md QMD section.

## Token-efficiency lesson

A compression pass on this script stripped progress bars, renamed sections to
shorter labels, and removed the footer. User corrected twice: progress bars,
emoji headers, and original phrasing ("Wiki offload candidates", "Keep as-is")
are user-approved visuals — keep them. Only apply real bug fixes during
efficiency passes, not aesthetic rewrites.

## Visuals and language: what to keep vs trim

**Keep (user explicitly approved):**
- Progress bars: `[█████████████████░░░]`
- Status icons: 🔴 (≥100%) 🟡 (≥85%) 🟢 (<85%)
- Emoji section headers: 🧠 📋 👤 🗂 📖 ✅
- Full labels: "Wiki offload candidates", "Skill offload candidates", "Keep as-is"
- Bullet format: `• Entry N: preview…`
- Footer: no longer used — auto-offload mode delivers action summary instead of review prompt
- 120-char entry previews

**Trim (genuinely redundant):**
- Governance disclaimers not in the approved footer
- Per-item verbosity that doesn't aid scanning

**Lesson:** Token-efficiency audits of cron output must distinguish between *boilerplate
the agent added* (safe to trim) and *formatting/wording the user approved* (keep unless
the user asks to change it). See SKILL.md pitfall #19.

## QMD refresh cron (added 2026-06-23)

Daily `no_agent` cron (`0 4 * * *`) running `qmd update` + `qmd embed` silently.
Keeps vector embeddings fresh as wiki pages are added/changed by the 3 ingest crons.
Only emits output on failure (stale embeddings > silent failure).
Script: `${HERMES_HOME}/scripts/qmd_refresh.py`, deliver=telegram, job_id=YOUR_CRON_JOB_ID.

## Files

- Script: `${HERMES_HOME}/scripts/memory_pressure_watch.py`
- QMD refresh: `${HERMES_HOME}/scripts/qmd_refresh.py` (daily cron)
- Memory files: `/opt/data/memories/MEMORY.md` (limit 3000), `/opt/data/memories/USER.md` (limit 4000)
- QMD binary: `/opt/data/home/.npm-global/lib/node_modules/@tobilu/qmd/bin/qmd`

## Sample output (when threshold exceeded, auto-offload mode)

```
🧠 **Memory Pressure — Auto-Offload**

📋 **MEMORY.md**  [██████████████████░░] 91%  (2735/3000 chars)
👤 **USER.md**    [█████████████████░░░] 85%  (3405/4000 chars)

🗑 **Auto-offloaded** 3 entries from MEMORY.md:
  • QMD v2.5.3, ~104 docs, BM25+vector. Binary: /opt/data/home/.npm-global/bin/qmd...
    → wiki (keyword match)
  • Delegate: max_children=5, depth=1. Model: qwen3-coder-next:q4_K_M. Code review→Kimi...
    → skill exists: delegate-progress-protocol
  • Verification discipline: edit → test → verify → next edit. Pattern: edit → test...
    → skill exists: test-driven-development, devloop

📊 **After offload:** 1527/3000 chars (51%)

📝 **Kept in memory** (2) — operational config, not skill candidates:
  • Entry 4: EOD wrap cron (YOUR_CRON_JOB_ID): forward-looking tomorrow forecast...
  • Entry 7: google_api.py --account fix (Jul 1 2026): gws binary at ~/.npm-global/bin/gws...

✅ QMD active — offloaded entries remain searchable via `[[wiki-page]]`

✅ **Kept** 5 entries in MEMORY.md
```

## Context for auto-trigger idea

Jim asked whether this could auto-trigger on memory compaction. Answer: no native
Hermes hook exists for memory compaction events. The polling watchdog at 6h intervals
is the practical alternative. The webhook system only supports external HTTP POST triggers.

## Auto-offload safety pitfall (added 2026-06-25)

**Before auto-removing a wiki-classified entry, verify the wiki page covering its
content already exists.** The script auto-removes entries from MEMORY.md, but it does
NOT create wiki pages — that's the agent's job during an interactive session. If the
script removes an entry whose knowledge hasn't been captured in the wiki yet, that
knowledge is lost until QMD re-indexes (which only helps if the content was already
written to a wiki page).

**Safe workflow:**
1. Agent (interactive session): identifies wiki offload candidates, creates/updates wiki pages, THEN removes from memory
2. Cron (unattended): auto-offloads remaining wiki-classified entries that were missed

**QMD-aware check is necessary but not sufficient:** QMD being active means wiki pages
ARE searchable — but only if they exist. The script checks QMD status, not whether a
specific wiki page covers the specific memory entry being removed. When the agent
offloads entries during an interactive session, it should create the wiki page first,
then remove the memory entry. The cron script handles the "low-hanging fruit" — entries
that are clearly wiki-worthy AND already covered by existing wiki pages.

**Classification heuristic expansion (2026-06-25):** WIKI_SIGNALS expanded to include
`"qmd"`, `"binary:"`, `"version:"`, `"v0.1"`, `"v0.2"` to catch infrastructure/tooling
entries that belong in the wiki, not memory. These patterns indicate version-specific
or binary-path details that are lookup knowledge, not identity/preference.