# Kanban SDLC Failure Modes — Crash Prevention Catalog

11 crash modes identified from the first live SDLC chain test and 3-model council review.
Each mode includes root cause, guardrails applied, and remaining gaps.

## Modes 1-4: ✅ Fixed

### Mode 1: DeepSeek reviewer crashes on missing pytest
- **Root cause:** DeepSeek model has strong bias toward `python3 -m pytest`, ignores explicit instructions
- **Guardrail:** T4/T5 task bodies forbid pytest in ALL CAPS; `hermes kanban reassign --reclaim` recovery path
- **Gap:** Model-level bias — may recur with other tool preferences

### Mode 2: tests/ directory deleted during T3
- **Root cause:** Worker cleaned up workspace, removed files it didn't create
- **Guardrail:** T3 task body: "DO NOT delete any existing files in the project directory"
- **Gap:** No filesystem-level protection — relies on worker compliance

### Mode 3: Script errors (wrong JSON key, wrong CLI subcommand, truncated output)
- **Root cause:** `task_id` vs `id`, `hermes skill list` vs `hermes skills list`, `COLUMNS` truncation
- **Guardrail:** All fixed in script; `create_task()` helper validates JSON + ID format; `COLUMNS=200`
- **Gap:** New CLI changes could introduce similar mismatches

### Mode 4: Stuck tasks (running >24h, blocked >48h)
- **Root cause:** Worker crashes, model hangs, dispatcher doesn't detect stuck state
- **Guardrail:** `kanban_stuck_watch.py` + hourly `no_agent` cron; detects and alerts
- **Gap:** Watchdog alerts but doesn't auto-reclaim — human must act

## Mode 12: ✅ Fixed — Skill not available in target profile (2026-06-27, expanded 2026-06-27)

- **Root cause:** Task created with `--skill multi-model-code-review` but the reviewer profile has no skills directory — the skill only exists in the default profile. Worker crashes on startup with `Error: Unknown skill(s): multi-model-code-review`. After 3 crashes, dispatcher auto-blocks the task.
- **Sub-cause discovered 2026-06-27:** Even after copying skills to the profile, the stale `.skills_prompt_snapshot.json` caches the old skill list. Workers still crash until the snapshot is deleted and regenerated.
- **Guardrail:** Always verify skills exist in the target profile before creating tasks. Use `hermes -p <profile> skills list` to check. If the skill doesn't exist, either: (a) copy it to the profile's skills dir, (b) delete `.skills_prompt_snapshot.json` to force regeneration, (c) use a different skill that does exist (e.g., `kanban-worker`), or (d) create the task without `--skill` and put instructions in the body.
- **Recovery:** `hermes kanban archive <crashed-task-id>` then create a replacement task with correct skills. The replacement must be linked to the same parent for dependency chain continuity.
- **Gap:** No pre-flight skill validation in `kanban create` — the CLI accepts any skill name and the crash only surfaces when the worker spawns.

## Mode 13: ✅ Fixed — MCP servers not available in worker profiles (2026-06-27)

- **Root cause:** Profile `config.yaml` files do NOT inherit MCP server definitions from the main `/opt/data/config.yaml`. The `inherit_mcp_toolsets: true` config key only affects delegation toolset narrowing, not MCP server availability. Workers in reviewer/worker profiles can't use MCP tools (e.g., `mcp_hermes_home_directory_tree`, `mcp_wiki_search_query`) even though the orchestrator can.
- **Guardrail:** Copy the `mcp_servers:` block from the main config to each profile's `config.yaml`. This must be done alongside skill sync (Mode 12) — the two failures often co-occur.
- **Recovery:** Add `mcp_servers:` blocks to `/opt/data/profiles/<name>/config.yaml`, then reclaim or recreate the task.
- **Gap:** No automatic MCP config propagation — must be done manually for each new profile.

## Modes 5-11: Documented with Mitigations

### Mode 5: Container restart loses in-flight work
- **Root cause:** Docker restart kills running workers; tasks stay `running` forever
- **Mitigation:** Watchdog detects stuck tasks; `--reclaim` recovery path
- **Gap:** No auto-recovery on restart — manual intervention needed

### Mode 6: Kanban DB corruption
- **Root cause:** SQLite corruption from concurrent writes or disk full
- **Mitigation:** Single-writer dispatcher design; WAL mode
- **Gap:** No automated backup or integrity check

### Mode 7: Ollama SPOF (single point of failure)
- **Root cause:** All local models go through one Ollama instance; if it's down, all workers fail
- **Mitigation:** Cloud model fallback for critical phases (reviewer uses DeepSeek Pro via OpenRouter)
- **Gap:** Local-only phases (T1-T3, T5) have no fallback if Ollama is down

### Mode 8: Context window exhaustion
- **Root cause:** Long task bodies + skill content + project context exceed model's context window
- **Mitigation:** Skills are loaded per-phase (not all at once); task bodies are concise
- **Gap:** No runtime context-window monitoring or truncation

### Mode 9: Resource exhaustion (disk, memory, CPU)
- **Root cause:** Multiple workers + models consume all available resources
- **Mitigation:** Dispatcher serializes per-profile (one worker per profile at a time)
- **Gap:** No resource limits or monitoring per worker

### Mode 10: Model non-compliance (ignores instructions)
- **Root cause:** Model ignores explicit instructions (pytest bias, file deletion, etc.)
- **Mitigation:** ALL CAPS warnings in task bodies; watchdog detects stuck state
- **Gap:** No runtime compliance verification — relies on post-hoc detection

### Mode 11: Auto-decompose runaway
- **Root cause:** Block loop limit triggers auto-decomposition, creating many sub-tasks
- **Mitigation:** Limit is 2 cycles; auto-decomposer is a safety net, not primary path
- **Gap:** No cap on auto-decomposed sub-task count

## Guardrail Summary

| # | Guardrail | Type | Status |
|---|---|---|---|
| 1 | pytest forbidden in T4/T5 bodies | Task body | ✅ Applied |
| 2 | "DO NOT delete existing files" in T3 body | Task body | ✅ Applied |
| 3 | `create_task()` helper with JSON + ID validation | Script | ✅ Applied |
| 4 | `--dry-run` mode | Script | ✅ Applied |
| 5 | Project lock file (`.kanban-sdlc.lock`) | Script | ✅ Applied |
| 6 | Fatal pre-flight checks (profiles + skills) | Script | ✅ Applied |
| 7 | `trap` cleanup on exit/interrupt | Script | ✅ Applied |
| 8 | Stale lock detection (>1hr auto-removed) | Script | ✅ Applied |
| 9 | Stuck-task watchdog (hourly cron) | Cron | ✅ Applied |
| 10 | `--idempotency-key` on T1 | Script | ✅ Applied |
| 11 | `--board` support for multi-project isolation | Script | ✅ Applied |
| 12 | `hermes kanban reassign --reclaim` recovery | CLI | ✅ Documented |
| 13 | Deprecated daemon warning in script header | Script | ✅ Applied |
| 14 | Phase 5b cron: sequential workdir + recursion guard | Design | ✅ Designed |
| 15 | Auto-decompose block loop limit (2 cycles) | Dispatcher | ✅ Default |
| 16 | Single-writer dispatcher (no claim races) | Dispatcher | ✅ Default |
| 17 | Cloud model fallback for reviewer | Config | ⏳ Pending |
| 18 | Resource limits per worker | Infra | ⏳ Pending |
| 19 | DB integrity check / backup | Infra | ⏳ Pending |
| 20 | Context window monitoring | Runtime | ⏳ Pending |
