# Resumable Script

Resumable Script lets a model or human author a small JSON/YAML workflow spec, then runs it on a
durable engine that can pause for a human answer and resume later without re-running completed work.

The product is the workflow spec. The engine gives it an append-only journal, deterministic replay,
human gates, model-step repair, routing, and crash/in-doubt handling.

## What

A workflow is a state machine with these currently-supported kinds:

- `run`: call a host registry function.
- `prompt`: call an injected LM and parse/repair one JSON result.
- `ask`: pause for a human answer, then resume.
- `search`: call an injected search function.
- `map`: run a step over a list and optionally reduce the results.

Every run writes a `journal.jsonl` in its `--state-dir`. On resume, the engine starts from the top,
replays completed records from the journal, consumes the new answer at the open gate, and continues.
Completed steps do not re-execute.

## Why

Use this when a workflow needs one or more of these properties:

- A model authors the workflow structure instead of imperative code.
- A task must pause for a person, then continue hours or days later.
- Completed model calls, searches, or side effects must not run again on resume.
- Routing and failure policy should be data in the spec, not hidden in driver code.
- A host process or LM orchestrator needs a simple exit-code loop: run, surface `pending.question`,
  resume with `--answer`.

## Where

| Path | Use it for |
|---|---|
| `SKILL.md` | Skill-level contract, design requirements, and verification summary. |
| `README.md` | Fast orientation, examples, and token-efficient reading routes. |
| `scripts/engine.py` | Durable code-first substrate: journal, replay, gates, in-doubt handling. |
| `scripts/workflow.py` | Workflow-spec interpreter: kinds, interpolation, routing, prompt repair. |
| `references/workflow.md` | Full spec authoring reference. Some historical/planned sections are marked. |
| `references/authoring-and-driving.md` | Minimal driver loop for an LM or host process. |
| `references/driving-failures.md` | Exit-code decision tree for failures. |
| `references/journal-format.md` | On-disk journal contract. |
| `references/nested-flows.md` | `ctx.call` and portable `run_flow`/`resume_flow` API. |
| `references/improvement-plan.md` | Roadmap from the Hermes/container authoring review. |
| `evals/author_flow_eval/README.md` | Live eval where Hermes authors specs through `hermes -z` in the container. |
| `tests/TEST-PLAN.md` | Test suite map and quality gates. |

## Token-Efficient LM Activities

Pick one activity and read only those files first.

| Activity | Read | Run |
|---|---|---|
| Drive an existing flow until done | `references/authoring-and-driving.md`, then `references/driving-failures.md` only on non-0/10 exits | `python3 scripts/engine.py run ...`; `python3 scripts/engine.py resume ...` |
| Author a new workflow spec | This README, then `references/workflow.md` sections 1-8 | `python3 scripts/engine.py run --flow <host.py> ...` |
| Debug interpolation/routing | `references/workflow.md` sections on state/interpolation/routing, then `tests/ladder/wf_paths.py` or `wf_router.py` | `python3 tests/run_ladder.py -k wf_paths --evidence` |
| Verify the current skill | `tests/TEST-PLAN.md` | `python3 tests/run.py` |
| Verify Hermes can author specs | `evals/author_flow_eval/README.md` | `evals/.venv/bin/pytest evals/author_flow_eval -v` |
| Continue improving the skill | `references/improvement-plan.md`, then the specific referenced files | Start with the narrow command listed in the plan |
| Restore or remove `agent`/MCP | `SKILL.md` current-gap note, `references/improvement-plan.md`, `evals/author_flow_eval/README.md` | `evals/.venv/bin/pytest evals/author_flow_eval -m L6 -v` |

## Minimal Example

Workflow spec:

```json
{
  "id": "approval",
  "version": 1,
  "start": "prepare",
  "states": {
    "prepare": {"run": "begin"},
    "review": {
      "ask": "Approve ${$.input.customer} for ${$.input.amount} dollars?",
      "options": ["approve", "reject"],
      "routes": {"approve": "@done", "reject": "@fail"}
    }
  }
}
```

Host file:

```python
from workflow import load_workflow

def begin(flowing, state):
    return {"ok": True, "input": flowing}

SPEC = {...}
flow = load_workflow(SPEC, {"begin": begin}, llm=my_llm, router=my_router)
```

Driver loop:

```bash
python3 scripts/engine.py run \
  --flow approval.py \
  --input '{"customer":"ACME-9931","amount":4172}' \
  --state-dir /tmp/approval-run

# If exit 10, show pending.question to the user, then:
python3 scripts/engine.py resume \
  --flow approval.py \
  --state-dir /tmp/approval-run \
  --answer '"approve"'
```

## Worked Offline Examples

```bash
python3 examples/triage.py run --state-dir /tmp/triage \
  --input '{"customer":"acme","topic":"widget","items":[{"name":"A","amount":60}]}'

python3 examples/triage.py resume --state-dir /tmp/triage --answer '"approve"'
```

Also useful:

- `python3 examples/complaint.py` for prompt interruption with `ASK:`.
- `python3 examples/walkthrough.py` for crash -> in-doubt -> resolve -> gate -> replay.
- `python3 examples/walkthrough_nested.py` for nested `ctx.call` and portable state.

## Verification

Default offline gate:

```bash
python3 tests/run.py
```

Fast focused checks:

```bash
python3 tests/run_ladder.py --suite smoke
python3 tests/run_ladder.py -k wf_intervene_multi --evidence
python3 tests/run_call_ladder.py -k rf_2level
```

Live Hermes authoring gate, run from the host checkout with the `hermes` container up:

```bash
python3 -m venv evals/.venv
evals/.venv/bin/pip install pytest
evals/.venv/bin/pytest evals/author_flow_eval -v
```

Expected current live result: L1-L5 pass, wrapper order passes, and L6 skips until the `agent` kind
is restored or the legacy MCP surface is removed.

## Current Gaps

- `agent` + live MCP is documented as historical/planned but is not in the active interpreter
  kind set. See `references/improvement-plan.md`.
- `references/workflow.md` still contains some historical/planned material. Its top note points to
  the executable contract that is authoritative today.
- Live authoring evals are model-dependent. Treat failures as evidence: inspect
  `evals/author_flow_eval/artifacts/<suite>_<id>/attemptN/`.

