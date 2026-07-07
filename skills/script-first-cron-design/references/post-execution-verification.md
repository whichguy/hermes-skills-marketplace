# Post-Execution Verification Pattern

## Problem

A `no_agent` cron script writes a file (MEMORY.md, state JSON, config) and exits 0.
The scheduler delivers empty stdout → silent success. But the write could have been
partial, corrupted, or silently failed. The user has no way to know.

## Solution

After every write operation, **re-read the file and verify**:

1. File parses correctly (JSON, YAML, etc.)
2. Expected changes are present (removed entries gone, new entries present)
3. Entry count matches expectations
4. No corruption (truncation, encoding issues)

If verification fails, print the error to stdout so the scheduler delivers it.

## Implementation (Python)

```python
def verify_write(path: Path, expected_removals: list[str], expected_keeps: list[str]) -> bool:
    """Re-read the written file and verify correctness."""
    if not path.exists():
        print(f"❌ Verification failed: {path} does not exist after write")
        return False

    content = path.read_text()

    # Check removals are actually gone
    for entry in expected_removals:
        if entry in content:
            print(f"❌ Verification failed: entry still present after removal: {entry[:60]}...")
            return False

    # Check kept entries are still there
    for entry in expected_keeps:
        if entry not in content:
            print(f"❌ Verification failed: entry missing after write: {entry[:60]}...")
            return False

    # Check file parses (for structured formats)
    if path.suffix == '.json':
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            print(f"❌ Verification failed: {path} is not valid JSON: {e}")
            return False

    return True
```

## When to Use

- Any `no_agent` script that mutates a file (MEMORY.md, state JSON, config)
- Any precheck script that writes handoff/seen state files
- Any script where a silent write failure would go undetected

## Pitfalls

- **Don't verify against in-memory state** — re-read from disk. In-memory state may
  differ from what was actually written (encoding issues, partial writes, filesystem
  buffering).
- **Verification failure should print to stdout** — not stderr. In `no_agent` mode,
  stdout is delivered to the user; stderr is invisible.
- **Don't skip verification for "simple" writes** — the memory pressure watchdog
  wrote a simple text file and the first test run silently removed entries without
  the user knowing. Simple writes fail too.

## Real Example

The memory pressure watchdog (`memory_pressure_watch.py`) was updated to add
post-execution verification after Jim asked "did you finish?" — the script had
run but there was no proof it worked correctly. The verification step now:

1. Re-reads MEMORY.md from disk
2. Confirms each removed entry is actually gone
3. Confirms each kept entry is still present
4. Prints a verification summary: `✅ Verified: 11 entries removed, 5 kept`
5. On failure, prints specific errors so the user knows what went wrong
