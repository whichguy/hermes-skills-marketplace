"""E2E: non-Python artifact — JSON config.

Task: Create config.json with a structured configuration object. Tests that the
loop can produce a non-Python file and that devloop's JSON linter runs end-to-end.
"""
import json

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _run_devloop,
)


def test_json_config():
    """Non-Python E2E scenario — validates JSON output + the json.tool linter path."""
    skip_if_not_enabled()
    root = _e2e_dir("json_config")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create config.json. The top-level object must have exactly three keys: "
        "\"server\" (an object with string \"host\" and integer \"port\"), "
        "\"debug\" (a boolean), and \"features\" (a list of strings).",
        root, "jsonrun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"json config task should COMPLETE: {res['terminal']}"
    config_path = out["worktree"]["path"] + "/config.json"
    with open(config_path) as f:
        cfg = json.load(f)
    assert isinstance(cfg, dict), "config.json must be a JSON object"
    assert sorted(cfg.keys()) == ["debug", "features", "server"], cfg.keys()
    assert isinstance(cfg["server"], dict)
    assert isinstance(cfg["server"]["host"], str)
    assert isinstance(cfg["server"]["port"], int)
    assert isinstance(cfg["debug"], bool)
    assert isinstance(cfg["features"], list)
    assert all(isinstance(x, str) for x in cfg["features"])
    print(f"E2E OK: json_config — COMPLETE, keys={sorted(cfg.keys())}")