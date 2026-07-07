import os
import subprocess
import tempfile
import json
import shutil
import sys

ROOT = "/opt/data/skills/resumable-script"
SCRIPTS = os.path.join(ROOT, "scripts")
ENGINE = os.path.join(SCRIPTS, "engine.py")

FLOW_SRC = """
from workflow import load_workflow
import os

SPEC = {
    "id": "fuzz_map", "version": 1, "start": "fan",
    "states": {
        "fan": {"map": {"over": "$.input.items", "as": "it", "do": {"run": "work"}, 
                        "on_item_error": os.environ.get("MODE", "fail"),
                        "retries": int(os.environ.get("RETRIES", "0"))},
                "reduce": {"run": "join"}, "next": "@done"},
    }
}

def work(item, state):
    idx = state["it_index"]
    if os.environ.get("FAIL_IDX") == str(idx):
        raise RuntimeError("injected failure")
    return {"val": item, "idx": idx}

def join(outs, state):
    return {"count": len(outs), "items": outs}

flow = load_workflow(SPEC, {"work": work, "join": join})
"""

def run_fuzz():
    with tempfile.TemporaryDirectory() as td:
        flow_path = os.path.join(td, "flow.py")
        with open(flow_path, "w") as f:
            f.write(FLOW_SRC)
        
        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS
        
        # 1. Huge list (1000 items)
        print("Testing huge list (1000 items)...")
        input_data = {"items": [{"x": i} for i in range(1000)]}
        res = subprocess.run([
            sys.executable, ENGINE, "run", 
            "--flow", flow_path,
            "--input", json.dumps(input_data),
            "--state-dir", os.path.join(td, "huge")
        ], capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Huge list failed: {res.stderr}")
            return 1
        out = json.loads(res.stdout.splitlines()[-1])
        if out["result"]["result"]["count"] != 1000:
            print(f"Huge list count mismatch: {out['result']['result']['count']}")
            return 1
        print("  PASS huge list")

        # 2. Empty list
        print("Testing empty list...")
        input_data = {"items": []}
        res = subprocess.run([
            sys.executable, ENGINE, "run", 
            "--flow", flow_path,
            "--input", json.dumps(input_data),
            "--state-dir", os.path.join(td, "empty")
        ], capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Empty list failed: {res.stderr}")
            return 1
        out = json.loads(res.stdout.splitlines()[-1])
        if out["result"]["result"]["count"] != 0:
            print(f"Empty list count mismatch: {out['result']['result']['count']}")
            return 1
        print("  PASS empty list")

        # 3. on_item_error: fail
        print("Testing on_item_error='fail'...")
        input_data = {"items": [1, 2, 3]}
        env["MODE"] = "fail"
        env["FAIL_IDX"] = "1"
        res = subprocess.run([
            sys.executable, ENGINE, "run", 
            "--flow", flow_path,
            "--input", json.dumps(input_data),
            "--state-dir", os.path.join(td, "fail_mode")
        ], capture_output=True, text=True, env=env)
        if res.returncode != 1:
            print(f"Fail mode should have returned exit 1, got {res.returncode}")
            return 1
        print("  PASS fail mode")

        # 4. on_item_error: skip
        print("Testing on_item_error='skip'...")
        input_data = {"items": [1, 2, 3]}
        env["MODE"] = "skip"
        env["FAIL_IDX"] = "1"
        res = subprocess.run([
            sys.executable, ENGINE, "run", 
            "--flow", flow_path,
            "--input", json.dumps(input_data),
            "--state-dir", os.path.join(td, "skip_mode")
        ], capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Skip mode failed: {res.stderr}")
            return 1
        out = json.loads(res.stdout.splitlines()[-1])
        if out["result"]["result"]["count"] != 2:
            print(f"Skip mode count mismatch: {out['result']['result']['count']} (expected 2)")
            return 1
        print("  PASS skip mode")

        # 5. on_item_error: collect
        print("Testing on_item_error='collect'...")
        input_data = {"items": [1, 2, 3]}
        env["MODE"] = "collect"
        env["FAIL_IDX"] = "1"
        res = subprocess.run([
            sys.executable, ENGINE, "run", 
            "--flow", flow_path,
            "--input", json.dumps(input_data),
            "--state-dir", os.path.join(td, "collect_mode")
        ], capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Collect mode failed: {res.stderr}")
            return 1
        out = json.loads(res.stdout.splitlines()[-1])
        if out["result"]["result"]["count"] != 3:
            print(f"Collect mode count mismatch: {out['result']['result']['count']} (expected 3)")
            return 1
        items = out["result"]["result"]["items"]
        if "__error__" not in items[1]:
            print(f"Collect mode did not collect error sentinel: {items[1]}")
            return 1
        print("  PASS collect mode")

        # 6. Large items (spill to blob)
        print("Testing large items (spill to blob)...")
        large_val = "x" * 100000
        input_data = {"items": [large_val]}
        res = subprocess.run([
            sys.executable, ENGINE, "run", 
            "--flow", flow_path,
            "--input", json.dumps(input_data),
            "--state-dir", os.path.join(td, "large")
        ], capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Large items failed: {res.stderr}")
            return 1
        
        # Verify blobs directory
        blobs_dir = os.path.join(td, "large", "blobs")
        if not os.path.exists(blobs_dir) or not os.listdir(blobs_dir):
            print("Large items did not spill to blobs")
            return 1
        print("  PASS large items")

    return 0

if __name__ == "__main__":
    sys.exit(run_fuzz())
