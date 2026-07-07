# GitHub Release Polling Pattern

`no_agent` cron script that polls a GitHub repo's releases API, compares the
latest tag to a known baseline, and stays **completely silent** until a new
release drops. Zero tokens on the healthy path.

## When to use

- Monitoring a specific repo for the next release (e.g. waiting for a bugfix to ship)
- Watching for new versions of a tool you depend on
- Any "tell me when X ships" request that should be fire-and-forget

## Script contract

- **Silent (exit 0, empty stdout):** latest release == known tag. Nothing delivered.
- **Loud (exit 0, non-empty stdout):** new tag detected. Stdout is the user message.
- **Error (non-zero exit):** scheduler sends error alert. Script should catch
  transient HTTP errors internally and exit 0 silently — don't spam the user
  on a temporary GitHub API blip.

## Template

```python
#!/usr/bin/env python3
"""Poll GitHub releases for <REPO>. Silent until a new tag appears.

Schedule: daily at <time>
Silence: latest tag == LAST_KNOWN_TAG → exit 0, no output
Alert: new tag detected → print notification with version, link, fix detection
"""

import json
import sys
import urllib.request

REPO = "owner/repo"
LAST_KNOWN_TAG = "v1.0.0"  # update when a new release ships
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

def main():
    try:
        req = urllib.request.Request(API_URL, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hermes-cron-release-watch",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception:
        # Silent on transient errors — don't spam the user
        sys.exit(0)

    latest_tag = data.get("tag_name", "")
    if not latest_tag or latest_tag == LAST_KNOWN_TAG:
        sys.exit(0)  # silent — same release

    # New release! Build the notification
    release_name = data.get("name", "")
    release_url = data.get("html_url", "")
    published_at = data.get("published_at", "")
    body = data.get("body", "")

    print(f"🚀 **New {REPO} release: {release_name} ({latest_tag})**")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Published: {published_at}")
    print(f"Link: {release_url}")
    print()
    # Optional: check for specific fixes
    if "FIX_KEYWORD" in body:
        print("✅ Fix appears to be included")
    else:
        print("⚠️ Fix — check release notes to confirm")

if __name__ == "__main__":
    main()
```

## Cron job shape

```text
script: my_release_watch.py
no_agent: true
schedule: 0 11 * * *       # daily, off-peak
deliver: telegram            # or origin
```

## Key design decisions

- **No state file needed.** The comparison is against a hardcoded `LAST_KNOWN_TAG`
  constant. When a new release ships and you update the constant, the watcher
  goes silent again. Simpler than maintaining a state file for a single value.
- **Transient errors are silent.** Network blips, rate limits, GitHub downtime —
  all caught and suppressed. The next tick will retry. Only persistent failures
  (script crash, non-zero exit) trigger the scheduler's error channel.
- **Fix detection is optional.** The `body` scan for keywords is a nice-to-have.
  Remove it if you just want "new release exists" notification.
- **No LLM tokens.** Pure `no_agent` — the script IS the message.

## Pitfalls

- **`LAST_KNOWN_TAG` must be updated manually** after a release ships, or the
  watcher will fire on every tick. This is by design — the watcher is for
  "tell me when the NEXT release drops," not ongoing version tracking.
- **GitHub API rate limit:** unauthenticated requests get 60/hour. Daily cron
  is fine. Sub-hourly needs a token (`Authorization: Bearer *** header).
- **Pre-release tags:** the `/releases/latest` endpoint returns the latest
  **full** release, not pre-releases. If you need to watch for pre-releases,
  use `/releases` and filter by `prerelease: true`.
