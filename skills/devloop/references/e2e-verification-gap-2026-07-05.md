# E2E Verification Gap — 2026-07-05

## What happened

Devloop produced a `calendar-quick-add` skill that passed all 4 unit tests
(4/4 criteria green, judges trusted, evidence passing) but failed when run
against the real `gws` binary.

## The bug

The implementation used `gws calendar events create --title ... --start ... --end ... --attendees a@b.com`
but the actual gws CLI uses `gws calendar +insert --summary ... --start ... --end ... --attendee a@b.com`.

Four specific format errors:
1. **Wrong subcommand:** `events create` → `+insert` (helper)
2. **Wrong flag:** `--title` → `--summary`
3. **Wrong attendee format:** `--attendees comma,separated` → `--attendee` (repeatable per email)
4. **Missing reminder support:** `+insert` doesn't support `--reminder` at all

## Why unit tests didn't catch it

The unit tests mocked `gws_runner` and asserted:
```python
assert 'lunch' in call_str
assert '2026-07-06' in call_str
```

These pass regardless of whether the gws command format is correct — they only
check that the title and date appear *somewhere* in the string.

## What would have caught it

An integration-tier criterion that runs the real binary:
```python
def test_c5_gws_command_format():
    import subprocess, json
    result = subprocess.run(
        ['gws', 'calendar', '+insert', '--dry-run',
         '--summary', 'test', '--start', '2026-07-06T12:00:00',
         '--end', '2026-07-06T13:00:00', '--calendar', 'primary'],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    body = json.loads(result.stdout)['body']
    assert body['summary'] == 'test'
    assert body['start']['dateTime'] == '2026-07-06T12:00:00'
```

## The fix

Three changes to the implementation:
1. `gws calendar events create` → `gws calendar +insert`
2. `--title` → `--summary`
3. `--attendees comma,separated` → `--attendee` (repeatable per email)
4. Dropped `--reminder` flag (not supported by `+insert`)

## Lesson

When the deliverable calls an external CLI (gws, gh, aws, etc.), the charter
MUST include at least one integration-tier criterion that runs the real binary
with `--dry-run` (or equivalent) and verifies the API call shape. Unit tests
with mocked runners cannot catch command-format bugs.
