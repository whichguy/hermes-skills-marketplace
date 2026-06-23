# Memory Pressure Watchdog Pattern

**Established:** 2026-06-21 session · **Updated:** 2026-06-23

## Pattern

A `no_agent` Python script that reads Hermes memory files directly, classifies entries
by offload destination, and fires a review report only when pressure exceeds a threshold.
Silent when stores are comfortable — costs zero tokens on most runs.

## Key design decisions

- **Two thresholds:** `LOW_THRESHOLD = 0.70` (stay silent below) and `HIGH_THRESHOLD = 0.85` (report above). Both must be evaluated — only fire when at least one store exceeds HIGH.
- **Classification heuristics:**
  - `WIKI_SIGNALS`: `["detail →", "documented in", "wiki concept", "[[", "see wiki", "ops notes", "deploy", "runtime"]`
  - `SKILL_SIGNALS`: `["skill", "procedure", "workflow", "steps", "documented in the", "pitfall", "quirk"]`
  - Anything not matching → `keep`
- **Never auto-modifies.** Report only — user reviews candidates before anything is removed.
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

## Fixes applied 2026-06-23

- **USER_LIMIT corrected** 2400 → 4000 to match actual Hermes memory budget (was causing false 128% alerts).
- **Bar clamped at 100%** — `min(used, limit)` in `fill_bar()` prevents bar overflow past 20 chars when usage exceeds limit.
- **QMD-aware wiki offload** — checks QMD status before reporting wiki candidates.

## Visuals and language: what to keep vs trim

**Keep (user explicitly approved):**
- Progress bars: `[█████████████████░░░]`
- Status icons: 🔴 (≥100%) 🟡 (≥85%) 🟢 (<85%)
- Emoji section headers: 🧠 📋 👤 🗂 📖 ✅
- Full labels: "Wiki offload candidates", "Skill offload candidates", "Keep as-is"
- Bullet format: `• Entry N: preview…`
- Footer: "_Review the candidates above with Jim before removing anything._"
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
Script: `/opt/data/scripts/qmd_refresh.py`, deliver=telegram, job_id=312c3939cdee.

## Files

- Script: `/opt/data/scripts/memory_pressure_watch.py`
- QMD refresh: `/opt/data/scripts/qmd_refresh.py` (daily cron)
- Memory files: `/opt/data/memories/MEMORY.md` (limit 3000), `/opt/data/memories/USER.md` (limit 4000)
- QMD binary: `/opt/data/home/.npm-global/lib/node_modules/@tobilu/qmd/bin/qmd`

## Sample output (when threshold exceeded)

```
🧠 **Memory Pressure Review**

📋 **MEMORY.md**  [█████████████████░░░] 85%  (2558/3000 chars)
👤 **USER.md**    [█████████████████████] 77%  (3064/4000 chars)

🗂 **Wiki offload candidates** (3) — searchable via QMD after removal:
  • Entry 4: Google Workspace accounts...
  • Entry 5: Hermes runs in Docker...
  • Entry 7: deploy notes for production...

📖 **Skill offload candidates** (1):
  • Entry 6: WhatsApp trust anchors...

✅ **Keep as-is**: 5 entries

_Review the candidates above with Jim before removing anything._
```

## Context for auto-trigger idea

Jim asked whether this could auto-trigger on memory compaction. Answer: no native
Hermes hook exists for memory compaction events. The polling watchdog at 6h intervals
is the practical alternative. The webhook system only supports external HTTP POST triggers.