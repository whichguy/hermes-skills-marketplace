#!/usr/bin/env python3
"""Worked example: provision a DB, pause to confirm public exposure, resume.

  python3 examples/provision_db.py run    --state-dir /tmp/x --input '{"hint":"us"}'
  python3 examples/provision_db.py resume --state-dir /tmp/x --answer true
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from engine import flow, run_cli  # noqa: E402


def choose_region(hint):
    return {"us": "us-east-1", "eu": "eu-west-1"}.get(hint, "us-east-1")


def create_db(region, idem):
    # `idem` (= "<run_id>:create-db") would be forwarded to the cloud API so it
    # dedupes if this step is re-run after a crash. Here we just fabricate an id.
    return {"id": "db-" + idem.split(":")[-1][:6], "region": region}


def open_firewall(db_id, idem):
    return {"opened": True, "db": db_id}


@flow(id="provision-db", version=1)
def provision_db(ctx, inp):
    region = ctx.step("pick-region", lambda: choose_region((inp or {}).get("hint", "us")))
    db = ctx.step("create-db", lambda idem: create_db(region, idem), idempotent=False)
    public = ctx.ask("make-public",
                     {"prompt": "DB %s is up. Make it public?" % db["id"], "type": "boolean"})
    if public:
        ctx.step("open-fw", lambda idem: open_firewall(db["id"], idem), idempotent=False)
    return {"db_id": db["id"], "region": region, "public": public}


if __name__ == "__main__":
    sys.exit(run_cli(provision_db))
