# Resumable Script Improvement Plan

This plan captures the follow-up work from the Hermes/container authoring review. The theme is simple:
keep the executable contract, docs, and live authoring eval aligned.

## What We Learned

- The default Python suite was strong for hand-written specs, but it was not enough to prove that
  Hermes can author a runnable workflow in the container.
- Live evals caught stale integration seams: unsupported `agent=` wrapper wiring, a removed
  `_convo_to_text` import, and global state-MCP setup that ran before any scenario needed it.
- Cross-run authoring needs input shape hints for every run whose input shape differs. The model can
  preserve canary secrecy and still write correct paths when it sees shape-only examples.
- Docs drift is a quality bug. `SKILL.md` and `references/workflow.md` described `agent`/MCP as active
  while `workflow._KINDS` rejected it.
- Artifact hygiene matters. Stale attempt folders made live-eval failures harder to interpret.

## Principles

- Tests are the executable contract. Docs should route readers to tests when a feature is subtle.
- First docs should be short. A future LM should not need to read every reference just to drive a
  suspended run.
- Live model evals should fail for behavioral reasons, not import/setup/artifact noise.
- Historical or planned surfaces should be explicitly labelled until they are restored or removed.
- Every new feature should have both an offline deterministic rung and, when LM authoring matters, a
  live authoring scenario.

## Roadmap

### P0: Keep Current Contract Honest

Done or started:

- Add a root `README.md` with what/where/why/examples/how-to-use.
- Add token-efficient reading activities so LM drivers choose a minimal doc path.
- Keep `tests/run.py` pinning the authoring wrapper against unsupported `agent=` kwargs and stale kind
  teaching.
- Keep L6 marked as an explicit skip while `agent` is unsupported.

Next checks:

```bash
python3 tests/run.py
evals/.venv/bin/pytest evals/author_flow_eval -v
```

### P1: Decide The `agent`/MCP Surface

Decision needed: restore `agent` as an active workflow kind or remove the remaining legacy docs and
eval bridge.

Restore path:

- Reintroduce `agent` into `workflow._KINDS`.
- Dispatch it through `_do_model_step` with a caller signature that receives `convo`, state snapshot,
  and `state_dir`.
- Restore or replace `scripts/state_mcp.py`.
- Add an offline protocol rung for state MCP and a deterministic `wf_agent` rung.
- Unskip L6 and require it in the live authoring ladder.

Remove path:

- Delete `docker_agent_caller`, state-MCP setup, and L6.
- Remove `agent` sections from `references/workflow.md`, `nested-flows.md`, and related docs.
- Keep a short changelog note explaining that `prompt` + `ASK:` is the supported model surface.

Suggested decision gate:

```bash
python3 tests/run_ladder.py --suite workflow
evals/.venv/bin/pytest evals/author_flow_eval -m L6 -v
```

### P2: Make Live Authoring Evals Easier To Run

- Add a small `evals/author_flow_eval/run.sh` wrapper that checks `docker ps`, Ollama, pytest venv, and
  then runs a selected marker.
- Write a `doctor` mode that prints the exact Hermes command path, model/provider, and container name.
- Keep artifacts clean by scenario and attempt, with a summary file that names the winning attempt.
- Add a fast `-m L1 or L5` recommendation to docs for smoke versus cross-run coverage.

### P3: Extend Authoring Coverage

Good next scenarios:

- L7: author a flow with a prompt that interrupts via `ASK:` before resolving.
- L8: author a map/reduce flow whose gate surfaces a reduced total.
- L9: author a flow with a deterministic `when` predicate instead of spending a prompt call.
- L10: author an error-handling flow with `on_error` for a registry failure.
- L11: author a flow where a bad `$${...}` currency pattern would fail evidence, then verify the
  prompt guidance avoids it.

For each scenario, include:

- Hidden canary values in runtime input.
- Shape-only authoring hints.
- Behavioral evidence over rendered prompts, terminal status, and journal records.
- Attempt artifacts saved under `evals/author_flow_eval/artifacts/`.

### P4: Reconcile Deep References

`references/workflow.md` is still useful but has historical/planned features mixed into active
guidance. Reconcile it in small passes:

- Mark each kind as active, planned, or removed.
- Split historical `agent`/`flow` material into a separate archival note if not restored.
- Align all examples with current `_KINDS`.
- Add "read this section only if..." anchors for LM readers.

Verification:

```bash
rg -n "`agent`|agent kind|on_exhausted|namespace|max_visits|flow kind" references SKILL.md README.md
python3 tests/run.py
```

### P5: CI And Regression Hygiene

- Add a docs-only check that important commands in README and TEST-PLAN are syntactically current.
- Add a small link/file-existence checker for referenced local docs and examples.
- Keep live authoring evals out of ordinary offline CI unless Hermes/Ollama are available; they should
  skip cleanly when unavailable.
- Consider a nightly or manual `author_flow_eval -v` run as the true "Hermes can author it" gate.

## Documentation Checklist For Future Changes

When changing behavior:

- Update `README.md` for the fast path if a user-facing command or concept changes.
- Update `SKILL.md` only for the skill-level contract and routing to deeper docs.
- Update the narrow reference file that owns the details.
- Add or update a test rung.
- If Hermes authoring behavior matters, add or update an author-flow scenario.
- Run `python3 tests/run.py`; run `evals/.venv/bin/pytest evals/author_flow_eval -m <marker> -v` for
  authoring changes.

