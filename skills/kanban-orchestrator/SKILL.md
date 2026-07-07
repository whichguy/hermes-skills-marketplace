---
name: kanban-orchestrator
description: Decomposition playbook + anti-temptation rules for an orchestrator profile
  routing work through Kanban. The "don't do the work yourself" rule and the basic
  lifecycle are auto-injected into every kanban worker's system prompt; this skill
  is the deeper playbook when you're specifically playing the orchestrator role.
version: 3.0.0
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - kanban
    - multi-agent
    - orchestration
    - routing
    related_skills:
    - kanban-worker
    config:
    - key: kanban-orchestrator.enabled
      description: Enable kanban-orchestrator skill behavior
      default: true
      prompt: Enable kanban-orchestrator skill?
    category: devops
author: Fortified Strength
license: MIT
---


# Kanban Orchestrator — Decomposition Playbook

> The **core worker lifecycle** (including the `kanban_create` fan-out pattern and the "decompose, don't execute" rule) is auto-injected into every kanban process via the `KANBAN_GUIDANCE` system-prompt block. This skill is the deeper playbook when you're an orchestrator profile whose whole job is routing.

## Profiles are user-configured — not a fixed roster

Hermes setups vary widely. Some users run a single profile that does everything; some run a small fleet (`docker-worker`, `cron-worker`); some run a curated specialist team they've named themselves. There is **no default specialist roster** — the orchestrator skill does not know what profiles exist on this machine.

Before fanning out, you must ground the decomposition in the profiles that actually exist. The dispatcher silently fails to spawn unknown assignee names — it doesn't autocorrect, doesn't suggest, doesn't fall back. So a card assigned to `researcher` on a setup that only has `docker-worker` just sits in `ready` forever.

**Step 0: discover available profiles before planning.**

Use one of these:

- `hermes profile list` — prints the table of profiles configured on this machine. Run it through your terminal tool if you have one; otherwise ask the user.
- `kanban_list(assignee="<some-name>")` — sanity-check a single name. Returns an empty list (rather than an error) for an unknown assignee, so this only confirms a name you're already considering.
- **Just ask the user.** "What profiles do you have set up?" is a fine first turn when the goal needs more than one specialist.

Cache the result in your working memory for the rest of the conversation. Re-asking every turn wastes a tool call.

## Automatic Kanban Detection (SOUL.md Injection)

The orchestrator skill is comprehensive, but it only helps if the agent *loads* it. The default profile — the user's interactive chat profile — has no built-in kanban awareness. It won't scan for the skill, won't recognize multi-step work as kanban-shaped, and will just do everything inline. The fix is **SOUL.md injection**: put kanban routing awareness directly into the agent's identity so it's always in context, no skill scanning required.

### The Problem

- Skills are discoverable but the agent must scan and recognize relevance each turn
- The kanban toolset is gated to worker processes — the default profile can only use CLI commands
- Without explicit prompting ("use kanban"), the agent defaults to inline execution or delegate_task
- The decision matrix in this skill is invisible to the agent unless it loads the skill first

### The Solution

Add a kanban routing block to `$HERMES_HOME/SOUL.md`. This puts the routing rules into the stable tier of the system prompt (slot #1), so every turn the agent sees them without needing to load a skill.

### SOUL.md Template

The template below is the **canonical working version** (verified 2026-06-27). It includes the Bitwarden JSON pipe fix, ID capture step, explicit link step, single-phase exclusion rule, and `execute_code` subprocess pattern — all learned from live testing.

```markdown
## Kanban Auto-Routing

When the user's request matches ANY of these structural patterns, automatically
load the `kanban-orchestrator` skill and route work through the Kanban board:

**Route to Kanban when:**
- Multiple distinct phases are named explicitly (e.g., "research X, then
  implement Y, then review Z")
- Multiple specialist profiles are needed (research + code + review)
- Work should survive session resets or crashes (cross-session durability)
- Parallel independent workstreams (fan-out)
- Explicit review gates needed (human-in-the-loop or reviewer profile)

**Do NOT route to Kanban for:**
- Single-tool lookups, quick questions, trivial fixes, typos
- Anything answerable in a single turn or a single delegate_task call
- Simple research with no review gate
- Small refactors, single-file edits, linting fixes
- Prompts with no multi-step or multi-specialist signal
- "Build X" or "Fix Y" alone — these are single-phase, do them inline

**User override:** If the user says anything like "just answer directly,"
"skip kanban," "no board," "inline only," or "don't route this," honor it
immediately and respond inline regardless of other signals.

**When in doubt:** Use `delegate_task` for quick parallel subtasks (minutes).
Use Kanban for multi-session work with review gates.

**How to route:**
1. Load `kanban-orchestrator` skill via `skill_view(name='kanban-orchestrator')`
2. Discover available profiles: `terminal(command="hermes profile list")`
   — Parse profile names from the first column of the table output
   — If the needed profile doesn't exist, ask the user; do NOT invent names
3. Decompose the request into a task graph (show it to the user before creating)
4. Create tasks via CLI. Use `execute_code` with subprocess for reliable ID capture:
   ```python
   import subprocess
   result = subprocess.run(["/opt/hermes/bin/hermes", "kanban", "create",
       "title", "--assignee", "worker", "--json"], capture_output=True, text=True)
   # Strip non-JSON prefix (Bitwarden warnings, etc)
   output = result.stdout
   idx = output.find("{")
   task_id = json.loads(output[idx:])["id"] if idx >= 0 else None
   ```
   — You do NOT have `kanban_create`/`kanban_list` tools in this profile
   — Always use `hermes kanban <verb>` CLI commands through `terminal()` or `execute_code`
   — The skill's Python-style `kanban_create()` examples are for reference only, NOT direct calls
   — Bitwarden warning prefixes break `--json | python3` pipes — always use `execute_code` with subprocess + `find("{")` to strip non-JSON output
5. Capture every task ID from the create response before creating the next task.
   You need these IDs for `--parent` links. Never guess or hardcode IDs.
6. Link parent-child dependencies with `hermes kanban link <parent> <child>`.
   Children with unfinished parents auto-stay in `todo` until parents complete.
7. If any `hermes kanban create` fails, STOP creating further tasks.
   Tell the user what succeeded and what failed. Ask how to proceed.
   Do NOT leave half-created task graphs unattended.
8. Report the task graph to the user (one summary line per task with ID + title + assignee)
9. Monitor via `terminal(command="hermes kanban list")` or dashboard

**SDLC-specific routing:** When the request involves an SDLC pattern (research →
implement → review, or design → build → test → deploy), decompose into ordinary
kanban tasks — the build/debug stages are executed by the **devloop** engine
automatically when a worker dispatches a build_code/debug task through the `ask`
pipeline (the legacy `sdlc-pipeline` engine + `kanban-sdlc.sh` were retired
2026-07-01; do NOT load the `sdlc-pipeline` skill or invoke `kanban-sdlc.sh`).
On COMPLETE a devloop build AUTO-MERGES its work into the target's current branch
(every gate passed — user decision 2026-07-01); only when the merge cannot apply
safely (dirty target / conflict / detached HEAD) does it degrade to a kept
`devloop/<name>` branch — chain a review task to inspect/merge THAT branch when
`devloop_result.merged` is false.

**Profile skill sync:** Before creating Kanban tasks that pin skills (via
`--skill`), ensure the target profile has that skill. Run
`python3 /opt/data/projects/kanban-auto-routing/sync-profile-skills.py` to sync
all skills and MCP servers from the default profile to worker/reviewer profiles.
A cron job runs this every 6 hours automatically.

**Delegation transparency:** When you create an SDLC chain via Kanban, you are
acting on a delegation from the user. The user should have full visibility into
what each worker is doing. Always:
1. Report the task graph immediately after creation (task IDs, assignees, skills, worktree path)
2. Set up dashboard monitoring (cron job posting to the same thread)
3. When the user replies in the thread, interpret it as a directive about the
   active SDLC chain — translate it into kanban actions (comment, block, unblock,
   re-queue, create follow-up task)
4. When a stage completes, proactively report the result and what's next
5. When the chain completes, report the final deliverable and suggest merging
   the worktree branch to main

**Delegation status check (when user asks "status?"):** Use `agent.log` grep as the
fastest path — `grep -i 'deleg_<id>\\|Dispatched async\\|ASYNC DELEGATION BATCH
COMPLETE' /opt/data/logs/agent.log | tail -20`. This reveals dispatch time,
completion events, and whether the subagent is still making API calls. Also check
`find <project_dir> -mmin -5 -type f` to see files the subagent modified recently.
See `delegate-progress-protocol` skill for the full delegation status toolkit.
```

### How It Works

1. **Always in context** — SOUL.md is in the stable prompt tier, loaded every session
2. **No skill scanning needed** — the agent sees the routing rules before it even processes the user's message
3. **Self-reinforcing** — the directive tells the agent to load the orchestrator skill, which then provides the full decomposition playbook
4. **Exclusion rules prevent over-routing** — trivial questions stay inline

### Verification

After adding the block to SOUL.md, test with these prompts:
- "Build a Python CLI tool for tracking gym workouts" → should decompose to kanban
- "What's 2+2?" → should NOT create kanban tasks
- "Research X, then implement Y, then review" → should create parent-child task chain

### Pitfalls

- **Editing the wrong SOUL.md.** Always verify `echo $HERMES_HOME` first. The active file is `$HERMES_HOME/SOUL.md`, not `$HERMES_HOME/.hermes/SOUL.md`.
- **Layering without removing old directives.** If an existing directive conflicts (e.g., "use delegate_task for everything"), remove or supersede it.
- **Prompt caching.** SOUL.md is in the stable tier — mid-session edits won't take effect until the next prompt rebuild. Use `/reset` for immediate effect.
- **Kanban tools are gated.** The default profile can't call `kanban_create` directly — it must use `hermes kanban create` via the terminal. The orchestrator skill accounts for this.
- **`--body` and `--skill` flags trigger gateway restart guard (2026-07-05).** When running `hermes kanban create` from inside the gateway process, flags that load prompt content (`--body` with a long string, `--skill`) may trigger the gateway restart guard: `Blocked: cannot restart or stop the gateway from inside the gateway process`. This is because the CLI interprets these as prompt-bearing operations that could trigger a gateway reload. **Workaround:** create the task with a short title only (no `--body`, no `--skill`), write the detailed task body to a file in a shared workspace directory (e.g., `/opt/data/projects/<name>/T1-task.md`), and include the file path in a short `--body` string (under ~100 chars avoids the guard): `--body 'Full instructions: /opt/data/projects/<name>/T1-task.md'`. Without this pointer, the worker sees a null body and has no way to discover the instruction file — it will guess from the title alone, producing inconsistent results. The worker can load skills itself from the task body instructions. For `--skill`, the worker profile must already have the skill synced (run `sync-profile-skills.py` before creating the task).
- **One-shot sessions can't create full task graphs.** `hermes chat -q` ends after one response, so the agent can only create the first task in the chain. Full parent-child decomposition (research → implement → review) requires a gateway session (Slack, Telegram, etc.) where the agent can continue across multiple turns. Test auto-routing from the actual chat platform, not from `hermes chat -q`.

## When to use the board (vs. delegate_task vs. just doing the work)

### Kanban needs multiple profiles to be useful

With only one profile (e.g. `default`), the orchestrator assigns everything to
itself — that's just a regular session with extra overhead. Kanban's value comes
from routing work to **specialists with isolated memory, skills, and context**.

**Minimum viable profile set for kanban:**

| Profile | Role | Why separate |
|---|---|---|
| `default` | Orchestrator + interactive chat | Your daily driver, keeps full context |
| `worker` | Research, implementation, tests | Isolated skill focus (qwen3-coder) |
| `reviewer` | Code review, quality gates, audits | Critical-eye persona (deepseek-v4-pro) |

Create profiles: `hermes profile create <name>` (from host: `docker exec -it
hermes /opt/hermes/bin/hermes profile create <name>`). Use `--clone` to copy
skills from default. Each profile gets its own memories, sessions, cron, and
skills directory.

### Decision matrix: delegate_task vs Kanban vs. do it yourself
| Factor | delegate_task | Kanban | Do it yourself |
|---|---|---|---|
| **Speed** | Faster (no profile spawn) | Slower (full process spawn) | Fastest |
| **Durability** | Lost if session ends | Survives restarts (SQLite) | N/A |
| **Parallelism** | Up to 5 in one turn | Dispatcher manages queue | Serial |
| **Human-in-loop** | No | Yes (block/unblock) | Yes (interactive) |
| **Audit trail** | Summary only | Full comment thread + state history | Session log |
| **Cross-session** | No | Yes | No |
| **Best for** | Quick parallel subtasks (minutes) | Multi-session projects with review gates | Single-session work |

**Rule of thumb:** Delegate for things that finish in minutes. Kanban for things
that span sessions or need human review gates. Do it yourself for single-tool
calls and sequential pipelines.

### When to create Kanban tasks

Create Kanban tasks when any of these are true:

1. **Multiple specialists are needed.** Research + analysis + writing is three profiles.
2. **The work should survive a crash or restart.** Long-running, recurring, or important.
3. **The user might want to interject.** Human-in-the-loop at any step.
4. **Multiple subtasks can run in parallel.** Fan-out for speed.
5. **Review / iteration is expected.** A reviewer profile loops on drafter output.
6. **The audit trail matters.** Board rows persist in SQLite forever.

If *none* of those apply — it's a small one-shot reasoning task — use `delegate_task` instead or answer the user directly.

## The anti-temptation rules

Your job description says "route, don't execute." The rules that enforce that:

- **Do not execute the work yourself.** Your restricted toolset usually doesn't even include terminal/file/code/web for implementation. If you find yourself "just fixing this quickly" — stop and create a task for the right specialist.
- **For any concrete task, create a Kanban task and assign it.** Every single time.
- **Split multi-lane requests before creating cards.** A user prompt can contain several independent workstreams. Extract those lanes first, then create one card per lane instead of bundling unrelated work into a single implementer card.
- **Run independent lanes in parallel.** If two cards do not need each other's output, leave them unlinked so the dispatcher can fan them out. Link only true data dependencies.
- **Never create dependent work as independent ready cards.** If a card must wait for another card, pass `parents=[...]` in the original `kanban_create` call. Do not create it first and link it later, and do not rely on prose like "wait for T1" inside the body.
- **If no specialist fits the available profiles, ask the user which profile to create or which existing profile to use.** Do not invent profile names; the dispatcher will silently drop unknown assignees.
- **Decompose, route, and summarize — that's the whole job.**

## Decomposition playbook

### Step 1 — Understand the goal

Ask clarifying questions if the goal is ambiguous. Cheap to ask; expensive to spawn the wrong fleet.

### Step 2 — Sketch the task graph

Before creating anything, draft the graph out loud (in your response to the user). Treat every concrete workstream as a candidate card:

1. Extract the lanes from the request.
2. Map each lane to one of the profiles you discovered in Step 0. If a lane doesn't fit any existing profile, ask the user which to use or create.
3. Decide whether each lane is independent or gated by another lane.
4. Create independent lanes as parallel cards with no parent links.
5. Create synthesis/review/integration cards with parent links to the lanes they depend on. A child created with unfinished parents starts in `todo`; the dispatcher promotes it to `ready` only after every parent is done.

Examples of prompts that should fan out (using placeholder profile names — substitute whatever exists on the user's setup):

- "Build an app" → one card to a design-oriented profile for product/UI direction, one or two cards to engineering profiles for implementation, plus a later integration/review card if the user has a reviewer profile.
- "Fix blockers and check model variants" → one implementation card for the blocker fixes plus one discovery/research card for config/source verification. A final reviewer card can depend on both.
- "Research docs and implement" → a docs-research card can run in parallel with a codebase-discovery card; implementation waits only if it truly needs those findings.
- "Analyze this screenshot and find the related code" → one card to a vision-capable profile for the visual analysis while another searches the codebase.

Words like "also," "finally," or "and" do not automatically imply a dependency. They often mean "make sure this is covered before reporting back." Only link tasks when one card cannot start until another card's output exists.

Show the graph to the user before creating cards. Let them correct it — including which actual profile name should own each lane.

### Step 3 — Create tasks and link

Use the profile names from Step 0. The example below uses placeholders `<profile-A>`, `<profile-B>`, `<profile-C>` — replace them with what the user actually has.

```python
t1 = kanban_create(
    title="research: Postgres cost vs current",
    assignee="<profile-A>",  # whichever profile handles research on this setup
    body="Compare estimated infrastructure costs, migration costs, and ongoing ops costs over a 3-year window. Sources: AWS/GCP pricing, team time estimates, current Postgres bills from peers.",
    tenant=os.environ.get("HERMES_TENANT"),
)["task_id"]

t2 = kanban_create(
    title="research: Postgres performance vs current",
    assignee="<profile-A>",  # same profile, run in parallel
    body="Compare query latency, throughput, and scaling characteristics at our expected data volume (~500GB, 10k QPS peak). Sources: benchmark papers, public case studies, pgbench results if easy.",
)["task_id"]

t3 = kanban_create(
    title="synthesize migration recommendation",
    assignee="<profile-B>",  # whichever profile does synthesis/analysis
    body="Read the findings from T1 (cost) and T2 (performance). Produce a 1-page recommendation with explicit trade-offs and a go/no-go call.",
    parents=[t1, t2],
)["task_id"]

t4 = kanban_create(
    title="draft decision memo",
    assignee="<profile-C>",  # whichever profile drafts user-facing prose
    body="Turn the analyst's recommendation into a 2-page memo for the CTO. Match the tone of previous decision memos in the team's knowledge base.",
    parents=[t3],
)["task_id"]
```

`parents=[...]` gates promotion — children stay in `todo` until every parent reaches `done`, then auto-promote to `ready`. No manual coordination needed; the dispatcher and dependency engine handle it.

If the task graph has dependencies, create the parent cards first, capture their returned ids, and include those ids in the child card's `parents` list during the child `kanban_create` call. Avoid creating all cards in parallel and linking them afterward; that creates a window where the dispatcher can claim a child before its inputs exist.

### Step 4 — Complete your own task

If you were spawned as a task yourself (e.g. a planner profile was assigned `T0: "investigate Postgres migration"`), mark it done with a summary of what you created:

```python
kanban_complete(
    summary="decomposed into T1-T4: 2 research lanes in parallel, 1 synthesis on their outputs, 1 prose draft on the recommendation",
    metadata={
        "task_graph": {
            "T1": {"assignee": "<profile-A>", "parents": []},
            "T2": {"assignee": "<profile-A>", "parents": []},
            "T3": {"assignee": "<profile-B>", "parents": ["T1", "T2"]},
            "T4": {"assignee": "<profile-C>", "parents": ["T3"]},
        },
    },
)
```

### Step 5 — Report back to the user

Tell them what you created in plain prose, naming the actual profiles you used:

> I've queued 4 tasks:
> - **T1** (`<profile-A>`): cost comparison
> - **T2** (`<profile-A>`): performance comparison, in parallel with T1
> - **T3** (`<profile-B>`): synthesizes T1 + T2 into a recommendation
> - **T4** (`<profile-C>`): turns T3 into a CTO memo
>
> The dispatcher will pick up T1 and T2 now. T3 starts when both finish. You'll get a gateway ping when T4 completes. Use the dashboard or `hermes kanban tail <id>` to follow along.

## Common patterns

**Fan-out + fan-in (research → synthesize):** N research-style cards with no parents, one synthesis card with all of them as parents.

**Parallel implementation + validation:** one implementer card makes the change while one explorer/researcher card verifies config, docs, or source mapping. A reviewer card can depend on both. Do not make the implementer own unrelated verification just because the user mentioned both in one sentence.

**Pipeline with gates:** `planner → implementer → reviewer`. Each stage's `parents=[previous_task]`. Reviewer blocks or completes; if reviewer blocks, the operator unblocks with feedback and respawns.

**Same-profile queue:** N tasks, all assigned to the same profile, no dependencies between them. Dispatcher serializes — that profile processes them in priority order, accumulating experience in its own memory.

**Human-in-the-loop:** Any task can `kanban_block()` to wait for input. Dispatcher respawns after `/unblock`. The comment thread carries the full context.

**SDLC chain (research → tests → code → review → test):** The full software development lifecycle as a 5-phase parent-child task graph. Each phase depends on the previous phase's output. All tasks share the same `dir:` workspace so each phase can read the previous phase's files.

```
T1: research → worker, dir:/opt/data/projects/<name>  [skill: spike]
    ↓ parent
T2: write tests (TDD) → worker, dir:/opt/data/projects/<name>  [skill: test-driven-development]
    ↓ parent
T3: implement code → worker, dir:/opt/data/projects/<name>  [skills: TDD + systematic-debugging]
    ↓ parent
T4: review code → reviewer, dir:/opt/data/projects/<name>  [skill: multi-model-code-review]
    ↓ parent (if approved) OR → fix cycle (if blocked)
T5: run full test suite → worker, dir:/opt/data/projects/<name>  [no skill — test instructions in body]
```

**Key rules for SDLC chains:**
- All tasks share the same `dir:` workspace — scratch workspaces are isolated and prevent downstream tasks from seeing upstream output.
- T4 (reviewer) uses a different model/profile for genuine cognitive diversity (maker-checker).
- If T4 blocks, create a NEW fix task linked from T4 — don't re-run T3.
- Max 2 fix cycles (T4 → fix → T4 → fix2 → T4), then ping the human.
- T5 (final test) verifies no regressions across the full suite, not just the new tests.
- For git-tracked projects, use `worktree:` workspaces so each phase gets its own branch and the reviewer can inspect `git diff`.
- Use `--idempotency-key` on T1 to prevent duplicate chains on script rerun (derived from project+goal hash).
- Use `--board <slug>` for multi-project isolation (optional 3rd arg or `HERMES_KANBAN_BOARD` env var).
- **Do NOT run `hermes kanban daemon`** while `dispatch_in_gateway` is enabled — the daemon is deprecated and causes claim races.
- If the reviewer keeps crashing, use `hermes kanban reassign <id> <new-profile> --reclaim` to switch profiles mid-run.

### Aligning skills with SDLC phases via `--skill`

The `kanban create --skill <name>` flag force-loads a skill into the worker's system prompt alongside the auto-injected KANBAN_GUIDANCE. This bridges procedural knowledge (skills) with execution context (Kanban) — the worker knows HOW to work (from the skill) AND WHAT to work on (from the task body).

**Standard SDLC skills-per-phase mapping (R4-corrected):**

| Phase | `--skill` flag(s) | What the worker gains |
|---|---|---|
| T1 Research | `--skill spike` | Structured research/experimentation with VALIDATED/PARTIAL/INVALIDATED verdict |
| T2 Write tests | `--skill test-driven-development` | RED-GREEN-REFACTOR discipline, test-first enforcement |
| T3 Implement | `--skill test-driven-development --skill systematic-debugging` | GREEN phase + 4-phase debugging if tests fail |
| T4 Review | `--skill multi-model-code-review` | Independent cross-agent review protocol (NOT requesting-code-review, which is a pre-commit self-review) |
| T5 Final test | No skill — test instructions in task body | `skill-testing-harness` is for validating Hermes skills, not project test suites |

**R4 corrections (from advisors review round 4):**
- T1: Changed from `plan` to `spike` — `plan` writes to `.hermes/plans/` and forbids project file edits, conflicting with producing RESEARCH.md
- T4: Changed from `requesting-code-review` to `multi-model-code-review` — the former is a pre-commit self-review skill that assumes `git diff --cached` and the reviewer wrote the code
- T5: Removed `skill-testing-harness` — it validates Hermes skills (frontmatter, scripts, tests under `skills/<name>/tests/`), not project test suites

**File-based handoff contracts (in shared `dir:` workspace):**
- T1 → `RESEARCH.md` (goal, options, recommendation, risks, verdict)
- T2 → `TEST_PLAN.md` (test list, expected behavior) + actual test files
- T3 → `CHANGES.md` (changed files, decisions, test results)
- T4 → `REVIEW.md` (findings or APPROVED status)
- T5 → `TEST_RESULTS.md` (tests_run, tests_passed, all_passed)

**Skill precedence when conflicts arise:**
1. KANBAN_GUIDANCE wins on lifecycle (when to complete/block/heartbeat)
2. Task body wins on deliverables (what to produce, where to put it)
3. Phase skill wins on technical method (how to TDD, how to debug, how to review)

**Why this matters:** Without `--skill`, a worker gets only the task body and KANBAN_GUIDANCE. It must figure out HOW to do TDD, how to review code, or how to debug from scratch — inconsistent across runs. With `--skill`, the worker follows a proven process every time.

**Three layers of knowledge per worker:**
1. **Kanban lifecycle** (auto-injected KANBAN_GUIDANCE) — how to use kanban_show, kanban_complete, kanban_block
2. **Phase skill** (via `--skill`) — how to do TDD, how to review code, how to debug
3. **Project context** (via AGENTS.md in `dir:` workspace) — project-specific invariants and standards

**Live test findings (2026-06-27):** First end-to-end SDLC chain ran on a real project. 5/5 phases completed, 14/14 tests pass. Three issues found and fixed:

1. **DeepSeek reviewer crashes on missing pytest** — The reviewer model (DeepSeek) has a strong bias toward `python3 -m pytest` and ignores explicit instructions to use `python3 -m unittest`. After 5 consecutive crashes, the dispatcher auto-blocks the task. **FIXED R5:** T4 and T5 task bodies now explicitly forbid pytest in ALL CAPS. Also added `hermes kanban reassign --reclaim` as a recovery path.

2. **tests/ directory deleted during T3** — The implementer worker cleaned up its workspace and removed files it didn't create. In a shared `dir:` workspace, this breaks downstream phases. **FIXED R5:** T3 task body now includes "DO NOT delete any existing files in the project directory."

3. **Script bugs found and fixed** — JSON key is `id` not `task_id`; CLI subcommand is `hermes skills list` not `hermes skill list`; skill names truncated in table output (fix: `COLUMNS=200`). All fixed.

**R5 advisors review (2026-06-27):** DeepSeek + Kimi reviewed the plan against latest Hermes docs. 8 new findings:
- CRITICAL: Status name is `running` not `in_progress` (verified via CLI)
- HIGH: `--idempotency-key` added to T1 (prevents duplicate chains on rerun)
- HIGH: `--board <slug>` support added (multi-project isolation)
- MEDIUM: pytest explicitly forbidden in T4/T5 task bodies
- MEDIUM: T3 body now says "DO NOT delete existing files"
- MEDIUM: Deprecated daemon warning added to script header
- MEDIUM: Cron Phase 5b rewritten for sequential workdir + recursion guard
- LOW: Profile description CLI + reassign mention for crash recovery

**R6 implementation (2026-06-27):** All 13 fixes applied. Key deliverables:

**Script guardrails (`kanban-sdlc.sh`)** *(HISTORICAL — kanban-sdlc.sh was retired with the
legacy SDLC engine on 2026-07-01; devloop is the SDLC engine now. Kept as a record of the
guardrail patterns.)*:
- **`--dry-run` mode** — prints task bodies without creating any tasks, for pre-flight review
- **Project lock file** (`.kanban-sdlc.lock`) — prevents overlapping SDLC chains on same project dir; auto-removed by `trap` on exit/interrupt; stale locks >1hr auto-cleaned
- **Fatal pre-flight checks** — profiles + skills must exist or script exits non-zero (was warning-only)
- **`create_task()` helper** — captures stderr (no more `2>/dev/null` hiding failures), validates JSON, checks ID format (`t_[a-f0-9]+`), uses `--idempotency-key`
- **Arg validation** — fixed `set -u` unbound variable crash on missing args; shows usage on error
- **Shell injection guard** — `_goal_has_unsafe()` rejects dangerous metacharacters (quotes, backtick, `$`, backslash, `;`, `|`, `&`, `<`, `>`) using `grep -qE` pattern matching. Allows spaces, hyphens, underscores, parens, periods, commas, slashes, colons. **Do NOT use bash `case` patterns for this** — `case` patterns with `|` and `*` break on spaces and require fragile escaping. The `printf '%s' "$1" | grep -qE '['"'"'"\`\$\\;|&<>]'` approach is simpler and correct.

**Operational guardrails:**
- **Stuck-task watchdog** deployed: `kanban_stuck_watch.py` + hourly `no_agent` cron (YOUR_CRON_JOB_ID, Slack). Detects tasks stuck in `running` >24h or `blocked` >48h. Silent on healthy board. See `references/kanban-stuck-task-watchdog.md`.
- **Failure modes catalog** created: `wiki/concepts/kanban-sdlc-failure-modes.md` — 11 crash modes with root cause, guardrails, and gaps. Covers pytest bias, workspace deletion, script errors, stuck tasks, container restart, DB corruption, Ollama SPOF, context exhaustion, resource exhaustion, model non-compliance, auto-decompose runaway. See `references/kanban-sdlc-failure-modes.md`.
- **Validation plan** created: `projects/kanban-integration/validation-plan.md` — 3-tier plan: Tier 1 (8 deterministic script logic tests), Tier 2 (5 guardrail enforcement tests), Tier 3 (3 live demos: happy-path, block→fix, idempotent rerun). See `references/kanban-sdlc-validation-plan.md`.
- **Positioning doc** created: `wiki/concepts/sdlc-pipeline-comparison.md` — 10-dimension decision matrix comparing Kanban SDLC vs multi-model-dev-pipeline.
- **Phase 5b cron design** rewritten: sequential workdir constraint, recursion guard (cron sessions may create kanban tasks but NOT cron jobs), `--add-skill` vs `--skill` semantics, circuit breakers (max 10 tasks/run, max 50 open/board).
- **Phase 4b edge-case test plan** ready: 7 tests covering block→fix→re-review, 2-cycle cap, pytest fallback, workspace preservation, kill switch, stuck-task watchdog, idempotent rerun.

See `references/sdlc-live-test-results.md` for the full test report.
See `references/sdlc-skills-alignment.md` for the full mapping and reusable script.

## Pitfalls

**Inventing profile names that don't exist.** The dispatcher silently fails to spawn unknown assignees — the card just sits in `ready` forever. Always assign to a profile from your Step 0 discovery; ask the user if you're unsure.

**Bundling independent lanes into one card.** If the user asks for two independent outcomes, create two cards. Example: "fix blockers and check model variants" is not one fixer task; create a fixer/engineer card for the fixes and an explorer/researcher card for the variant check, then optionally gate review on both.

**Over-linking because of wording.** "Finally check X" may still be parallel with implementation if X is static config, docs, or source discovery. Link it after implementation only when the check depends on the implementation result.

**Forgetting dependency links.** If the task graph says `research -> implement -> review`, do not create all tasks as independent ready cards. Use parent links so implement/review cannot run before their inputs exist.

**Reassignment vs. new task.** If a reviewer blocks with "needs changes," create a NEW task linked from the reviewer's task — don't re-run the same task with a stern look. The new task is assigned to the original implementer profile.

**Fix-task parent linkage trap.** When a reviewer blocks and you create a fix task, do NOT set `parents=[<blocked-review-task-id>]`. A blocked parent never reaches `done`, so the fix task stays in `todo` forever — the dependency engine only promotes children when every parent is `done`. Instead, create the fix task as an independent `ready` task (no parents), then manually unblock the review task after the fix completes. Alternatively, create with the parent link and immediately `kanban unlink` to break the dependency. The correct flow: T1(implement) → T2(review, blocks) → T3(fix, independent ready) → T2(unblock for re-review). Never: T3(parent=T2) when T2 is blocked.

**Block loop limit triggers auto-decomposition.** The dispatcher has a `block_loop_limit` (default: 2). When a reviewer blocks the same task more than this limit, the auto-decomposer splits the review into sub-tasks (extract invariants, verify each, run tests, audit quality, synthesize). This is a safety net, not a bug — it prevents infinite re-review loops. If you want the reviewer to keep re-reviewing after fixes, unblock the task rather than letting it hit the limit. The auto-decomposer is a last resort, not the primary fix path.

**Argument order for links.** `kanban_link(parent_id=..., child_id=...)` — parent first. Mixing them up demotes the wrong task to `todo`.

**Don't pre-create the whole graph if the shape depends on intermediate findings.** If T3's structure depends on what T1 and T2 find, let T3 exist as a "synthesize findings" task whose own first step is to read parent handoffs and plan the rest. Orchestrators can spawn orchestrators.

**Skill not available in target profile (2026-06-27, expanded 2026-06-27).** When creating a task with `--skill <name>`, the skill must exist in the TARGET profile's skills directory, not just the orchestrator's. Workers crash on startup with `Error: Unknown skill(s): <name>` if the skill isn't found. This is the #1 cause of kanban worker crashes in practice.

**Root cause chain:** Profiles created with `hermes profile create` only get bundled default skills. Custom skills installed later in the default profile (`/opt/data/skills/`) are never propagated to worker/reviewer profiles. The profile's `.skills_prompt_snapshot.json` caches the old skill list — even after copying skills, the snapshot must be deleted or workers still won't see them.

**Full fix procedure (automated):**
1. **Run the sync script** — `python3 /opt/data/projects/kanban-auto-routing/sync-profile-skills.py`
   This handles: chmod (profile skill files are read-only, owned by `hermes` user), overlay of missing skills, MCP config sync, and stale snapshot deletion. A cron job runs this every 6h automatically.
2. **Manual fallback** — if the script is unavailable:
   - Copy skills: `cp -r /opt/data/skills/* /opt/data/profiles/<name>/skills/`
   - Fix permissions first: `chmod -R u+w /opt/data/profiles/<name>/skills/`
   - Delete stale snapshot: `rm /opt/data/profiles/<name>/.skills_prompt_snapshot.json`
   - Add MCP servers to profile `config.yaml` (not inherited from main config) via `python3 /opt/data/projects/kanban-auto-routing/sync-mcp-config.py`

**Pre-flight check:** Before creating tasks, verify with `hermes -p <profile> skills list`. If the skill doesn't exist, either sync it, use a different skill, or put instructions in the task body.

**Recovery:** `hermes kanban archive <crashed-task-id>` then create a replacement task with correct skills (or no `--skill` flag). The replacement must be linked to the same parent for dependency chain continuity. See `references/kanban-sdlc-failure-modes.md` Mode 12 and Mode 13.

**MCP server inheritance gap (2026-06-27).** Profile `config.yaml` files do NOT inherit MCP server definitions from the main `/opt/data/config.yaml`. The `inherit_mcp_toolsets: true` config key only affects delegation toolset narrowing, not MCP server availability. If a worker profile needs MCP tools (e.g., `mcp_hermes_home_directory_tree` for file exploration, `mcp_wiki_search_query` for knowledge base access), the MCP server blocks must be explicitly added to the profile's `config.yaml`. Without this, workers can't use MCP tools even though the orchestrator can. Fix: run `python3 /opt/data/projects/kanban-auto-routing/sync-mcp-config.py` to copy the `mcp_servers:` block from the main config to each profile's config.yaml, or run `python3 /opt/data/projects/kanban-auto-routing/sync-profile-skills.py` to sync skills and MCP servers together.

**Broken symlinks in skill `.venv` directories crash `sync-profile-skills.py` (2026-07-03).** The sync script uses `os.walk()` + `shutil.copy2()` to copy skill files to profile directories. If a skill directory contains a `.venv` with platform-specific symlinks (e.g., macOS `.venv` synced to a Linux host, with symlinks pointing to `/Applications/Xcode.app/.../python3`), `shutil.copy2()` raises `FileNotFoundError` because the symlink target doesn't exist on the current platform. The script has been patched to skip broken symlinks (guard: `os.path.islink(src) and not os.path.exists(src)` before `shutil.copy2()`), but the root cause — stale platform-specific `.venv` directories bundled in skills — should also be addressed by removing the `.venv` from the skill directory. **Detection:** the error traceback shows `shutil.copy2` → `FileNotFoundError` with a path containing `.venv/bin/python3`. **Prevention:** before syncing a skill that includes a `.venv`, verify it's compatible with the current platform or remove it. The 6-hourly cron sync job will catch and auto-fix this class of error going forward.

**Bitwarden JSON pipe breakage (default profile only).** The Bitwarden Secrets Manager warning prefix (`Bitwarden Secrets Manager: secrets.bitwarden.enabled is true...`) appears in `hermes kanban` CLI output before the JSON payload. This breaks `--json | python3` pipes because the piped input starts with non-JSON text. The default profile (which lacks kanban tools) must use `execute_code` with `subprocess.run()` and `output.find("{")` to strip non-JSON prefixes. The orchestrator profile (which has kanban tools) is unaffected — it calls `kanban_create()` directly.

**`hermes kanban delete` is not a valid command.** The CLI has no `delete` subcommand. To remove tasks from the board, use `hermes kanban archive <task_id>`. Archived tasks are hidden from `kanban list` but preserved in the database. To permanently remove a task, archive it first, then use `hermes kanban gc` (garbage collection). Common mistake: trying `kanban delete` after seeing `kanban create` — the symmetry is misleading.

**Tenant inheritance.** If `HERMES_TENANT` is set in your env, pass `tenant=os.environ.get("HERMES_TENANT")` on every `kanban_create` call so child tasks stay in the same namespace.

**Scratch workspace isolation breaks chained tasks.** Workers in `scratch` workspaces (the default) cannot see files written by other workers. If T1 writes a file to `/tmp/foo.py` and T2 (parent: T1) needs to read it, T2 will fail — it runs in a different scratch directory. For chained tasks (SDLC, pipeline, fan-in), use `dir:` or `worktree:` workspaces so all phases share the same filesystem. The smoke test confirmed this: a reviewer in a scratch workspace could not find a file the worker wrote to `/tmp/`.

**notify-subscribe must happen BEFORE dispatch.** The `kanban notify-subscribe` command registers a subscription that fires when the task completes. But if the dispatcher has already claimed the task (status: `running`), the subscription may not fire — the completion event has already been consumed. Always subscribe immediately after `kanban create` and before the dispatcher's next tick (default: 60s). Subscriptions are consumed on completion (auto-removed from `notify-list`), so they don't persist across multiple task runs. Gateway log at INFO level does not show notification sends; use `notify-list` to verify subscription state.

## References

- `references/kanban-setup-checklist.md` — One-time setup: profile creation,
  config keys, board init, gateway restart, AGENTS.md templates, smoke tests.
- `references/kanban-smoke-test-results.md` — Verified smoke test results
  (2026-06-26): worker spawn, reviewer spawn, block flow, kill switch, workspace
  isolation finding.
- `references/sdlc-live-test-results.md` — First end-to-end SDLC chain test
  (2026-06-27): 5/5 phases completed, 14/14 tests pass, 3 script bugs found,
  DeepSeek reviewer pytest crash, tests/ directory deletion.
- `references/kanban-auto-detection-test-plan.md` — Test plan for validating
  automatic kanban routing from the default profile after SOUL.md injection
  (2026-06-27).
- `references/kanban-auto-routing-test-results.md` — Phase 1-4 test results:
  baseline (0/4 routed), SOUL.md injection (explicit triggers work, implicit
  single-phase stays inline), gateway session implicit multi-phase (3-task SDLC
  chain created), Bitwarden JSON pipe fix, 6 SOUL.md improvements applied
  (2026-06-27).
- `references/kanban-stuck-task-watchdog.md` — Operational watchdog pattern:
  script + no_agent cron for detecting stuck running/blocked tasks (2026-06-27).
- `references/kanban-sdlc-failure-modes.md` — Crash prevention catalog: 11
  failure modes with root cause, guardrails, and gaps (2026-06-27).
- `references/kanban-dashboard-pattern.md` — Script-only cron dashboard pattern:
  enriched multi-section board monitoring with delta detection, zero-token
  `no_agent` delivery, and Slack-friendly formatting (2026-06-27). Updated
  with Slack mrkdwn best practices and Block Kit research summary.
- `references/kanban-sdlc-validation-plan.md` — 3-tier validation plan: 8
  deterministic script tests, 5 guardrail enforcement tests, 3 live demos
  (2026-06-27).

## Slack Home Tab Kanban Visualization (2026-06-27)

The Slack Home Tab (managed by the `slack-block-kit-enhancement` skill) now
includes a **📋 Kanban Board** section showing live board stats, blocked task
alerts, and recent tasks. Two refresh paths: auto-refresh every 5 minutes via
cron, and a manual 🔄 Refresh Board button. This gives the user a dashboard
view of the board without leaving Slack. See the `slack-block-kit-enhancement`
skill for implementation details.

## Recovering stuck workers

When a worker profile keeps crashing, hallucinating, or getting blocked by its own mistakes (usually: wrong model, missing skill, broken credential), the kanban dashboard flags the task with a ⚠ badge and opens a **Recovery** section in the drawer. Three primary actions:

1. **Reclaim** (or `hermes kanban reclaim <task_id>`) — abort the running worker immediately and reset the task to `ready`. The existing claim TTL is ~15 min; this is the fast path out.
2. **Reassign** (or `hermes kanban reassign <task_id> <new-profile> --reclaim`) — switch the task to a different profile (one that exists on this setup) and let the dispatcher pick it up with a fresh worker.
3. **Change profile model** — the dashboard prints a copy-paste hint for `hermes -p <profile> model` since profile config lives on disk; edit it in a terminal, then Reclaim to retry with the new model.

Hallucination warnings appear on tasks where a worker's `kanban_complete(created_cards=[...])` claim included card ids that don't exist or weren't created by the worker's profile (the gate blocks the completion), or where the free-form summary references `t_<hex>` ids that don't resolve (advisory prose scan, non-blocking). Both produce audit events that persist even after recovery actions — the trail stays for debugging.
