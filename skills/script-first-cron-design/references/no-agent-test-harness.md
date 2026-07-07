# No-Agent Cron Script Test Harness

## Problem

`no_agent` cron scripts are hard to test because they read/write real files
(MEMORY.md, state JSON, skills directory). Running them against live data
corrupts the baseline — state files advance, entries get removed, and the
next real cron tick sees stale data as "new."

## Solution

A sandbox test harness that:

1. Creates a temp directory
2. Symlinks the real skills directory (read-only, no copy needed)
3. Copies the target file (MEMORY.md, state JSON) into the sandbox
4. Sets `HERMES_HOME` to the sandbox
5. Runs the script
6. Verifies output and side effects
7. Cleans up

## Template

```python
#!/usr/bin/env python3
"""Test harness for <script_name>.py — runs in sandbox, never touches real data."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL_HOME = Path("/opt/data")
SCRIPT = REAL_HOME / "scripts" / "<script_name>.py"


def setup_sandbox():
    """Create sandbox with symlinked skills and copied target files."""
    sandbox = Path(tempfile.mkdtemp(prefix="test_<name>_"))
    (sandbox / "skills").symlink_to(REAL_HOME / "skills")
    (sandbox / "cron").mkdir(parents=True, exist_ok=True)
    (sandbox / "cron" / "state").mkdir(exist_ok=True)

    # Copy target files (not symlinks — the script will write to them)
    for f in ["MEMORY.md", "USER.md"]:
        src = REAL_HOME / f
        if src.exists():
            shutil.copy2(src, sandbox / f)

    return sandbox


def run_script(sandbox: Path) -> subprocess.CompletedProcess:
    """Run the script in the sandbox."""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(sandbox)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, timeout=30,
        env=env,
    )


def verify(sandbox: Path, result: subprocess.CompletedProcess):
    """Verify the script's output and side effects."""
    # Check exit code
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Check target file was modified
    target = sandbox / "MEMORY.md"
    assert target.exists(), "MEMORY.md not found after run"

    # Check expected changes
    content = target.read_text()
    # ... specific assertions ...

    print("✅ All checks passed")


def main():
    sandbox = setup_sandbox()
    try:
        result = run_script(sandbox)
        verify(sandbox, result)
    finally:
        shutil.rmtree(sandbox)


if __name__ == "__main__":
    main()
```

## Key Design Decisions

- **Symlink skills, copy data** — skills are read-only (symlink is safe), but
  data files are mutated (must copy). Symlinking MEMORY.md would cause the
  test to write to the real file.
- **`HERMES_HOME` override** — the script uses `HERMES_HOME` for all paths,
  so setting it to the sandbox isolates everything.
- **Cleanup in `finally`** — always remove the temp dir, even on assertion failure.
- **No mocking** — the test runs the real script against real (copied) data.
  This catches real bugs that mocks would hide.

## When to Use

- Any `no_agent` script that mutates files
- Any precheck script with state files
- Before deploying a script change to cron
- After fixing a bug — add a regression test case

## Pitfalls

- **Don't run against live data** — even once. The memory pressure watchdog test
  accidentally ran against real MEMORY.md and removed entries. Always use a sandbox.
- **`write_file` tool may silently fail** — the test file kept disappearing when
  written with `write_file`. Use `mcp_hermes_home_write_file` as a fallback.
- **Symlinks don't work for mutated files** — if the script writes to a file in
  the skills directory, symlinking will corrupt the real skill. Copy instead.
- **Large skills directories** — symlinking is fast (no copy), but if the script
  walks the skills tree, it will see all real skills. This is usually desired
  (test against real data) but can be slow.

## Real Example

`test_memory_pressure_watch.py` tests the memory pressure watchdog with 3 cases:
1. Entry with matching skill → auto-offloaded
2. Entry without matching skill → kept
3. Entry below threshold → no action

Each case uses a sandbox with a crafted MEMORY.md and the real skills directory.
The test was created after Jim asked "Is there a way to plan to test this to
make sure it works with a simple case" — the answer was yes, and the pattern
is now reusable.
