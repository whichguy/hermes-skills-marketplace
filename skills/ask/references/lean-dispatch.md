# Lean Dispatch — Slim Hermes Agent for `ask`

Discovered 2026-07-09. When dispatching via `ask` (especially for models that
don't need skills browsing), stripping the system prompt yields a ~40% speedup.

## System Prompt Breakdown

Measured on Jim's Hermes instance (166 skills, full SOUL.md, 8K user profile):

| Component | Approx. Chars | Stripped by |
|---|---|---|
| Skills metadata (`<available_skills>` block) | **18,029** | Omitting `skills` toolset |
| SOUL.md (persona) | **12,830** | `--ignore-rules` |
| Memory (user profile + notes) | **~11,000** | `--ignore-rules` |
| Tool schemas (all tools) | **~8,000+** | Limited toolsets |
| MCP tool schemas | **~5,000+** | Still loaded (MCP servers persist) |
| Platform hints | **~500** | Always loaded |
| Guidance blocks | **~3,000** | Always loaded |
| Timestamp/profile | **~200** | Always loaded |
| **Total** | **~58K+** | |

## Timing Benchmarks

All measured with `hermes chat -q "What is 2+2?"` on qwen3.6:35b-a3b (local):

| Config | Time | What's stripped |
|---|---|---|
| Baseline (full system) | **9.6s** | Nothing |
| `--ignore-rules` | **6.9s** | SOUL.md, memory, AGENTS.md, .cursorrules, preloaded skills |
| `--ignore-rules` + `-t file,web` | **5.8s** | ↑ + limited toolsets (fewer tool schemas) |
| `--safe-mode` | **6.1s** | ↑ + config, plugins, MCP servers (bare metal) |
| `--ignore-rules` + no tools | **7.0s** | ↑ + zero tool schemas |

**Best practical config: `--ignore-rules -t file,terminal,web`** — 5.8s (40% faster).

## Why It Works

The skills metadata block (18K) is injected because `skills_list`/`skill_view`/
`skill_manage` tools are in the default toolset. When you specify `-t file,terminal,web`
(without `skills`), the `has_skills_tools` gate in `build_system_prompt_parts()`
evaluates to `False` and the entire `<available_skills>` block is skipped.

Source: `/opt/hermes/agent/system_prompt.py` → `build_system_prompt_parts()` →
`has_skills_tools = any(name in agent.valid_tool_names for name in ['skills_list', 'skill_view', 'skill_manage'])`

## The Slim Path

```bash
hermes chat -q "your question" \
  -m kimi-k2.7-code:cloud --provider ollama-glm \
  -Q --yolo --pass-session-id \
  --ignore-rules \
  -t file,terminal,web
```

This gives:
- **No SOUL.md** (saves 13K)
- **No memory** (saves 11K)
- **No skills metadata** (saves 18K — `skills_list`/`skill_view` aren't in `file,terminal,web`)
- **MCP tools still work** (wiki-search, Google Drive, hermes-home — all still loaded)
- **3 toolsets instead of ~15** (saves several K of tool schemas)
- **~5.8s instead of 9.6s** — 40% faster

## When to Use

| Scenario | Recommendation |
|---|---|
| Direct question to DeepSeek/Kimi (no skills needed) | **Lean** — `--ignore-rules -t file,terminal,web` |
| Code review that needs to read files | **Lean** — model uses `file` tool, not `skill_view` |
| Research that needs wiki/QMD MCP | **Lean** — MCP tools still work |
| Task that might need a skill | **Standard** — include `skills` in toolsets |
| Full agent with persona + memory | **Standard** — no `--ignore-rules` |

## What `--ignore-rules` Actually Does

From source (`hermes_cli/main.py:2342`):
- Sets `HERMES_IGNORE_RULES=1` env var
- Maps to `AIAgent(skip_context_files=True, skip_memory=True)`
- **Strips:** SOUL.md (~13K), memory/user-profile (~11K), AGENTS.md, .cursorrules, preloaded skills from config
- **Keeps:** Skills metadata block (~18K!), tool schemas, MCP servers, guidance blocks, platform hints

The skills metadata is the biggest remaining chunk — that's why limiting toolsets matters.

## Caveats

- Model loses ability to browse/load skills (no `skills_list`/`skill_view`)
- Model loses persona/memory context (no SOUL.md, no user profile)
- If you need skills access, add `skills` back: `-t file,terminal,web,skills`
- MCP tools (wiki-search, Google Drive) still work — they're loaded separately
