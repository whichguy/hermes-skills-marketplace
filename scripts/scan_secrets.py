#!/usr/bin/env python3
"""
Scan all Python scripts in the marketplace for hardcoded secrets.
"""

import sys
import re
from pathlib import Path


SECRET_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key"),
    (r'ghp_[a-zA-Z0-9]{36,}', "GitHub personal access token"),
    (r'gho_[a-zA-Z0-9]{36,}', "GitHub OAuth token"),
    (r'AIza[a-zA-Z0-9_-]{35}', "Google API key"),
    (r'xox[baprs]-[a-zA-Z0-9-]+', "Slack token"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key"),
    (r'-----BEGIN (RSA |EC )?PRIVATE KEY-----', "Private key block"),
]

# Placeholder patterns that look like secrets but aren't — skip these
PLACEHOLDER_PATTERNS = [
    r'\.\.\.',            # contains "..." (e.g. "COMFY_..._KEY")
    r'^\*+$',             # all asterisks (e.g. "***")
    r'YOUR[_-]',          # YOUR_API_KEY
    r'<[^>]+>',           # <api_key>
    r'EXAMPLE',           # EXAMPLE_KEY
    r'PLACEHOLDER',       # PLACEHOLDER
    r'XXXX',              # XXXX
    r'api_key=api_key',   # variable self-reference (not a literal)
]


def main():
    repo_root = Path(__file__).parent.parent
    issues = []

    for base in ["skills", "community", "skill-template"]:
        base_path = repo_root / base
        if not base_path.exists():
            continue

        for py_file in base_path.rglob("*.py"):
            content = py_file.read_text()
            rel = py_file.relative_to(repo_root)

            for pattern, desc in SECRET_PATTERNS:
                for match in re.finditer(pattern, content):
                    line_num = content[:match.start()].count('\n') + 1
                    issues.append(f"{rel}:{line_num}: {desc} detected")

    if issues:
        print(f"\n❌ Secret scan failed ({len(issues)} issue(s)):\n")
        for issue in issues:
            print(f"  • {issue}")
        sys.exit(1)
    else:
        print("✅ No hardcoded secrets detected")
        sys.exit(0)


if __name__ == "__main__":
    main()