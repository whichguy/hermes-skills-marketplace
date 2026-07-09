"""Shared fixtures for the E2E suite.

Each E2E scenario is a self-contained test that runs one full devloop cycle
against a real model. Scenarios are designed to be:
- Small (one task, one devloop run, ~2-5 min each)
- Independent (no shared state between scenarios)
- Diverse (different task types: simple functions, multi-file, classes, etc.)
- Self-verifying (independent corroboration of the produced code)

All scenarios require DEVLOOP_RUN_REAL=1 to run (double-gated, same as the
original test_e2e_real.py). The quarantine gate (DEVLOOP_RUN_MULTIFILE=1)
is per-scenario via the `quarantined` marker.
"""
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _DIR)

import dispatch   # noqa: E402
import runner     # noqa: E402


def _enabled():
    """Double-gate: DEVLOOP_RUN_REAL=1 AND hermes binary exists."""
    return os.environ.get("DEVLOOP_RUN_REAL") == "1" and os.path.exists(dispatch.HERMES_BIN)


def _e2e_dir(name):
    """Create a fresh E2E directory under .devloop/e2e/<name>."""
    d = os.path.join(_DIR, ".devloop", "e2e", name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def _git_repo(root, name="repo"):
    """Create a git repo at <root>/<name> with an initial commit. Returns the repo path."""
    repo = os.path.join(root, name)
    os.makedirs(repo)
    for a in (["init", "-q"], ["config", "user.email", "x@y.z"], ["config", "user.name", "x"]):
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    open(os.path.join(repo, "README"), "w").write("repo\n")
    subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True, capture_output=True)
    return repo


def _import_fresh(path, modname):
    """Import a module from a file path, returning the module object."""
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_produced_file(worktree_path):
    """Find the .py file produced by the devloop coder in a worktree.

    The coder may name the output file differently than the prompt requested
    (e.g. prompt says 'strings.py' but coder creates 'reverse.py'). This
    discovers the actual file by checking the devloop result metadata first,
    then falling back to scanning for non-test .py files.
    """
    # Try .devloop/result.json first — it records changed file paths
    result_path = os.path.join(worktree_path, ".devloop", "result.json")
    if os.path.exists(result_path):
        import json
        with open(result_path) as f:
            result = json.load(f)
        changed = result.get("changed_files", [])
        py_files = [f for f in changed if f.endswith(".py")]
        if len(py_files) == 1:
            p = os.path.join(worktree_path, py_files[0])
            if os.path.exists(p):
                return p

    # Fallback: scan for .py files that aren't tests or scaffolding
    candidates = []
    for f in os.listdir(worktree_path):
        if not f.endswith(".py"):
            continue
        if f.startswith("test_") or f == "conftest.py":
            continue
        candidates.append(os.path.join(worktree_path, f))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Prefer the largest non-test .py file (most likely the implementation)
        candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
        return candidates[0]

    raise FileNotFoundError(
        f"No produced .py file found in worktree {worktree_path}. "
        f"Contents: {os.listdir(worktree_path)}"
    )


def _run_devloop(repo, request, root, name="run"):
    """Run one devloop cycle. Returns the result dict + worktree path."""
    out = runner.run_task(repo, request, os.path.join(root, "wts"), name)
    return out


def skip_if_not_enabled():
    """Skip the test if DEVLOOP_RUN_REAL is not set."""
    if not _enabled():
        pytest.skip("set DEVLOOP_RUN_REAL=1 to run E2E tests")


def skip_if_quarantined(marker_name=""):
    """Skip if the scenario is quarantined and the unlock env var is not set."""
    if not marker_name:
        return
    env_var = f"DEVLOOP_RUN_{marker_name.upper()}"
    if os.environ.get(env_var) != "1":
        pytest.skip(f"QUARANTINED — set {env_var}=1 to run")