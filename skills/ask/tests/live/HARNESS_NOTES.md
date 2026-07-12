# Live-suite harness notes (macOS host → `hermes` container)

Gotchas discovered while building `run_live_suite.sh` (LC1–LC11) on 2026-07-11.
Each cost real iterations; capture-once so the next author doesn't re-burn them.
The runner runs on the **host** and wraps every invocation as `docker exec hermes …`
(container name `hermes`; skill path inside = `/opt/data/skills/productivity/ask`).

## Shell / tooling portability

- **macOS `bash` is 3.2.** No `${var,,}` / `${var^^}` case-folding, no `mapfile`,
  no associative-array niceties. Fold case with `tr '[:upper:]' '[:lower:]'`.
  `set -uo pipefail` (NOT `-e`) — every case must run and report, not abort the suite.
- **`jq -er` treats a JSON `null` as a failure exit.** A legitimate
  `dispatch_result.content == null` (the None-contract case) then looks like a jq
  error, not a passing assertion. Use `jq -r` plus an explicit path-existence check
  (`jq -e 'has("content")'` separately from reading the value), or a `python3 -c`
  reader. Reserve `-e` for "field must be truthy" checks only.
- **Gate/workflow cases need the venv Python, not bare `python3`.** `gate_driver.py`
  imports `yaml` (PyYAML); the container's system `python3` doesn't have it. Use
  `/opt/data/.venv/bin/python3`.
- **Regex parens in `grep`/`rg` assertions are groups, not literals.** Asserting the
  comparison-mode banner text `--thinking low: running sequentially (not parallel)`
  requires escaping the parens (`\(not parallel\)`); unescaped, you search for text
  that never existed and the assertion silently never matches.

## Hermes-specific traps

- **There is no `hermes config get`.** Real subcommands: `show / edit / set / path /
  env-path / check / migrate`. To read a config value (e.g. verifying
  `agent.reasoning_effort` was restored after a `--thinking` run), call a Python probe
  `model_utils.get_reasoning_effort()`, not a CLI get.
- **Session registry is keyed by the *resolved* alias, not the one you passed.**
  `ask.py`'s reverse lookup (`_alias_for_model`) saves a session under the FIRST alias
  in `ALIASES` whose model matches — so a session from `ask fast …` can land under
  `qwen` (both resolve to the same model family). Read the registry with the same
  resolution the code uses, or you'll "lose" a session that was saved fine.
- **A per-model `--timeout 30` starves a cold dispatch.** First-call model spin-up +
  tool turns routinely exceed 30s; gate/tool cases (LC8, LC10) need ≥90s. Small
  inference-only cases (LC1) are fine at 15–20s. Keep prompts tiny and use the `fast`
  alias to stay cheap.
- **A prompt-workflow step's `acceptance:` criterion invokes the engine's live-model
  judge.** Small local models fail its strict decision protocol
  (`PromptRuntimeError: judge returned no valid decision`), failing the whole run for
  a reason unrelated to what you're testing. Omit `acceptance:` when validating loop
  *wiring* (LC10) rather than judge behavior.
- **hermes-core crashes when dispatched from a `0700` cwd** (see
  `references/upstream-blockers.md`). resumable-script locks state dirs to `0700`, so
  never point a model subprocess's `cwd` at a durable state store.

## Determinism trick — `HERMES_BIN` stub

`model_utils` honours `HERMES_BIN`. To exercise a failure/gate path at the REAL
subprocess boundary without a live model, write a stub script into the container and
pass `HERMES_BIN=/tmp/stub.sh` via `docker exec -e HERMES_BIN=…`. Used by LC3 (exit-0
empty output → one retry), LC4 (exit-2 empty output → no retry), and LC10b (a scripted
gate actor that emits the exact `{"ask": …}` protocol JSON, making the auto-answer
*wiring* deterministic independent of any live model). Branch the stub on prompt
content (ask-protocol turn vs `untrusted_human_response` turn vs answerer prompt).

## Per-case hygiene

Every case cleans up the `/tmp` state dirs, stub scripts, and YAML flows it created,
and restores any session-registry backup it took. Note: a case's own cleanup can
delete its `/tmp/*.yaml` before you manually re-probe it — recreate the YAML first.
The suite is **opt-in**, excluded from the default `-k 'not live'` run, and appends a
dated results block to `TEST_PLAN.md` per run.
