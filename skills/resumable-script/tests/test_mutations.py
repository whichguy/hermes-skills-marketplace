import os
import subprocess
import tempfile
import json
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
ENGINE = os.path.join(SCRIPTS, "engine.py")

FLOW_SRC = """
from engine import flow
import os
@flow(id="blob_test")
def main(ctx, inp):
    val = "x" * 2000
    res = ctx.step("big", lambda: val)
    return {"len": len(res)}
"""

def test_blob_corruption():
    print("Testing blob corruption detection...")
    with tempfile.TemporaryDirectory() as td:
        flow_path = os.path.join(td, "flow.py")
        with open(flow_path, "w") as f:
            f.write(FLOW_SRC)

        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS
        env["HERMES_FLOW_BLOB_THRESHOLD"] = "1000"  # Force spill

        # 1. First run - creates blob
        subprocess.run(
            [sys.executable, ENGINE, "run", "--flow", flow_path, "--state-dir", td],
            env=env,
            capture_output=True,
        )

        # 2. Corrupt the blob
        blobs_dir = os.path.join(td, "blobs")
        blob_file = os.path.join(blobs_dir, os.listdir(blobs_dir)[0])
        with open(blob_file, "w") as f:
            f.write('{"corrupted": true}')

        # 3. Second run - should fail with exit 3
        res = subprocess.run(
            [sys.executable, ENGINE, "run", "--flow", flow_path, "--state-dir", td],
            capture_output=True,
            text=True,
            env=env,
        )
        if res.returncode == 3:
            print("  PASS: Blob corruption detected (exit 3)")
        else:
            print(f"  FAIL: Expected exit 3, got {res.returncode}")
            print(res.stderr)
            return 1
    return 0


def test_schema_version():
    print("Testing future schema version rejection...")
    with tempfile.TemporaryDirectory() as td:
        flow_path = os.path.join(td, "flow.py")
        with open(flow_path, "w") as f:
            f.write(FLOW_SRC)

        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS

        # 1. Seed journal with future version
        os.makedirs(td, exist_ok=True)
        jp = os.path.join(td, "journal.jsonl")
        with open(jp, "w") as f:
            f.write(json.dumps({"v": 999, "seq": 0, "type": "run_started",
                                "run_id": "R", "flow_id": "blob_test"}) + "\n")

        # 2. Run - should fail with exit 3
        res = subprocess.run(
            [sys.executable, ENGINE, "run", "--flow", flow_path, "--state-dir", td],
            capture_output=True,
            text=True,
            env=env,
        )
        if res.returncode == 3:
            print("  PASS: Future schema version rejected (exit 3)")
        else:
            print(f"  FAIL: Expected exit 3, got {res.returncode}")
            print(res.stderr)
            return 1
    return 0


def test_torn_tail_recovery():
    print("Testing torn-tail recovery...")
    with tempfile.TemporaryDirectory() as td:
        flow_path = os.path.join(td, "flow.py")
        with open(flow_path, "w") as f:
            f.write(FLOW_SRC)

        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS

        os.makedirs(td, exist_ok=True)
        jp = os.path.join(td, "journal.jsonl")
        with open(jp, "w") as f:
            f.write(json.dumps({"v": 1, "seq": 0, "type": "run_started",
                                "run_id": "R", "flow_id": "blob_test",
                                "engine": "py", "input": None}) + "\n")
            f.write('{"v":1,"seq":1,"type":"step_started","key":"big"')  # Torn

        # 2. Run - should succeed (dropping the torn line and re-running)
        res = subprocess.run(
            [sys.executable, ENGINE, "run", "--flow", flow_path, "--state-dir", td],
            capture_output=True,
            text=True,
            env=env,
        )
        if res.returncode == 0:
            print("  PASS: Torn-tail dropped and flow completed")
        else:
            print(f"  FAIL: Expected exit 0, got {res.returncode}")
            print(res.stderr)
            return 1
    return 0


if __name__ == "__main__":
    rc = 0
    rc |= test_blob_corruption()
    rc |= test_schema_version()
    rc |= test_torn_tail_recovery()
    sys.exit(rc)
