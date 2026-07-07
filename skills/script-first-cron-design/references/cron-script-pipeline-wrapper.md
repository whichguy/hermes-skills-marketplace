# Cron Script Pipeline Wrapper Pattern

When a cron job's `script` field contains a full shell pipeline (e.g. `cd /opt/data && python3 /path/to/script.py "arg" --json 2>&1 | grep -v "banner"`), the cron runner prepends its scripts directory to the entire string, producing a nonexistent path. The fix is to create a wrapper script that calls the real script via `subprocess.run()`.

## Wrapper Template

```python
#!/usr/bin/env python3
"""Wrapper for <real_script> — called by cron job <job_name>.

The cron runner resolves script fields relative to its scripts directory,
so the script field must be a bare filename. This wrapper calls the real
script via subprocess with timeout and output parsing.
"""
import subprocess
import sys
import json
import os

REAL_SCRIPT = "/opt/data/path/to/real_script.py"
TIMEOUT = 15  # seconds — must fit under cron.script_timeout_seconds


def main():
    try:
        result = subprocess.run(
            [sys.executable, REAL_SCRIPT, "--json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=os.path.dirname(REAL_SCRIPT),
        )
        if result.returncode != 0:
            print(f"script failed: exit={result.returncode}", file=sys.stderr)
            sys.exit(1)

        # Parse and validate output
        output = result.stdout.strip()
        if not output:
            return  # silent — nothing to report

        # If the real script outputs JSON, parse it
        try:
            data = json.loads(output)
            # Format for delivery
            print(f"result: {data.get('category', 'unknown')} {data.get('label', '')}")
        except json.JSONDecodeError:
            # Pass through raw output
            print(output)

    except subprocess.TimeoutExpired:
        print(f"script timed out after {TIMEOUT}s", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"script not found: {REAL_SCRIPT}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

## Key Design Decisions

1. **Use `sys.executable`** — ensures the same Python interpreter runs the subprocess (important when the cron environment may differ from the interactive environment).
2. **Set `cwd`** — if the real script uses relative paths or `__file__`-based resolution, set the working directory to the script's directory.
3. **Timeout** — always set a subprocess timeout. The sum of all internal timeouts must fit under `cron.script_timeout_seconds` (default 120s).
4. **Output parsing** — if the real script outputs JSON, parse and format it for human-readable delivery. If it outputs plain text, pass through.
5. **Silent on empty** — if the real script produces no output, the wrapper should also produce no output (cron delivers stdout verbatim in `no_agent` mode).

## When to Use

- The real script needs arguments, environment setup, or output filtering that can't be expressed as a bare filename
- The real script lives outside the cron scripts directory (e.g. in a skill directory)
- The real script's output needs post-processing before delivery

## When NOT to Use

- The real script is already a standalone file in the scripts directory — just use the bare filename
- The real script can be moved/copied into the scripts directory and run directly
- The pipeline is simple enough to inline into a single `subprocess.run()` call in the wrapper

## Shell Script Wrapper Variant

When the real script needs environment variables set (e.g. `PYTHONPATH`) or the wrapper itself is simpler as a shell script, use a `.sh` wrapper instead of Python:

```bash
#!/bin/bash
# Wrapper for reply_listener.py — called by cron job WhatsApp Approval Reply Listener.
# Sets PYTHONPATH so the script can import from skill directories.
set -euo pipefail

export PYTHONPATH="/opt/data/skills/productivity/google-workspace/scripts:/opt/data/skills/productivity/approval-workflow-engine/scripts"
exec python3 /opt/data/skills/productivity/sheets-approval-whatsapp/scripts/reply_listener.py \
  --sheet "1uWFQiz9Wrxh3ldpsPDgvQsfwERAWLn1RboWWBI5rw34" \
  --account personal \
  --tab "_MessageLog" \
  "$@"
```

**Key design decisions for shell wrappers:**
1. **`set -euo pipefail`** — exit on error, undefined variable, or pipe failure. Essential for cron — without it, a failed `cd` or `export` is silently ignored.
2. **`exec python3`** — replaces the shell process with Python, so the cron runner sees the Python exit code directly. Without `exec`, the shell exits 0 even if Python fails.
3. **`"$@"`** — passes through any additional arguments from the cron runner.
4. **`chmod +x`** — the wrapper must be executable. The cron runner executes scripts directly, not via `bash <script>`.
5. **Absolute paths** — use absolute paths for both the script and any `PYTHONPATH` entries. The cron runner's working directory is not guaranteed.

**When to use shell vs Python wrapper:**
- **Shell**: when the real script needs env vars set, or the wrapper is just a few lines of setup + exec
- **Python**: when the real script's output needs parsing/validation, or when you need subprocess timeout handling

## Real Example: triage_warmup.py

```python
#!/usr/bin/env python3
"""Cron wrapper: warm up the triage classifier model.

Called every 5 minutes by the triage-model-warmup cron job.
Calls the triage classifier via subprocess with a 15s timeout.
Silent on success (model loaded, classification returned).
"""
import subprocess
import sys
import json

TRIAGE_SCRIPT = "/opt/data/skills/productivity/triage/scripts/triage.py"
TIMEOUT = 15


def main():
    try:
        result = subprocess.run(
            [sys.executable, TRIAGE_SCRIPT, "hello", "--json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if result.returncode != 0:
            sys.exit(1)

        output = result.stdout.strip()
        if not output:
            return

        data = json.loads(output)
        category = data.get("category", "unknown")
        model = data.get("model", "unknown")
        elapsed = data.get("elapsed", "?")
        print(f"triage warmup: {category} {elapsed}s {model}")

    except subprocess.TimeoutExpired:
        sys.exit(1)
    except (json.JSONDecodeError, KeyError):
        sys.exit(1)


if __name__ == "__main__":
    main()
```
