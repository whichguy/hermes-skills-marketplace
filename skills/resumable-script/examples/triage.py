#!/usr/bin/env python3
"""Worked example: a refund-triage WORKFLOW exercising `search` + `map`/reduce + `prompt` + `ask`.

The spec lives in triage.workflow.json (portable JSON); this driver supplies the function registry
and the injected `search`/`llm` callers. All hooks are deterministic STUBS so it runs offline — for
real use, swap `stub_search` for a web caller and `stub_llm` for `workflow.llm_json(...)`.

Flow: research (search) -> summarise (map each line item, reduce to a total) -> assess (prompt routes
on the total) -> approve (human gate for >100) -> notify. A total <= 100 completes in one `run`;
a total > 100 SUSPENDS at the approval gate and resumes durably.

  # straight-through (auto): total 90 -> no gate
  python3 examples/triage.py run --state-dir /tmp/tri \
    --input '{"customer":"acme","topic":"widget","items":[{"name":"A","amount":40},{"name":"B","amount":50}]}'

  # large refund (review): total 140 -> suspends at the approval gate, then resume
  python3 examples/triage.py run --state-dir /tmp/tri2 \
    --input '{"customer":"acme","topic":"widget","items":[{"name":"A","amount":60},{"name":"B","amount":80}]}'
  python3 examples/triage.py resume --state-dir /tmp/tri2 --answer '"approve"'
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from engine import run_cli              # noqa: E402
from workflow import load_workflow_file  # noqa: E402


def stub_search(query, fmt):
    # Deterministic offline web caller. Real use: a web-search tool returning {results:[{title,url,snippet}]}.
    return {"query": query, "format": fmt, "results": [
        {"title": "Refund policy", "url": "https://help.example.com/refunds",
         "snippet": "Refunds over $100 need approval."}]}


def stub_llm(convo):
    # Deterministic offline TASK model (v2: replies are one JSON object; routing belongs to the router).
    text = convo[-1]["content"]
    m = re.search(r"total=(\d+)", text)
    total = int(m.group(1)) if m else 0
    decision = "review" if total > 100 else "auto"
    return '{"outcome": "%s", "decision": "%s", "total": %d}' % (decision, decision, total)


def stub_router(convo):
    # The independent judge — FALLBACK only (the task declares its outcome).
    nxt = "review" if '"decision": "review"' in convo[-1]["content"] else "auto"
    return '{"outcome": "%s"}' % nxt


def summarise_item(item, state):
    # inner `map` step: one line item -> a compact summary. `item` is the flowing value; $.it is the same.
    return {"label": item["name"], "amount": item["amount"]}


def tally(outs, state):
    # `reduce`: fold the per-item summaries into a total.
    return {"labels": [o["label"] for o in outs],
            "total": sum(o["amount"] for o in outs), "count": len(outs)}


def draft_notice(flowing, state):
    return {"notice": "Refund for %s processed (%s)."
            % (state["input"]["customer"], state["assess"]["decision"]),
            "total": state["summarise"]["total"]}    # $.assess = the task's parsed JSON reply


REGISTRY = {"summarise_item": summarise_item, "tally": tally, "draft_notice": draft_notice}
SPEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "triage.workflow.json")
triage = load_workflow_file(SPEC_PATH, REGISTRY, llm=stub_llm, search=stub_search, router=stub_router)


if __name__ == "__main__":
    sys.exit(run_cli(triage))
