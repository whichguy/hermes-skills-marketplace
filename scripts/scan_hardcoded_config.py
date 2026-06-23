#!/usr/bin/env python3
"""
Scan SKILL.md files for instructions that should be config declarations.
"""

import sys
import re
from pathlib import Path


PROSE_CONFIG_INDICATORS = [
    (r'replace\s+\w+\s+with\s+your\s+', "replace placeholder instruction (should be config)"),
    (r'change\s+the\s+\w+\s+to\s+\d+', "change numeric value instruction (should be config)"),
    (r'set\s+\w+\s+to\s+["\']\w+["\']', "set string value instruction (should be config)"),
    (r'edit\s+this\s+to\s+match\s+your', "edit-to-match instruction (should be config)"),
    (r'update\s+the\s+following\s+values', "update values instruction (should be config)"),
    (r'customize\s+these\s+(settings|defaults|values)', "customize instruction (should be config)"),
]


def main():
    repo_root = Path(__file__).parent.parent
    issues = []

    for base in ["skills", "community"]:
        base_path = repo_root / base
        if not base_path.exists():
            continue

        for skill_md in base_path.rglob("SKILL.md"):
            content = skill_md.read_text()
            rel = skill_md.relative_to(repo_root)

            # Skip code blocks (``` ... ```) — those are examples, not instructions
            prose_content = re.sub(r'```[\s\S]*?```', '', content)

            for pattern, desc in PROSE_CONFIG_INDICATORS:
                for match in re.finditer(pattern, prose_content, re.IGNORECASE):
                    line_num = content[:match.start()].count('\n') + 1
                    issues.append(f"{rel}:{line_num}: {desc}")

    if issues:
        print(f"\n❌ Hardcoded config in prose ({len(issues)} issue(s)):\n")
        for issue in issues:
            print(f"  • {issue}")
        sys.exit(1)
    else:
        print("✅ No hardcoded config instructions in SKILL.md prose")
        sys.exit(0)


if __name__ == "__main__":
    main()