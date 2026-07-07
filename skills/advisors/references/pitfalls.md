# Pitfalls

Organized by category. See [Patterns](patterns.md) for the pattern catalog and
[Quick Reference](quick-reference.md) for command summaries.

## Token Efficiency

### Keep SKILL.md lean — extract code to scripts/

The original advisors SKILL.md was 54 KB (1268 lines), the heaviest in the
autonomous-ai-agents category. The `task-decomposer` skill (9 KB) demonstrates
the target shape: focused prose with schema definitions, no redundant examples.
When adding new patterns or code snippets, prefer:

1. **`scripts/`** — re-runnable code the agent invokes directly (like
   `prompt_model.py`)
2. **`references/`** — session-specific detail, error transcripts, domain notes
3. **`templates/`** — starter files meant to be copied and modified

Inline Python examples in SKILL.md are convenient but inflate the token cost
of every skill load. Extract them to scripts and reference with short code
blocks. See `references/token-efficiency-review-2026-07-05.md` for the full
cross-skill review.

## Output Quality

### Advisor output should be at a logical level, not implementation detail

When the user asks advisors to review skills, plans, or architecture, the
prompt should explicitly request **logical-level review with action items**,
not implementation details. The user's preference (2026-07-05): "I only want
a review and action items at a logical level. If you do come back with action
items from the consensus, pass that to dev loop to go implement for me."

**Controller workflow:**
1. Frame the advisor prompt to ask for logical-level findings + action items
2. Synthesize consensus into a table of action items
3. Route consensus action items to devloop for implementation
4. Report: what was found, what was fixed, what's pending

**Wrong:** Advisors produce 50-line code patches with implementation details.
**Right:** Advisors produce "Fix X in Y file — the integration test example
is tautological" — then the controller routes to devloop.

### Advisor findings need verification — false positives are common

In the v6 quality review, 3 of Kimi's 4 HIGH findings were false
positives: `dispatch_single()` not error-checked (it is, at lines 1199/1263/1472),
`iteration_states` not reset (it is, at line 1159), and `_emit_iteration_summary`
doesn't check LEARNINGS exists (it does, at line 1582). The advisor correctly
identified the code patterns to check but didn't verify them against the actual
code before reporting them as bugs.

**Rule:** After receiving advisor findings, verify each one against the actual
code before applying fixes. Advisors are reasoning from context you provide —
they don't have live access to the codebase. A finding that sounds plausible
may be contradicted by code the advisor couldn't see. This is especially true
for code-review panels where the advisor receives a partial view of the code.

**Pattern:** After advisor results land, run a verification pass:
1. For each HIGH finding, grep the actual code to confirm the issue exists
2. For each MEDIUM finding, spot-check at least one
3. Report false positives explicitly in the consolidated results
4. Only apply fixes for confirmed issues

### 3-seat panels catch more than 2-seat panels

In the v6 SDLC state machine quality review (2026-06-28), a 3-seat panel
(DeepSeek + Kimi + GLM) found 14 issues total. GLM caught 6 issues that
DeepSeek and Kimi both missed — including thinking levels, toolsets, pytest
flag conflicts, and regex bugs. A 2-seat panel would have shipped with 6 bugs.

**Rule:** For code review and quality assurance, use 3 seats minimum. The
marginal cost of the 3rd seat (~$0.02) is negligible compared to shipping
with bugs. For simple lookups or yes/no questions, 1-2 seats is fine.

### 2-seat panels catch bugs that 1-seat panels miss

In the v3.4 dispatch_advisors.py self-review (2026-07-05), a 2-seat panel
(DeepSeek + Kimi) reviewed the fix plan. DeepSeek found 6 bugs that Kimi
missed — including the double-timeout bug in `synthesize()`, 0-byte output
filter gap, unreadable-file handling, and missing ThreadPoolExecutor timeout.
A 1-seat panel would have shipped with 6 bugs.

**Rule:** Even for plan review (not code review), use 2 seats minimum. The
second seat catches bugs the first seat's training lineage is blind to.
Different models have different blind spots — the overlap is where bugs hide.

### Consensus model as a panel member

If the synthesis model also answered independently, it's biased toward its own
answer. Use a different model for synthesis, or note the self-bias.

### DeepSeek API drops mid-stream for long outputs — use GLM-5.2 as fallback

When dispatching DeepSeek V4 Pro for long structured outputs (improvement plans,
design reviews, synthesis), the API connection can drop mid-stream (exit code 1,
partial output). The subprocess exits with code 1 and the output file contains
only the first portion of the response.

**Symptoms:** Exit code 1, output file exists but is truncated (ends mid-sentence
or mid-section), stderr may show connection errors. The dispatch appeared to
complete normally (no timeout) but the output is incomplete.

**Fix:** Retry once with a shorter timeout. If it fails again, switch to
`glm-5.2:cloud` — it's reliable for long structured outputs and consistently
delivers complete results.

**Decision rule:**

| Task type | Model | Why |
|---|---|---|
| Short targeted review (<2K chars expected) | deepseek-v4-pro:cloud | Fast, analytical |
| Code-level analysis, architectural reasoning | deepseek-v4-pro:cloud | Best for reasoning |
| Long structured output (improvement plans, synthesis) | glm-5.2:cloud | Reliable, no mid-stream drops |
| Advisor panel synthesis (Pattern 1 Step 4) | glm-5.2:cloud | Already the default |
| Multi-file design review (>5K chars expected) | glm-5.2:cloud | Consistent delivery |

**Real example (2026-06-29):** DeepSeek was dispatched to generate an improvement
plan for the v3.1 concurrent dispatch system. It read 7 source files and started
outputting, but the API dropped mid-stream twice (both attempts). GLM-5.2
succeeded on the first attempt, producing a comprehensive 128-line plan that
caught critical bugs (P0-1/P0-2 signature mismatch) the controller had missed.

## Configuration and Defaults

### Config deference: do not override Hermes config defaults

The `--max-turns` flag defaults to `None` in `prompt_model.py`, which means
Hermes config `agent.max_turns` (currently 120) is the source of truth. Do
NOT hardcode `--max-turns` in advisor dispatches unless the user explicitly
requests a specific value. The same applies to `--timeout` — only override
when there's a domain-specific reason (e.g., `execute_code` 5-min cap).

This is the same principle as the `ask` skill's config-deference rule: skills
should NOT impose their own limits when Hermes already has a config key for it.

### Stale imports when shared constants are removed from model_utils.py

`prompt_model.py` imports constants from `model_utils.py` (e.g., `DEFAULT_MAX_TURNS`).
When those constants are removed from `model_utils.py` during a config-deference
cleanup (replacing hardcoded defaults with `None` to let Hermes config win),
`prompt_model.py` breaks with `ImportError: cannot import name 'DEFAULT_MAX_TURNS'`.
This is the same class of bug that affected `ask.py` — any consumer of
`model_utils.py` that imports shared constants is vulnerable.

**Symptoms:** `prompt_model.py` exits immediately with code 1 before the agent
loop starts. The error is in the import block, not in agent reasoning. All
seats fail with the same error in under 1 second.

**Recovery:**
1. Remove the stale import from `prompt_model.py`
2. Change the argparse default from the removed constant to `None`
3. Update the help text to say "Hermes config agent.max_turns" instead of the old constant name
4. Verify: `python3 -c "import py_compile; py_compile.compile('prompt_model.py', doraise=True)"`
5. Verify downstream consumers still import correctly: `from model_utils import dispatch_single`

**Prevention:** After removing any constant from `model_utils.py`, grep all
consumers:
```bash
grep -rn "DEFAULT_MAX_TURNS\|OLD_CONSTANT_NAME" /opt/data/skills/
```
This includes `prompt_model.py`, `ask.py`, `pipeline.py`, `sdlc.py`, and any
other script that imports from `model_utils.py`. The `ask` skill's "Default
Changes Must Audit All Entry Points" pitfall covers the same pattern.

## Context and Data Channel

### Separate data channel from context — do not read review files into main context

**Principle:** The controller's running conversation should carry short prompts
and file paths — never the full data payload. Review data (5-15K chars per seat)
is write-once, read-once: it enters context only through the synthesis model
reading from disk, never through the controller reading raw review files.

This applies to **both directions**:
1. **Dispatch (context → seats):** Write the brief to disk, dispatch seats with
   file references (`-t file`). Do NOT pass 50K of context via `--context` inline.
2. **Synthesis (seats → controller):** Dispatch GLM synthesis reading seat files
   from disk. Do NOT read raw review files into the controller's context.

Every synthesis step (Pattern 1 Step 4, Pattern 5 Step 4, Pattern 6 Rounds 2+4)
must be dispatched to GLM via `prompt_model.py -t file` or `dispatch_advisors.py`.
Do NOT read the raw review files into your main context. Each review is 5-15K
chars — loading 3-6 of them pollutes the running conversation with 30-90K chars
that are never useful again after synthesis.

**Wrong:** Read all review files into context, reason about them, write
synthesis inline.

**Wrong:** Pass 50K context via `--context "$(cat design.md)"` — the context
data enters the controller's `execute_code` call and conversation transcript.

**Right:** Use `dispatch_advisors.py` — write brief to disk, dispatch seats with
file references, dispatch GLM synthesis reading seat files from disk. You read
only the small synthesis file (~1-2K chars) into your context to report to the user.

The synthesis model is GLM (not a panel member) to avoid self-bias. See the
"Consensus model as a panel member" pitfall above.

**When to use which:** See the "Context threshold" pitfall below for the
decision table. Rule of thumb: file-reference for multi-seat panels, inline
OK for single-seat queries with small, throwaway context.

### Context threshold: when to use file-reference vs inline

The file-reference pattern has overhead: writing a brief file, passing `-t file`
to the seat, the seat reading the file from disk. For small context, this overhead
isn't worth it — inline `--context` is fine. For large context, the inline
approach pollutes the controller's conversation transcript with data that's
write-once, read-once and never useful again after synthesis.

**The real cost is cumulative transcript pollution, not context window pressure.**
Even 2K chars of inline context costs ~40K chars over a 20-turn session (each
turn re-sends the full transcript). The same data via file-reference costs ~2.8K
chars total (one file path per turn). The issue isn't fitting in the context
window — it's that every byte of inline data is re-sent on every subsequent turn.

**Decision table (use as rationale, not as code):**

| Context size | Approach | Rationale |
|---|---|---|
| < 2K chars | Inline `--context` | Overhead of file I/O > transcript cost |
| 2K–5K chars | Either — controller's judgment | Marginal either way |
| 5K–50K chars | File-reference (`-c` or `dispatch_advisors.py`) | Transcript pollution dominates |
| > 50K chars | File-reference + `-t file` (model reads from disk) | Cumulative cost over session is prohibitive |

**Rule of thumb for the controller:** File-reference for multi-seat panels;
inline OK for single-seat queries under ~5K. The decision table is supporting
rationale — the controller needs the simple heuristic, not the table.

**Note:** ARG_MAX (shell argument size limit) is NOT the constraint here —
`dispatch_advisors.py` writes briefs to disk and never passes large context via
command-line arguments. The `--context-file` flag in `prompt_model.py` also
avoids ARG_MAX. The real constraint is cumulative transcript cost.

### File-reading review tasks need `-t file,terminal`

When dispatching an advisor to review source code and update a plan file
in-place (the SDLC plan review pattern), the advisor needs `-t file,terminal`
toolsets. Without file access, the advisor can only read context passed via
`--context` or `--context-file`, which may hit the OS argument size limit for
large codebases. With `-t file,terminal`, the advisor reads source files from
disk and writes the updated plan back — no context-size limit.

```bash
# Plan review pattern: advisor reads source + writes updated plan
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review the plan at /path/to/plan.md against source files in /path/to/src/.
         Update the plan with any fixes found." \
    -t file,terminal \
    --timeout 600 \
    -o /tmp/review-output.md
```

This pattern was used for all 4 review passes in the SDLC plan design session
(2026-06-28). The advisor reads 3+ source files (model_utils.py 897 lines,
sdlc.py 1317 lines, pipeline.py) plus the plan itself, then writes the updated
plan back to disk. Without `-t file`, the context would need to be passed via
`--context-file` which is fragile for multi-file reviews.

### Advisor times out reading too many source files → re-dispatch with tighter scope

When an advisor with `-t file,terminal` times out (300s default), it's usually
because it's reading too many source files — each file read is a tool call with
model latency. The advisor spends its entire time budget on file I/O and never
reaches the reasoning phase.

**Symptoms:** Exit code 1 (timeout), no output file written, or output file is
empty/truncated. The dispatch appeared to run normally but produced nothing.

**Fix — re-dispatch with tighter scope:**
1. Remove `-t terminal` — keep only `-t file` (the advisor doesn't need to run
   commands, just read files)
2. Pass the plan as a context file (`-c /path/to/plan.md`) instead of asking the
   advisor to read it from disk — saves one tool call
3. Reduce `--timeout` to 180s (if the advisor can't finish in 3 minutes with
   the tighter scope, the prompt is too broad)
4. Narrow the prompt: ask the advisor to review the plan text (already in
   context) rather than reading source files. The plan should already contain
   the relevant code snippets and line references.

**Real example (2026-07-06):** DeepSeek was dispatched with `-t file,terminal`
to review a documented implementation plan against source files. It timed out
at 300s — spent all its time reading `stream_consumer.py` (1700+ lines),
`run.py` (18000+ lines), and adapter files. Re-dispatched with `-t file` only,
plan as context file, 180s timeout, and a prompt that said "review the plan
text below" instead of "read the plan and source files." Completed in 56.7s
with 9,581 chars of detailed findings.

**Prevention:** For plan reviews where the plan already contains code snippets
and line references, pass the plan as context and ask the advisor to review the
plan text — don't ask it to re-read the source files. Reserve `-t file,terminal`
for cases where the advisor needs to verify claims against live code that isn't
in the plan.

### Sequential chains: ensure context file is complete BEFORE dispatching

When dispatching a sequential review chain (Pattern 2), the downstream model's
context file must include the upstream model's full output. Write the complete
file first, verify it, then dispatch. Dispatching before the context is ready
wastes a call — you'll have to kill and re-dispatch.

**Wrong (this session):**
1. Write prompt file for Kimi (without DeepSeek's review)
2. Dispatch Kimi via `terminal(background=true)`
3. Append DeepSeek's review to the context file (too late — Kimi is already running)
4. Kill Kimi, re-dispatch with complete context

**Right:**
1. Wait for DeepSeek to complete
2. Read DeepSeek's review
3. Write the complete context file (prompt + DeepSeek's full review)
4. Verify the file has the expected content (`wc -c`, check for key sections)
5. Dispatch Kimi

This applies to any chain where model B needs model A's output — write the
file, check it, then dispatch. The same principle applies to Pattern 5
(adversarial meta-review) and Pattern 6 (deliberation) where later rounds
depend on earlier output.

### Backticks and special characters in prompts break shell commands

When the prompt contains backticks (`` ` ``), dollar signs (`$`), or other
shell-special characters, the shell interprets them before `prompt_model.py`
ever sees the argument. Backticks trigger command substitution, consuming
subsequent arguments and causing cryptic errors like:

```
prompt_model.py: error: the following arguments are required: -p/--prompt
```

This happens because the backtick-substituted text ate the `-p` flag. The
subprocess exits with code 2 before Python even starts.

**Symptoms:** Exit code 2, "the following arguments are required" error,
immediate failure (0s elapsed). The command looks correct but the shell
mangled it.

**Fix:** Always use `--context-file` (`-c`) for prompts containing backticks,
code blocks, shell commands, or any special characters:

```bash
# BEFORE (fails — backticks trigger shell command substitution):
python3 prompt_model.py -m kimi-k2.7-code:cloud \
    -p "Run: cd /path && uv run pytest tests/ -v -k 'not live' 2>&1 | tail -20"

# AFTER (safe — prompt goes through a file, not the shell):
echo "Run: cd /path && uv run pytest tests/ -v -k 'not live' 2>&1 | tail -20" > /tmp/prompt.txt
python3 prompt_model.py -m kimi-k2.7-code:cloud \
    -c /tmp/prompt.txt -o /tmp/result.md
```

**Rule of thumb:** If the prompt contains backticks, `$()`, `&&`, `|`, `>`,
`<`, or `;`, use `--context-file`. The only safe characters for inline `-p`
are alphanumerics, spaces, and basic punctuation.

### Argument list too long (OSError: Errno 7)

When passing large context via `--context` on the command line, the OS may
reject the argument list if it exceeds `ARG_MAX` (typically 128KB-2MB on
Linux). This manifests as `OSError: [Errno 7] Argument list too long`.

**Symptoms:** The subprocess.run() call fails immediately with OSError before
the Python script even starts. The error message includes the full command
path.

**Fix:** Use `--context-file` instead of `--context` for large context:

```python
# BEFORE (fails with large context):
subprocess.run([sys.executable, SCRIPT, "-m", model, "-p", prompt,
    "--context", large_context_string, ...])

# AFTER (works regardless of size):
import tempfile
with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
    f.write(large_context_string)
    ctx_path = f.name
subprocess.run([sys.executable, SCRIPT, "-m", model, "-p", prompt,
    "-c", ctx_path, ...])
```

Or for the simplest case, just let the model read files from disk — pass a
short prompt that says "read the plan at /path/to/plan.md" and give the model
`-t file` toolsets. The model reads the file itself rather than receiving it
as context. This is the preferred approach for very large context (100K+ chars).

**Threshold:** ~100KB of context is the danger zone. Below 50KB, `--context`
is fine. Between 50-100KB, test it. Above 100KB, always use `--context-file`
or file-reading approach.

### Both context_file AND inline context — use `if`, not `elif`

When a function accepts multiple context sources (e.g., `context_file` and
`context`), use independent `if` blocks for each source. An `elif` silently
drops later sources when an earlier one is present — the user expects ALL
provided context to be included, not just the first one found.

**Wrong:**
```python
if context_file:
    content = read_file(context_file)
elif context:  # BUG: dropped when context_file is also provided
    content += context
```

**Right:**
```python
if context_file:
    content = read_file(context_file)
if context:  # Independent — both sources included
    content += "\n\n" + context
```

This applies to `prepare_brief()`, prompt construction, and any function that
accepts multiple optional context parameters. The `elif` pattern is a
composability anti-pattern — it assumes context sources are mutually exclusive
when they're meant to be additive. Caught by both Kimi and DeepSeek in the
v3.4 self-review (2026-07-05).

## Execution Environment

### Seat timeout

Default 300s per call. If a seat exceeds it, the subprocess is killed and
returns exit code 2. Proceed with completed seats — a 2-seat result is useful.

### Model unavailable

If a model is down, `hermes chat` returns an error. The script writes the error
to stderr and exits with code 1. Check the file exists before reading.

### Token limits

The default `--max-turns` is `None`, which means Hermes config `agent.max_turns`
is the source of truth (currently 120). Do not override `--max-turns` in
advisor dispatches unless the user explicitly requests a specific value.
The Hermes config already sets a sensible limit — hardcoding a lower value
in the advisors skill silently caps every call.

### Concurrent subprocess limits

Each call spawns a `hermes chat` process. With 5 parallel seats, that's 5
processes. Watch system resources on constrained hardware.

### execute_code interruption kills all subprocesses

When the advisors dispatch runs inside `execute_code` with `concurrent.futures`,
a user interruption (Ctrl+C, "Operation interrupted") kills the entire
`execute_code` process — including all in-flight `prompt_model.py` subprocesses.
Only seats that already completed survive; any mid-flight seat is lost.

**Symptoms:** You see "Operation interrupted" in the output, and only 1-2 of
3+ seats have output files. The remaining seats never wrote their files.

**Recovery:**
1. Read the output files that DID complete — partial results are still useful
2. Re-dispatch only the missing seats (not the full panel)
3. For the re-dispatch, use individual `terminal()` calls instead of
   `execute_code` with `concurrent.futures` — individual calls survive
   interruption better because each is a separate tool invocation

**Prevention:** For high-stakes panels where losing seats is costly, dispatch
each seat as a separate `terminal(background=true)` call with
`notify_on_complete=true`. This is slower (sequential tool calls) but each
seat is independently tracked and survives interruption. Reserve
`execute_code` + `concurrent.futures` for panels where partial results are
acceptable.

### execute_code has a 5-minute hard timeout — use terminal(background=true) for long dispatches

`execute_code` has a 5-minute (300s) hard timeout. A 15-turn advisor agent reviewing
multiple source files and writing an updated plan can take 3-8 minutes — well within
the `--timeout 600` you'd set on `prompt_model.py`, but exceeding `execute_code`'s cap.
The subprocess is killed mid-review and the output file is never written.

**Symptoms:** `execute_code` returns with a timeout error after exactly 5 minutes.
The advisor's output file doesn't exist or is empty. The advisor was mid-turn when killed.

**Fix:** Use `terminal(background=true, timeout=600, notify_on_complete=true)` instead
of `execute_code` for any advisor dispatch expected to take >4 minutes:

```python
# BEFORE (fails for long reviews):
execute_code(code=f"""
import subprocess, sys
subprocess.run([sys.executable, SCRIPT, "-m", "deepseek-v4-pro:cloud",
    "-p", "Review the plan...", "-t", "file,terminal",
    "--timeout", "600",
    "-o", "/tmp/review.md"], timeout=600)
""")

# AFTER (works for any duration):
terminal(
    command='python3 /opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py '
            '-m deepseek-v4-pro:cloud '
            '-p "Review the plan at /path/to/plan.md against source files. '
            'Update the plan with any fixes found." '
            '-t file,terminal --timeout 600 '
            '-o /tmp/review.md',
    background=True,
    notify_on_complete=True,
    timeout=600
)
```

**Threshold:** Use `terminal(background=true)` for any advisor dispatch with
`--timeout >= 300`. For quick dispatches (`--timeout <= 120`),
`execute_code` is fine. The `--max-turns` threshold no longer applies
because we don't override it — Hermes config is the source of truth.

### execute_code sandbox persistence — do full flow in one call

`execute_code` runs in a **fresh sandbox subprocess** each time. The
`AdvisorDispatch` object does NOT survive between `execute_code` calls.
Splitting `prepare_brief()` + `dispatch()` into one call and `synthesize()`
into another fails because the second call creates a new `AdvisorDispatch`
with no `seat_results`:

```
ValueError: Call dispatch() first
```

**Fix:** Do the full flow in a single `execute_code` call:

```python
ad = AdvisorDispatch(outdir='/tmp/advisors')
ad.prepare_brief(question="...", context_file="data.md")
ad.dispatch(seats=[("deepseek-v4-pro:cloud", "Reasoner"), ...])
ad.synthesize()
print(ad.read_synthesis())
```

**Alternative:** If the dispatch takes >5 min (exceeding `execute_code`'s
timeout), use `terminal(background=true, notify_on_complete=true)` for the
dispatch, then manually read seat files and dispatch GLM synthesis via a
separate `terminal()` call. See the "execute_code has a 5-minute hard timeout"
pitfall above.

### Local models may time out in agent loops

Local models (qwen3.6:35b-a3b, qwen3-coder-next:q4_K_M) are fast for single
inference but slow for multi-turn agent loops. Each tool call adds 0.5-3s of
model latency. A 5-turn agent loop on a local model can take 2-5 minutes vs
30-60s on cloud models. For time-sensitive panels, skip the local seat
entirely rather than overriding `--max-turns`. If the user explicitly requests
a lower turn limit for a local seat, pass `--max-turns` only for that seat.

### Gateway restarts kill the dispatch process, not the seat subprocesses

`hermes chat -q` subprocesses are independent of the gateway process — a
gateway restart does NOT kill running seat subprocesses. However, the
**dispatch process** (the `terminal(background=true)` or `execute_code` call
that orchestrates the seats) IS killed by a gateway restart. This means:

- **Seats that already completed** before the restart survive — their output
  files are on disk
- **Seats still running** when the restart hits are orphaned — they may
  complete but the dispatch process can't collect their results
- **The dispatch process itself** is dead — you must re-dispatch from scratch

**Recovery:**
1. Check the output directory for completed seat files
2. If all seats completed before the restart, skip to synthesis
3. **If using `dispatch_advisors.py`:** re-dispatch the full panel — the
   dispatch process state (seat tracking, manifest) is lost, so you can't
   reliably re-dispatch individual seats.
4. **If using raw `prompt_model.py` via `terminal(background=true)`:** you
   CAN re-dispatch only the missing seats. Each seat is an independent
   `terminal()` call with no shared dispatch state. Check which output files
   exist, re-dispatch only the missing ones. This was proven in practice
   (2026-07-06): a 2-seat panel lost DeepSeek to a restart; re-dispatching
   only DeepSeek worked correctly.
5. Use `dispatch_advisors.py` for new work — it writes a `seats.json` manifest
   that survives restarts, making recovery simpler regardless.

**Real example (2026-07-05):** A 2-seat quality review was dispatched via
`terminal(background=true)`. The gateway restarted twice during the review.
Both times, the dispatch process was killed but the brief file survived on
disk. The review was re-dispatched 3 times before both seats completed
successfully. The brief file (114KB, 3 source files) was written once and
reused across all 3 attempts.

**Prevention:** For high-stakes panels where losing the dispatch process is
costly, use `dispatch_advisors.py` — it writes a manifest and brief to disk
before dispatching, so re-dispatch is a single command. The brief file is
idempotent (same content every time), so re-dispatch doesn't waste tokens on
re-writing it.

### Session ID goes to stderr in quiet mode

When `hermes chat -q` runs in quiet mode, the session ID is printed to
**stderr**, not stdout. If you're capturing output with `subprocess.run` and
only reading `stdout`, you'll miss the session ID. Always capture both:

```python
r = subprocess.run(cmd, capture_output=True, text=True)
# Session ID is in r.stderr, not r.stdout
```

This matters for the `ask` skill's session memory feature — it reads the
session ID from stderr to enable conversational follow-up queries.

## Script-Specific Behaviors

### CLI uses subcommands — `--brief` is not a top-level flag

`dispatch_advisors.py` uses argparse subcommands (`run`, `prepare`, `dispatch`,
`synthesize`). Passing `--brief` as a top-level flag (without a subcommand)
produces `error: unrecognized arguments: --brief`. The correct invocation is:

```bash
# Wrong — --brief is not a top-level flag
python3 dispatch_advisors.py --brief /tmp/brief.md --outdir /tmp/advisors

# Right — use the run subcommand
python3 dispatch_advisors.py run --question "..." --context-file data.md --outdir /tmp/advisors
```

**Symptoms:** Exit code 2, "unrecognized arguments" error, immediate failure.
The controller may try the same wrong syntax multiple times before discovering
the subcommand structure. Always check `--help` first when the CLI shape is
uncertain.

### parse_seats — pipe syntax only, no colon disambiguation

`parse_seats` in `dispatch_advisors.py` uses **pipe syntax** (`model|Role`) for
explicit role assignment. Colons in model names are always preserved — they
are NOT used for role parsing. This eliminates the entire class of
disambiguation bugs that the previous provider-allowlist approach had.

```
# Correct — pipe syntax for explicit roles
deepseek-v4-pro:cloud|Reasoner,kimi-k2.7-code:cloud|Coder,qwen3.6:35b-a3b|Local Lens

# Correct — no role (defaults to model name as role)
deepseek-v4-pro:cloud,kimi-k2.7-code:cloud

# Also correct — local model tags with non-standard suffixes (no special handling needed)
qwen3-coder-next:q4_K_M
```

### parse_seats — whitespace-only input needs post-parse empty check

`parse_seats("  ,  ")` produces `["", ""]` after splitting on commas and
stripping each segment. The early guard `if not seats_str.strip()` returns
`True` for `"  ,  "` (`.strip()` → `","` which is truthy), so the early
return doesn't fire. The loop skips empty segments, producing an empty list.

**Fix:** Add a post-parse empty check: `if not seats: return list(DEFAULT_SEATS)`.
This catches the case where all segments were whitespace/empty after stripping.

**Test:** `test_whitespace_only_returns_defaults` in `test_dispatch_advisors.py`.

### concurrent.futures.as_completed() returns finish order, not input order

`dispatch()` in `AdvisorDispatch` uses `concurrent.futures.as_completed()` to
collect results as they finish. This means `seat_results[0]` is the **fastest
finisher**, not the first listed seat. `read_seat(0)` returns the wrong seat.

**Fix (applied):** Track the input index in `dispatch_seat()`, sort results by
index before returning. The `seats.json` manifest is also written in input order.

### seats.json manifest — don't reconstruct metadata from filenames

`cli_synthesize` originally reconstructed seat metadata by scanning `seat-*.md`
filenames in the output directory. This produced wrong metadata (role = filename,
model = blank) and picked up stale files from prior runs.

**Fix (applied):** `dispatch()` writes a `seats.json` manifest with full metadata
(role, model, outfile, returncode). `cli_synthesize` reads the manifest instead
of scanning filenames.

### prompt_model.py imports — cwd-independent via __file__-relative sys.path

`prompt_model.py` imports from `model_utils.py` which lives in
`/opt/data/skills/productivity/ask/scripts/`. The script uses `__file__`-relative
`sys.path` setup, so it resolves imports correctly regardless of the working
directory the subprocess runs from.

**Note:** `dispatch_advisors.py` still passes `cwd=ASK_SCRIPTS_DIR` to
`subprocess.run()` as a defensive measure, but this is not strictly required
for imports. The `cwd` matters if the advisor prompt references relative paths
— always resolve `outdir` to absolute before dispatch to avoid path resolution
issues across different working directories.

### prepare_brief() signature: context_file (singular) + extra_context_files (plural)

`AdvisorDispatch.prepare_brief()` accepts `context_file` (singular, one file) and
`extra_context_files` (plural, list of additional files). There is no
`context_files` parameter. Passing `context_files=[...]` produces:

```
TypeError: AdvisorDispatch.prepare_brief() got an unexpected keyword argument 'context_files'. Did you mean 'context_file'?
```

**Fix:** Use `context_file=` for the primary file and `extra_context_files=` for
additional files:

```python
ad.prepare_brief(
    question="...",
    context_file="/path/to/primary.md",
    extra_context_files=["/path/to/secondary.md", "/path/to/tertiary.md"],
)
```

## Synthesis and Workflow

### Synthesis dispatch: use foreground subprocess.run(), not background terminal()

The code examples in Patterns 1, 5, and 6 use foreground `subprocess.run()` for
synthesis — it blocks until the model finishes, then you read the output file.
No polling, no timers, no status updates needed. The synthesis model (GLM) reads
files from disk and writes the result — this is a single-turn file-read +
file-write operation that takes 30-90s.

**Wrong (this session):** Dispatch synthesis via `terminal(background=true)`
without `notify_on_complete=true`, then poll `process(action='poll')` every
3-5 seconds for 50+ seconds. This wastes 11+ tool calls and clutters the
conversation with empty poll results.

**Right:** Use `subprocess.run()` as shown in the code examples. It blocks for
30-90s and returns the result. One tool call, no polling.

**If you must use background mode** (e.g., synthesis expected to take >5 min):
always set `notify_on_complete=true` and do NOT poll manually. The system
auto-notifies on completion. If you want mid-run progress, poll at 30-60s
intervals — never every few seconds.

## Meta-Patterns

### Eat your own dogfood — use advisors to review the advisors skill

When making changes to the advisors skill itself (SKILL.md, dispatch_advisors.py,
prompt_model.py), use the advisors pattern to quality-review the changes. This
validates the architecture and catches bugs the controller missed.

**Process:**
1. Write a brief with the full diff + design rationale to disk
2. Dispatch 2-3 seats to review the changes
3. Synthesize via GLM — read only the synthesis into context
4. Fix confirmed bugs, re-test, commit

**Real example (2026-07-05):** Used `dispatch_advisors.py` to review itself.
2-seat panel (DeepSeek + Kimi) found 10 confirmed bugs in the v3.4 changes.
The file-referenced architecture worked: 29K brief + 20K seat outputs stayed
on disk; only 9.3K synthesis entered controller context. See
`references/self-review-dispatch-advisors-2026-07-05.md` for the full run.

**Real example (2026-07-05, round 2):** After fixing the 10 bugs, Kimi reviewed
the 5K threshold and found it arbitrary. DeepSeek then reviewed the fix plan
and found 6 additional bugs Kimi missed. See
`references/deepseek-plan-review-2026-07-05.md` for the full run.

## Non-English Models

### Non-English models (glm-5.2:cloud)

The script auto-appends "respond in English only" for known non-English models.
To add a new one, add it to `NON_ENGLISH_MODELS` in `prompt_model.py`.
