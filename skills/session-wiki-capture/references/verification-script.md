# Post-Capture Verification Script

After a session-to-wiki capture run, use this verification pattern to confirm
all changes are consistent. The script checks:

1. Frontmatter on all changed wiki pages
2. No broken wikilinks in changed files
3. Index page count matches actual wikilink count
4. Content-specific checks (bug fix sections, test counts, dates)

## Template

```python
#!/usr/bin/env python3
"""Ad-hoc verification: wiki page integrity for changed files."""
import re, os, sys

WIKI = "/opt/data/wiki"
CHANGED = [
    "concepts/page-one.md",
    "concepts/page-two.md",
    "index.md",
]
errors = []

# Collect all wiki page slugs
all_slugs = set()
for root, dirs, files in os.walk(WIKI):
    for f in files:
        if f.endswith(".md"):
            all_slugs.add(f[:-3])

# 1. Frontmatter check
for fname in CHANGED:
    fpath = os.path.join(WIKI, fname)
    if not os.path.exists(fpath):
        errors.append(f"Missing: {fpath}")
        continue
    with open(fpath) as f:
        content = f.read()
    if fname == "index.md":
        continue  # index.md doesn't need frontmatter
    if not content.startswith("---\n"):
        errors.append(f"{fname}: no frontmatter")
        continue
    fm = content.split("---\n", 2)[1] if len(content.split("---\n", 2)) >= 3 else ""
    for field in ["title:", "created:", "updated:", "type:", "tags:", "sources:"]:
        if field not in fm:
            errors.append(f"{fname}: missing {field}")

# 2. Broken wikilinks
for fname in CHANGED:
    fpath = os.path.join(WIKI, fname)
    if not os.path.exists(fpath):
        continue
    with open(fpath) as f:
        content = f.read()
    links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)
    broken = [l.strip() for l in links if l.strip() not in all_slugs and l.strip() != "SCHEMA"]
    if broken:
        errors.append(f"{fname}: broken: {broken}")

# 3. Index count match
with open(os.path.join(WIKI, "index.md")) as f:
    idx = f.read()
m = re.search(r'Curated pages:\s*(\d+)', idx)
actual = len(re.findall(r'^- \[\[', idx, re.MULTILINE))
declared = int(m.group(1)) if m else -1
if declared != actual:
    errors.append(f"Count mismatch: {declared} vs {actual}")

# 4. Content-specific checks (customize per session)
# Example: check a bug fix section exists
# with open(os.path.join(WIKI, "concepts/some-page.md")) as f:
#     content = f.read()
# if "EXPECTED_TEXT" not in content:
#     errors.append("Missing expected content")

if errors:
    print(f"FAILED: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("AD-HOC VERIFICATION PASSED")
    sys.exit(0)
```

## Usage

Write to a temp file, run, and clean up:

```bash
TMPFILE=$(mktemp /tmp/hermes-verify-XXXXXX.py)
# ... write script to $TMPFILE ...
python3 "$TMPFILE"
rm -f "$TMPFILE"
```

## When to Use

- After any session-to-wiki capture that modified wiki pages
- After fixing Slack-created pages (frontmatter, broken links, index entries)
- Before committing wiki changes to git
- As a pre-commit hook for wiki edits
