# SDLC Orchestrator — Child Process Model

> How the v6 iterative state machine spawns and manages child processes.
> Generated 2026-06-29 from a detailed architecture walkthrough.

## Architecture Overview

The SDLC v6 orchestrator (`run_iterative_state_machine` in `sdlc_state.py`) is a **single-process Python while-loop** that spawns child processes via `subprocess.run()` for each model interaction. The orchestrator itself is the only entity that interacts with the user — child processes are headless `hermes chat` subprocesses that cannot ask questions.

## The One Primitive: `dispatch_single()`

Every model call goes through one function in `model_utils.py:591`:

```
Orchestrator (Python loop)
    │
    ├── dispatch_single(model, prompt, context, toolsets, ...)
    │       │
    │       ├── builds: hermes chat -q <prompt> -m <model> --provider <provider> -Q --yolo --pass-session-id
    │       ├── optionally sets thinking level via hermes config (set before, restore after)
    │       │
    │       └── subprocess.run(cmd, timeout=3600, cwd=worktree)  ← BLOCKING CALL
    │               │
    │               └── Hermes agent subprocess (child process):
    │                       ├── loads system prompt, tools, skills
    │                       ├── runs multi-turn agent loop (up to 120 turns)
    │                       │   ├── model generates text/tool calls
    │                       │   ├── Hermes executes tool calls (write_file, terminal, etc.)
    │                       │   └── loops until model stops calling tools
    │                       └── writes final text response to stdout
    │
    └── returns: {"content": "...", "session_id": "...", "elapsed": 12.3, "error": None}
```

Key: `dispatch_single()` is a **blocking synchronous call**. The orchestrator waits. The child process is a full Hermes agent — system prompt, tools, skills, multi-turn reasoning — not a raw API call.

## State Machine — Which Child Gets Spawned When

The orchestrator is a `while state not in (COMPLETE, FAILED, HUMAN_REVIEW)` loop. Each state either spawns a child process or runs a local script:

| State | Child Process? | What Runs | Model |
|-------|---------------|----------|-------|
| **INIT** | No | Sets up `.sdlc/` dir, copies PROJECT.md, loads checkpoint | — |
| **PLAN** | ✅ `dispatch_single()` | Reads PROJECT.md + learnings + code state → generates iteration plan | GLM-5.2 (cloud) |
| **IMPLEMENT** | ✅ `dispatch_single()` | Reads plan → writes code + test files to worktree using terminal/file tools | qwen3-coder-next (local) |
| **LINT_FIX** | No | Runs `ruff --fix` + `pyflakes` + `mypy` locally via `subprocess.run()` | — |
| **RUN_TESTS** | No | Runs `pytest -v --tb=short` locally via `subprocess.run()` | — |
| **DEBUG** | ✅ `debug_cascade()` | Sequential cascade: qwen-coder first, if fails → kimi (cloud fallback) | qwen → kimi cascade |
| **VERIFYING** | ✅ `dispatch_single()` | Reads PROJECT.md + code state → returns SATISFIED/GAPS/UNCERTAIN verdict | DeepSeek-v4-pro (cloud) |
| **COMPLETE** | No | Emits final summary | — |
| **FAILED** | ✅ `dispatch_single()` | DeepSeek impasse diagnosis (root-cause analysis) | DeepSeek-v4-pro (cloud) |
| **HUMAN_REVIEW** | No | Emits options for user — orchestrator pauses | — |

## How a Child Process Spawn Works (concrete example: IMPLEMENT)

```python
# Line 1466 — orchestrator spawns coder:
result = dispatch_single(
    model="qwen3-coder-next:q4_K_M",      # local model via Ollama
    prompt="Implement this plan. You must write code AND tests as files on disk.\n"
           f"All work MUST happen in the worktree directory: {worktree}\n"
           f"1. Source file: {worktree}/{module_name}.py\n"
           f"2. Test file: {worktree}/test_{module_name}.py\n"
           f"Use 'cd {worktree} && cat > {module_name}.py << 'EOF'...' or write_file tool...\n"
           f"Do NOT run lint or format — the orchestrator handles that.\n"
           f"Do NOT return code in your response — WRITE it to disk.",
    context="",                            # plan is in the prompt itself
    toolsets="terminal,file",              # child can write files + run commands
    max_turns=None,                        # inherit Hermes default (120 turns)
    timeout=3600,                          # 1 hour (effectively unlimited — top-level wall-clock handles it)
    provider="ollama-glm",                 # Ollama proxy endpoint
    thinking=None,                         # inherit Hermes default reasoning_effort
    role="coder",                          # injects "You are acting as a coder" into context
    cwd=worktree,                          # child process working directory = worktree
)
```

The child process:
1. Hermes starts a fresh agent session with the coder model
2. The `role="coder"` directive is prepended to context: *"You are acting as a coder."*
3. The agent gets `terminal` and `file` toolsets — it can run shell commands and write files
4. `cwd=worktree` means the child's terminal tool runs commands in the worktree directory
5. The agent loops: model generates → Hermes executes tool calls (write_file, terminal) → model generates again → until it stops calling tools or hits 120 turns
6. Final text response goes to stdout
7. `dispatch_single()` captures stdout, parses session_id, returns `{"content": "...", "elapsed": 103.3}`
8. The orchestrator extracts any code from the response (fallback if model returned code as text instead of writing to disk)

## What the Child Process Can and Cannot Do

**Can do:**
- Write files to the worktree (via `write_file` tool or `cat > file` via terminal)
- Run shell commands in the worktree (via `terminal` tool)
- Read files from the worktree (via `read_file` tool)
- Multi-turn reasoning with tool use (up to 120 turns)

**Cannot do:**
- Ask the user questions (no `clarify` tool — child processes are headless `-Q --yolo` mode)
- Spawn subagents (no `delegate_task` — leaf agents only)
- Persist state between calls (each dispatch is a fresh session unless `--resume` is passed)
- Modify files outside the worktree (prompt enforces this, `cwd` constrains terminal)
- Control timeouts or termination (the orchestrator owns timing)

## The Orchestrator's Role as Proxy

Per user directive: *"The orchestrator is the only one who interacts with the user but the child process can ask the orchestrator to proxy on its behalf."*

The orchestrator:
- **Owns all timing** — `wall_clock_budget` (default 7200s) is checked at the top of every loop iteration. Per-dispatch timeouts are 3600s (effectively unlimited). The orchestrator is the only terminator.
- **Owns all user interaction** — when the state machine hits `HUMAN_REVIEW` or `FAILED`, it emits options to the user and pauses. The child processes never see the user.
- **Proxies for children** — if a child process needs clarification (e.g., ambiguous PROJECT.md), it can't ask directly. Instead:
  - The verifier returns `UNCERTAIN` verdict → orchestrator transitions to `HUMAN_REVIEW` → asks user
  - The debugger's cascade fails → orchestrator transitions to `FAILED` → emits impasse diagnosis → asks user
  - The coder's lint fails after 3 retries → orchestrator checks if tests pass → routes to `HUMAN_REVIEW` or `FAILED`

## State Transitions — The Complete Flow

```
INIT
  │
  ▼
PLAN ──────────── dispatch_single(GLM-5.2) ──────────► generates plan
  │
  ▼
IMPLEMENT ─────── dispatch_single(qwen-coder) ──────► writes code + tests to worktree
  │
  ▼
LINT_FIX ──────── subprocess: ruff + pyflakes + mypy ─► (no model, script only)
  │                                                    │
  ├── clean ─────────────────────────────────────────► RUN_TESTS
  │
  ├── unfixable, retries < 3 ────► back to IMPLEMENT (with lint errors in plan)
  │
  ├── unfixable, retries = 3 ────► check test files exist:
  │                                  ├── no test files → FAILED (coder didn't create tests)
  │                                  ├── tests pass → HUMAN_REVIEW
  │                                  └── tests fail → FAILED
  │
  ▼
RUN_TESTS ─────── subprocess: pytest ────────────────► (no model, script only)
  │
  ├── all pass ─────────────────────────────────────► VERIFYING
  │
  ├── some fail ────────────────────────────────────► DEBUG
  │
  └── stagnation (3x regression) ───────────────────► FAILED
  │
  ▼
DEBUG ─────────── debug_cascade(qwen → kimi) ──────► fixes code, writes to disk
  │                                                    │
  ├── fix succeeded, new root_cause ─────────────────► RUN_TESTS (tight loop)
  ├── fix succeeded, repeated root_cause ────────────► FAILED (stagnation)
  ├── fix succeeded, known root_cause ──────────────► PLAN (wide loop, re-plan)
  │
  └── cascade failed ───────────────────────────────► PLAN (re-plan) or FAILED (cascade stagnation)
  │
  ▼
VERIFYING ──────── dispatch_single(DeepSeek) ───────► reads code + PROJECT.md
  │
  ├── SATISFIED ───────────────────────────────────► COMPLETE ✅
  ├── GAPS ────────────────────────────────────────► PLAN (re-plan with gap analysis)
  ├── GAPS (same gaps 3x) ─────────────────────────► FAILED (gap stagnation)
  └── UNCERTAIN (2x) ──────────────────────────────► HUMAN_REVIEW
  │
  ▼
COMPLETE / FAILED / HUMAN_REVIEW  ← terminal states
```

## Data Flow Between Orchestrator and Children

| Direction | Mechanism | What flows |
|-----------|-----------|------------|
| Orchestrator → child | Prompt text | Plan, PROJECT.md excerpt, code state, failing test names, lint errors |
| Orchestrator → child | `context` param | Structured context blocks (PROJECT.md, learnings, code state, gaps) |
| Orchestrator → child | `role` param | Role directive ("You are acting as a coder/debugger/verifier/planner") |
| Orchestrator → child | `cwd` param | Worktree path — constrains where terminal tools operate |
| Orchestrator → child | `toolsets` param | Which tools the child can use (e.g., `terminal,file` for coder, `file` for verifier) |
| Child → orchestrator | stdout | Model's text response (plan, code, verdict, debug analysis) |
| Child → orchestrator | Files on disk | Code + test files written to worktree by the child's tool calls |
| Child → orchestrator | `session_id` | Session ID (captured from stderr) for potential `--resume` |
| Orchestrator → disk | `.sdlc/LEARNINGS.jsonl` | Structured learning entries (iteration, root_cause, fix, learning, files, commit) |
| Orchestrator → disk | `.sdlc/ITERATION_STATE.json` | Checkpoint for resume (all stagnation counters, iteration, state, plan) |
| Orchestrator → disk | `.sdlc/events.jsonl` | Structured event log (timestamps, state transitions, dispatch results) |
| Orchestrator → disk | `.sdlc/STATUS.json` | Current status snapshot (iteration, state, tests, elapsed) |

## Debug Cascade — The Special Case

The DEBUG state uses `debug_cascade()` in `sdlc.py:866` instead of a single `dispatch_single()`. It's a sequential fallback:

```python
DEBUGGER_CASCADE = [
    ('coder', 'qwen-coder (primary)', None, None),   # local, fast
    ('kimi',  'kimi (fallback)',    None, None),      # cloud, more capable
]
```

1. Try qwen-coder with the failing tests + error output
2. If qwen-coder returns content → use it (tight loop back to RUN_TESTS)
3. If qwen-coder fails (error, empty, timeout) → try kimi
4. If kimi succeeds → use it
5. If both fail → `cascade_succeeded=False`, orchestrator increments `cascade_stagnation`

The cascade is **sequential**, not parallel. Each attempt is a full `dispatch_single()` call with its own subprocess.

## Key Design Properties

1. **Synchronous blocking** — the orchestrator blocks on `subprocess.run()` during each child dispatch. No async, no threads, no parallelism. One child at a time.
2. **Fresh sessions** — each dispatch starts a new Hermes agent session (no conversation history carried over). Context is injected via the prompt + context parameters.
3. **Worktree isolation** — `cwd=worktree` ensures the child's terminal tool operates in the right directory. The prompt also explicitly says "cd {worktree} && ..." as belt-and-suspenders.
4. **Orchestrator owns termination** — wall-clock budget (7200s default) is the only real timeout. Per-dispatch timeouts are 3600s (effectively unlimited). The orchestrator checks at the top of every loop iteration.
5. **No child-to-child communication** — children never talk to each other. The orchestrator mediates everything: child output → orchestrator processes → next child gets processed context.
6. **Script-only states** — LINT_FIX and RUN_TESTS don't spawn model subprocesses. They run `ruff`/`pyflakes`/`mypy`/`pytest` directly via `subprocess.run()`, which is much faster and doesn't consume model tokens.

## Model Assignments

```python
MODEL_PLANNER_V6  = os.environ.get("SDLC_MODEL_PLANNER",  "glm-5.2:cloud")
MODEL_CODER_V6    = os.environ.get("SDLC_MODEL_CODER",    "qwen3-coder-next:q4_K_M")
MODEL_VERIFIER_V6 = os.environ.get("SDLC_MODEL_VERIFIER", "deepseek-v4-pro:cloud")
PROVIDER_DEFAULT  = os.environ.get("SDLC_PROVIDER_DEFAULT", "ollama-glm")
```

All overridable via environment variables. The planner uses GLM (cloud, broad reasoning), the coder uses qwen-coder (local, fast, free), and the verifier uses DeepSeek (cloud, strongest reasoning).
