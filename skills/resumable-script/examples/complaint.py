#!/usr/bin/env python3
"""The canonical multi-step v2 example: a customer-complaint workflow (see references/workflow.md §1).

The spec lives in complaint.workflow.json; this driver supplies deterministic STUB callers so both
canonical traces run offline (swap them for `workflow.llm_json` / a real router in production):

  # trace A — clean run: classify -> research -> assess (task + router) -> draft -> send -> @done
  python3 examples/complaint.py run --state-dir /tmp/cmp-a \
    --input '{"text":"My blender arrived cracked, ordered 5 days ago, order #4417"}'

  # trace B — the interrupt: a vague complaint makes the assess TASK reply with an ASK: line ->
  # exit 10; the answer is woven into the task convo, the task re-attempts, the router routes.
  python3 examples/complaint.py run    --state-dir /tmp/cmp-b --input '{"text":"my thing broke, want money back"}'
  python3 examples/complaint.py resume --state-dir /tmp/cmp-b --answer '"Blender, order #4417, last Tuesday"'
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from engine import run_cli                 # noqa: E402
from workflow import load_workflow_file    # noqa: E402


def stub_llm(convo):
    # Deterministic offline TASK model. Each branch answers ONE directive (v2: one JSON object out;
    # the vague-complaint branch demonstrates the ASK: interrupt convention).
    text = convo[-1]["content"]
    if text.startswith("Classify"):
        return '{"category": "damaged_goods", "severity": 2}'
    if text.startswith("Our policy areas"):
        return '{"result": "- Damaged on arrival: full refund within 30 days\\n- Replacements after 30 days\\n- Apologies otherwise"}'
    if text.startswith("Complaint:"):
        vague = "my thing broke" in text and not any(
            "The human answered:" in (m.get("content") or "") for m in convo)
        if vague:
            return "ASK: Which product is this, what is the order number, and when did it arrive?"
        return ('{"outcome": "give_refund", "recommend": "full refund", "evidence": "damaged on arrival, within the 30-day window"}')
    return '{"email": "Dear customer, your refund has been processed. Sorry for the trouble."}'


def stub_router(convo):
    # The independent judge — FALLBACK only (the task declares its outcome; this fires only when
    # a reply lacks a valid "outcome" after repair).
    return '{"outcome": "give_refund"}'


def send_email(flowing, state):
    return {"sent": True, "body": (state.get("draft") or {}).get("email")}


SPEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "complaint.workflow.json")
complaint = load_workflow_file(SPEC_PATH, {"send_email": send_email},
                               llm=stub_llm, router=stub_router)


if __name__ == "__main__":
    sys.exit(run_cli(complaint))
