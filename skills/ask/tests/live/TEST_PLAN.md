# Ask live corner-case validation suite

## Purpose

This is an opt-in, live control-plane/data-plane validation suite for the `ask` skill against the real Hermes container. It is not CI and does not use Python mocks: normal cases invoke the public CLIs in the `hermes` container, while the explicitly labeled LC2b supplementary probe calls the real dispatcher to expose a field no public CLI currently emits. Prompts are tiny, use the small `fast` alias, and pass short explicit timeouts to keep the run inexpensive.

## How to run

From this directory, run `bash run_live_suite.sh [LC-ids...]`. With no IDs, it runs all eleven cases in LC1–LC11 order. For example, `bash run_live_suite.sh LC1 LC3` runs only those cases.

The runner writes JSONL progress records to stderr and a final PASS/FAIL table to stdout. It exits `0` when every non-flaky case passed, `1` when a non-flaky case failed, `2` for an unknown LC ID/usage error, and `10` when an environment precondition fails (for example, the `hermes` container is not running).

## Conventions and preconditions

Every Hermes/ask action is executed through `docker exec hermes ...`. The runner requires Docker access, a running container literally named `hermes`, and either `jq` or host `python3`; it prefers `jq` and falls back to a small standard-library JSON reader. `LIVE_TIMEOUT` defaults to 20 seconds and can be lowered or raised for a warm/cold local model. LC10 uses its own `LC10_TIMEOUT`, defaulting to 30 seconds, because its gate-answer path can require a second live dispatch.

`ask.py` has no `--json` output flag. Its `--emit-events` flag emits dispatcher JSONL to stderr, while its human answer is stdout. `pipeline.py --json` exposes the full pipeline dictionary, including `dispatch_result`, `pipeline_status`, `pipeline_exit_code`, and `dispatch_retries`. `gate_driver.py --json` exposes its driver result, including `status`, `exit_code`, `auto_answers`, and `rounds_used`.

The CLI only offers `--clean-sessions` for expired sessions; it has no command to delete a newly created live session. The runner snapshots and restores the session-registry file around the whole suite (and LC6 performs an inner lifecycle snapshot), so it leaves no newly registered alias entry behind. Run this suite when no other interactive use of the `fast` alias is in progress; Hermes' underlying conversation store has no public per-session delete operation and is not removed.

The session-registry key is not necessarily the alias typed at the CLI. `ask.py` reverse-maps the resolved model by first matching `ALIASES` entry; in the current container `fast` resolves to the same model as an earlier `qwen` entry, so it is saved under `qwen`. LC6 and LC8 reproduce that first-match lookup with a `model_utils.ALIASES`/`resolve_alias('fast')` probe rather than hardcoding `registry["fast"]`.

For LC5 and LC7, `agent.reasoning_effort` must already be set to a non-empty value. Hermes has no `config get` subcommand. The runner reads it through the same real library boundary that the dispatcher uses:

```sh
docker exec hermes env PYTHONPATH=/opt/data/skills/productivity/ask/scripts python3 -c "from model_utils import get_reasoning_effort; print(get_reasoning_effort())"
```

Source behavior intentionally cannot restore an initially unset value, so the runner treats an unset value as a failed precondition rather than claiming restoration.

## LC1 — silent model reroute

**Purpose.** Verify that a nonexistent model tag is silently rerouted by the real agent without contaminating the answer.

**Preconditions.** The real `fast` fallback route and `definitely-not-a-model:tag` reroute behavior are available; the container is warm enough to answer within `LIVE_TIMEOUT`.

**Invocation.**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py definitely-not-a-model:tag 'Reply only with the word rerouted.' --thinking none --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** Exit `0`; stderr JSONL contains `dispatch_end`. `ask.py` does not expose a structured `fallback` return field, so this case deliberately assesses silent rerouting by answer cleanliness only.

**Expected data plane.** Non-empty stdout answer; no stdout line contains `Primary auth failed` or `Primary model failed`.

**Flakiness.** Model-tag rerouting is a live Hermes behavior; a changed routing policy can fail this case.

## LC2 — provider fallback, notice lifted out of content

**Purpose.** Verify real provider fallback through the public CLI, and separately prove the dispatcher exposes the removed notice structurally.

**Preconditions.** Hermes recognizes `definitely-not-a-provider` as a failed primary provider and falls back to a working provider. `fast` must be available.

**Invocation (mandatory public CLI path).**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Reply only with: provider fallback probe.' --provider definitely-not-a-provider --thinking none --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** Exit `0`; stderr JSONL contains a `fallback` event whose `notice` is the fallback notice. The public `ask.py` CLI has no structured JSON output, so `fallback` is observable here as the event rather than a stdout field.

**Expected data plane.** Non-empty stdout answer with neither `Primary auth failed` nor `Primary model failed`.

**Supplementary LC2b structured-field probe.** The runner then invokes this real dispatcher boundary, not a mock:

```sh
docker exec hermes env PYTHONPATH=/opt/data/skills/productivity/ask/scripts python3 -c "import json; from model_utils import dispatch_single, resolve_alias; r=dispatch_single(resolve_alias('fast'), 'Reply only with: structured fallback probe.', '', 'file,web', None, $LIVE_TIMEOUT, 'definitely-not-a-provider'); print(json.dumps(r, ensure_ascii=False))"
```

It asserts a non-empty JSON `content`, a non-null/non-empty `fallback`, and no raw fallback phrase in serialized content. LC2b is explicitly supplementary and non-fatal if provider policy makes it unreliable; LC2’s CLI assertion is load-bearing.

**Flakiness.** Provider naming and fallback policy are installation-specific. A provider that errors instead of falling back will fail LC2.

## LC3 — transient empty output, exactly one retry

**Purpose.** Exercise the real `pipeline.py` subprocess boundary with a deterministic empty-success executable.

**Preconditions.** Pipeline triage/routing must route the tiny Python request to ordinary dispatch. The runner writes and removes `/tmp/stub-lc3.sh` inside the container.

**Invocation.**

```sh
docker exec hermes env HERMES_BIN=/tmp/stub-lc3.sh DEVLOOP_ENABLED=0 python3 /opt/data/skills/productivity/ask/scripts/pipeline.py 'Write a tiny Python function named lc3_add that returns a plus b.' --json --emit-events --timeout 5
```

The stub exits `0` with empty stdout.

**Expected control plane.** Process exit `1`; JSON has `dispatch_retries == 1`, `dispatch_result.retried == true`, and `pipeline_status == "dispatch_failed"`; stderr JSONL has `dispatch_retry`.

**Expected data plane.** The runner asserts `dispatch_result.content == null`; the failed dispatch is reported rather than treated as an answer.

**Flakiness.** If live triage no longer selects normal dispatch for this wording, the failure detail identifies routing rather than fabricating a retry result.

## LC4 — hard failure, no retry

**Purpose.** Show that a non-transient subprocess failure is not retried.

**Preconditions.** Same routing prerequisite as LC3. The runner writes and removes `/tmp/stub-lc4.sh`.

**Invocation.**

```sh
docker exec hermes env HERMES_BIN=/tmp/stub-lc4.sh DEVLOOP_ENABLED=0 python3 /opt/data/skills/productivity/ask/scripts/pipeline.py 'Write a tiny Python function named lc4_add that returns a plus b.' --json --emit-events --timeout 5
```

The stub exits `2` with empty stdout.

**Expected control plane.** Process exit `1`; JSON has `dispatch_retries == 0`, `pipeline_status == "dispatch_failed"`, and `dispatch_result.error` contains `exit 2`; stderr has no `dispatch_retry` event.

**Expected data plane.** The runner asserts `dispatch_result.content == null`.

**Flakiness.** Same live-routing sensitivity as LC3.

## LC5 — timeout while thinking, effort restored

**Purpose.** Verify a timeout produces a clean dispatch error and does not leave global reasoning effort mutated.

**Preconditions.** A non-empty original `agent.reasoning_effort` is readable using the `model_utils.get_reasoning_effort()` container probe in Conventions. The temporary wrapper must be able to proxy `/opt/hermes/bin/hermes` for `config` commands.

**Invocation.**

```sh
docker exec hermes env HERMES_BIN=/tmp/stub-lc5.sh python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Reply only with timeout probe.' --thinking high --timeout 5 --emit-events
```

The wrapper forwards `config ...` to `/opt/hermes/bin/hermes`, but sleeps for 30 seconds on `chat`.

**Expected control plane.** `ask.py` exits `1` (its CLI maps an empty/error dispatch—including a timeout—to `1`); stderr contains `Timed out after 5s`; stderr JSONL includes a failed `dispatch_end`. A post-run config read equals the pre-run value.

**Expected data plane.** No answer is emitted.

**Flakiness.** This is deterministic after preconditions. An initially unset effort is a source-defined non-restorable state and intentionally fails the precondition.

## LC6 — session lifecycle

**Purpose.** Validate capture, resume with retained context, and stale-session auto-recovery.

**Preconditions.** Hermes emits a session ID for the model resolved from `fast`. Do not run concurrent `fast` conversations while this case runs.

**Invocations.**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Remember the exact token LC6-CONTEXT-482. Reply only with that token.' --timeout "$LIVE_TIMEOUT" --emit-events
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'What exact token did I ask you to remember? Reply only with it.' --resume "<captured-session-id>" --timeout "$LIVE_TIMEOUT" --emit-events
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Reply only with LC6-RECOVERED.' --resume lc6-bogus-session-id --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** All three exit `0`. The runner snapshots then clears the registry before the first ask, ensuring it creates a fresh test session rather than implicitly resuming an unrelated alias entry. It resolves the actual first-match alias key for `fast` (currently `qwen`, not `fast`) and obtains the captured ID from that entry in `~/.hermes/ask-sessions.json`; it then verifies that entry does not retain `lc6-bogus-session-id` after recovery. The dispatcher retries a stale `Session not found` resume fresh and avoids re-saving the stale ID. The runner restores the registry snapshot afterward because `--clean-sessions` only removes expired entries, not newly created sessions.

**Expected data plane.** The resumed answer contains `LC6-CONTEXT-482`; the bogus-resume invocation returns `LC6-RECOVERED` from a fresh session.

**Flakiness.** Session retention and model obedience are live-dependent.

## LC7 — multi-model comparison and thinking serialization

**Purpose.** Verify that comparison dispatch serializes when thinking changes shared global effort, while each result retains its resolved model label.

**Preconditions.** Non-empty readable reasoning effort; `fast` is available. `LC7_MODEL_2` optionally selects a distinct second small model. It defaults to `fast`, so the default runs two real slots against the same model and still proves serialization and per-slot labels.

**Invocation.**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast "$LC7_MODEL_2" 'Reply only with comparison-ok.' --thinking low --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** Exit `0`; stderr contains `--thinking low: running sequentially (not parallel)`; the post-run effort equals the pre-run effort.

**Expected data plane.** Stdout contains at least two `🤖 <resolved-model>` result labels and an answer under each. The runner resolves both requested names using the same container `resolve_alias` logic and asserts those labels. Set `LC7_MODEL_2` to a truly distinct installed small model/tag for a more meaningful comparison.

**Flakiness.** The second configured tag must be accepted by Hermes; defaulting it to `fast` avoids dependence on an unregistered `fast2` alias.

## LC8 — tool-using dispatch

**Purpose.** Confirm a live agent can use the file toolset and retain a session.

**Preconditions.** The `fast` agent has file-tool access to `/etc/hostname`.

**Invocation.**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Use your file tool to read /etc/hostname. Reply with its contents only.' --toolsets file --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** The runner clears the registry first so this is a fresh capture, then requires exit `0` and a non-empty `session_id` at the first-match session-registry entry for the model resolved from `fast` (it can be `qwen` in the current alias map).

**Expected data plane.** Non-empty stdout includes the hostname independently read by `docker exec hermes cat /etc/hostname`.

**Flakiness.** Tool policy can prevent the read, and a model may paraphrase despite the constrained prompt.

## LC9 — auto-answer free-text clarification

**Purpose.** Exercise bounded automatic answering inside an ordinary agent session.

**Preconditions.** `fast` follows the clarification instruction and returns a resumable session.

**Invocation.**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Ask me exactly one clarifying question about my favorite color. As soon as I answer, give your final response immediately — do not ask a second question.' --auto-answer --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** Three terminal shapes pass. (1) The model asks for clarification, an `auto_answer` event is emitted with non-empty `question`, `answer`, and `round` fields plus `seam: "freetext"`, and the run exits `0`. (2) The model decides clarification is unnecessary and answers directly: exit `0`, substantive non-question output, and no `auto_answer` event; the runner records `no clarification elicited this run`. (3) As a model-sensitive fallback, exit `2` is accepted only after at least one well-formed `auto_answer` event, proving a bounded-round handoff after auto-answer actually engaged. Exit `2` with zero `auto_answer` events is a hard failure, because the clarification was never attempted (typically a missing `session_id` from the initial dispatch).

**Expected data plane.** Both exit-`0` shapes require final stdout that is non-empty and whose last line is not merely a question. A qualifying exit-`2` fallback is a control-plane handoff and does not require a final answer.

**Best-effort flaky sub-check.** The runner also asks a model to clarify forever under `--auto-answer`; it reports—but never fails the suite on—whether the expected bounded-round exit `2` occurred. This is deliberately non-fatal because live models may answer immediately rather than ask the instructed “exactly one” clarification, and that behavior alone is not a suite failure.

## LC10 — auto-answer through a durable gate

**Purpose.** Validate real-agent progress through one resumable enum gate.

**Preconditions.** `gate_driver.py` can import the mounted resumable-script runtime, its configured default worker model follows the purpose-built one-step flow, and `/opt/data/.venv/bin/python3` has PyYAML installed. Bare container `python3` lacks PyYAML and cannot load the workflow. `gate_driver.py` has no model-selection flag and its strict YAML schema rejects a `model` key, so this is the one suite case that uses the driver's source-defined default (`deepseek` alias) rather than `fast`. The runner writes the flow as a heredoc to `/tmp/gd-lc10.yaml` and removes it with `/tmp/gd-lc10` afterward.

The durable `--state-dir` is intentionally **not** passed as the live Hermes subprocess `cwd`. `journal_store` locks that store to mode `0700`; passing it as `cwd` made Hermes core's `_load_hermes_md`/`_find_git_root` path probe raise an uncaught `PermissionError` while checking `.git`. The state directory remains exclusively prompt-runtime bookkeeping; the model's file/terminal tools do not need to operate in it.

**Invocation.**

```sh
docker exec hermes /opt/data/.venv/bin/python3 /opt/data/skills/productivity/ask/scripts/gate_driver.py --flow /tmp/gd-lc10.yaml --state-dir /tmp/gd-lc10 --auto-answer fast --json --emit-events --timeout "$LC10_TIMEOUT"
```

The heredoc flow explicitly directs the first turn to emit exactly `{"ask": {"prompt": "Approve this demo?", "options": ["approved", "denied"]}}`, then to summarize after `untrusted_human_response` arrives.

**Expected control plane.** Exit `0`; JSON has `status == "completed"`, `auto_answers` length `1`, and `auto_answers[0].answer` is `approved` or `denied`; stderr JSONL has an `auto_answer` event with `seam: "gate"`. Gate enum matching accepts only the declared option after conservative presentation cleanup (surrounding quotes, trailing `. ! ? , ; :`, or the short `Answer:`, `Response:`, or `Choice:` prefix). It still rejects genuinely off-menu prose rather than fuzzy-matching it.

**Expected data plane.** The runner asserts a non-empty final `result` payload; the authored flow instructs that payload's final summary to state the selected answer.

**Flakiness and scope.** Live prompt obedience is the sensitivity. Off-menu enum handling/escalation is out of scope here and remains covered by mocked unit tests.

## LC11 — output robustness

**Purpose.** Ensure output cleaning preserves Unicode and ordinary prose that merely resembles a control message, while retaining a long answer.

**Preconditions.** `fast` follows an exact-format prompt.

**Invocation.**

```sh
docker exec hermes python3 /opt/data/skills/productivity/ask/scripts/ask.py fast 'Reply exactly as follows: first line 😀 café — 東京; second line Primary authentication failed? This ordinary prose must remain.; then a numbered list from 1 through 20.' --thinking none --timeout "$LIVE_TIMEOUT" --emit-events
```

**Expected control plane.** Exit `0`; any actual raw `Primary auth failed` or `Primary model failed` notice remains stripped.

**Expected data plane.** Stdout preserves `😀 café — 東京`, preserves `Primary authentication failed? This ordinary prose must remain.`, and reaches a word-boundary `20` list item (accepting reasonable terminators such as `.`, `)`, `:`, or whitespace). The intentionally similar phrase does not match the exact fallback-notice cleaner pattern and must not be stripped.

**Flakiness.** Exact formatting is model-sensitive; a single item-20 failure is not conclusive without a rerun. Failure output identifies the missing preservation property.

## Results log

The runner appends a dated block below after each real execution. The initial scaffold is retained, followed by any historical supervised live-run blocks.

(no runs recorded yet)

### 2026-07-11T11:21:00-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC1 | PASS | 14 | exit 0; non-empty, notice-free answer |
| LC2 | PASS | 12 | CLI clean fallback verified; LC2b supplementary direct-dispatcher fallback field non-null |
| LC3 | FAIL | 7 | dispatch_result.content expected null, got <unreadable> |
| LC4 | FAIL | 2 | dispatch_result.content expected null, got <unreadable> |
| LC5 | FAIL | 7 | precondition: agent.reasoning_effort is unset or config get failed;reasoning effort not restored (before=unset, after=unset) |
| LC6 | FAIL | 23 | could not capture fast session_id from session registry;bogus session id was retained or no fresh session captured |
| LC7 | FAIL | 12 | precondition: agent.reasoning_effort is unset or config get failed;missing serialization warning;reasoning effort not restored (before=unset, after=unset) |
| LC8 | FAIL | 14 | no session_id captured in fast registry |
| LC9 | FAIL | 78 | expected exit 0, got 2;missing auto_answer JSONL event;auto_answer event missing question;auto_answer event missing answer;auto_answer event missing round;auto_answer event seam expected freetext;final output is empty or only a clarifying question; round-cap sub-check observed exit 2 |
| LC10 | FAIL | 0 | expected exit 0, got 1;status expected completed, got error;auto_answers length expected 1, got 0;recorded gate answer not an allowed enum;missing gate auto_answer JSONL event;gate auto_answer event missing question;gate auto_answer event missing answer;gate auto_answer event missing round;gate auto_answer event seam expected gate;missing final workflow result payload |
| LC11 | FAIL | 6 | long numbered list did not reach item 20 |

### 2026-07-11T11:38:25-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC1 | PASS | 13 | exit 0; non-empty, notice-free answer |
| LC2 | PASS | 10 | CLI clean fallback verified; LC2b supplementary direct-dispatcher fallback field non-null |
| LC3 | PASS | 6 | one empty-output retry; dispatch_failed |
| LC4 | PASS | 2 | hard exit 2 failed immediately without retry |
| LC5 | PASS | 6 | timeout error and reasoning effort restored |
| LC6 | PASS | 17 | captured, resumed, and stale-session recovered |
| LC7 | FAIL | 18 | missing serialization warning |
| LC8 | PASS | 7 | file-tool answer reflects hostname and session captured |
| LC9 | PASS | 43 | free-text auto-answer completed; round-cap sub-check observed exit 2 |
| LC10 | FAIL | 4 | expected exit 0, got 1;status expected completed, got error;auto_answers length expected 1, got 0;recorded gate answer not an allowed enum;missing gate auto_answer JSONL event;gate auto_answer event missing question;gate auto_answer event missing answer;gate auto_answer event missing round;gate auto_answer event seam expected gate |
| LC11 | PASS | 11 | unicode, control-like prose, and long list preserved |

### 2026-07-11T11:39:35-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC7 | FAIL | 11 | missing serialization warning |

### 2026-07-11T11:40:26-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC7 | FAIL | 12 | missing serialization warning |

### 2026-07-11T11:58:28-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC1 | PASS | 13 | exit 0; non-empty, notice-free answer |
| LC2 | PASS | 9 | CLI clean fallback verified; LC2b supplementary direct-dispatcher fallback field non-null |
| LC3 | PASS | 5 | one empty-output retry; dispatch_failed |
| LC4 | PASS | 2 | hard exit 2 failed immediately without retry |
| LC5 | PASS | 6 | timeout error and reasoning effort restored |
| LC6 | PASS | 18 | captured, resumed, and stale-session recovered |
| LC7 | PASS | 11 | serialized qwen3.6:35b-a3b and qwen3.6:35b-a3b; effort restored |
| LC8 | PASS | 7 | file-tool answer reflects hostname and session captured |
| LC9 | FAIL | 31 | exit 0 but missing auto_answer JSONL event;auto_answer event missing question;auto_answer event missing answer;auto_answer event missing round;auto_answer event seam expected freetext; round-cap sub-check non-fatal (observed exit 0) |
| LC10 | FAIL | 24 | expected exit 0, got 2;status expected completed, got needs_human;auto_answers length expected 1, got 0;recorded gate answer not an allowed enum;missing gate auto_answer JSONL event;gate auto_answer event missing question;gate auto_answer event missing answer;gate auto_answer event missing round;gate auto_answer event seam expected gate |
| LC11 | FAIL | 21 | expected exit 0, got 1;emoji/unicode first line was not preserved;control-like ordinary prose was stripped or changed;long numbered list did not reach item 20 |

### 2026-07-11T12:01:26-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC1 | PASS | 14 | exit 0; non-empty, notice-free answer |
| LC2 | PASS | 9 | CLI clean fallback verified; LC2b supplementary direct-dispatcher fallback field non-null |
| LC3 | PASS | 2 | one empty-output retry; dispatch_failed |
| LC4 | PASS | 0 | hard exit 2 failed immediately without retry |
| LC5 | PASS | 6 | timeout error and reasoning effort restored |
| LC6 | PASS | 20 | captured, resumed, and stale-session recovered |
| LC7 | PASS | 11 | serialized qwen3.6:35b-a3b and qwen3.6:35b-a3b; effort restored |
| LC8 | PASS | 7 | file-tool answer reflects hostname and session captured |
| LC9 | FAIL | 41 | exit 0 but missing auto_answer JSONL event;auto_answer event missing question;auto_answer event missing answer;auto_answer event missing round;auto_answer event seam expected freetext; round-cap sub-check observed exit 2 |
| LC10 | FAIL | 25 | expected exit 0, got 2;status expected completed, got needs_human;auto_answers length expected 1, got 0;recorded gate answer not an allowed enum;missing gate auto_answer JSONL event;gate auto_answer event missing question;gate auto_answer event missing answer;gate auto_answer event missing round;gate auto_answer event seam expected gate |
| LC11 | PASS | 8 | unicode, control-like prose, and long list preserved |

### 2026-07-11T12:14:05-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC9 | FAIL | 49 | exit 2 with zero auto_answer events: clarification was never attempted (likely no session_id); round-cap sub-check non-fatal (observed exit 1) |
| LC10 | FAIL | 35 | expected exit 0, got 1;status expected completed, got error |

### 2026-07-11T12:17:53-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC9 | PASS | 58 | free-text auto-answer completed; round-cap sub-check non-fatal (observed exit 1) |
| LC10 | FAIL | 43 | expected exit 0, got 1;status expected completed, got error |

### 2026-07-11T12:21:56-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC10 | PASS | 88 | completed one durable gate with approved |

### 2026-07-11T12:25:52-07:00

| Case | Result | Seconds | Detail |
| --- | --- | ---: | --- |
| LC1 | PASS | 13 | exit 0; non-empty, notice-free answer |
| LC2 | PASS | 19 | CLI clean fallback verified; LC2b supplementary direct-dispatcher fallback field non-null |
| LC3 | PASS | 5 | one empty-output retry; dispatch_failed |
| LC4 | PASS | 3 | hard exit 2 failed immediately without retry |
| LC5 | PASS | 6 | timeout error and reasoning effort restored |
| LC6 | PASS | 17 | captured, resumed, and stale-session recovered |
| LC7 | PASS | 10 | serialized qwen3.6:35b-a3b and qwen3.6:35b-a3b; effort restored |
| LC8 | PASS | 10 | file-tool answer reflects hostname and session captured |
| LC9 | PASS | 57 | free-text auto-answer completed; round-cap sub-check observed exit 2 |
| LC10 | FAIL | 67 | expected exit 0, got 2;status expected completed, got needs_human;auto_answers length expected 1, got 0;recorded gate answer not an allowed enum;missing gate auto_answer JSONL event;gate auto_answer event missing question;gate auto_answer event missing answer;gate auto_answer event missing round;gate auto_answer event seam expected gate |
| LC11 | FAIL | 21 | expected exit 0, got 1;emoji/unicode first line was not preserved;control-like ordinary prose was stripped or changed;long numbered list did not reach item 20 |
