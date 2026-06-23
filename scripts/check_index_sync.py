#!/usr/bin/env python3
"""
Verify that .well-known/skills/index.json is in sync with actual skills
in the repository.
"""

import sys
import os
import re
import json
import yaml
from pathlib import Path


def parse_frontmatter(content: str):
    if not content.startswith("---"):
        return {}
    match = re.search(r'\n---\s*\n', content[3:])
    if not match:
        return {}
    try:
        fm = yaml.safe_load(content[3:match.start() + 3])
        return fm if isinstance(fm, dict) else {}
    except Exception:
        return {}


def main():
    repo_root = Path(__file__).parent.parent
    index_path = repo_root / ".well-known" / "skills" / "index.json"

    if not index_path.exists():
        print("❌ .well-known/skills/index.json not found")
        sys.exit(1)

    with open(index_path) as f:
        index_data = json.load(f)

    indexed_skills = {s["name"] for s in index_data.get("skills", [])}

    # Find all actual skills
    actual_skills = {}
    for base in ["skills", "community", "skill-template"]:
        base_path = repo_root / base
        if not base_path.exists():
            continue
        for skill_md in base_path.rglob("SKILL.md"):
            content = skill_md.read_text()
            fm = parse_frontmatter(content)
            name = fm.get("name", "")
            if name:
                actual_skills[name] = skill_md.relative_to(repo_root)

    # Check for skills missing from index
    missing_from_index = set(actual_skills.keys()) - indexed_skills
    # Check for skills in index that don't exist
    stale_in_index = indexed_skills - set(actual_skills.keys())

    issues = []
    for name in missing_from_index:
        issues.append(f"Skill '{name}' ({actual_skills[name]}) not in index.json")
    for name in stale_in_index:
        issues.append(f"Skill '{name}' in index.json but no SKILL.md found")

    if issues:
        print(f"\n❌ Index sync issues ({len(issues)}):\n")
        for issue in issues:
            print(f"  • {issue}")
        sys.exit(1)
    else:
        print(f"✅ Index.json in sync ({len(actual_skills)} skills)")
        sys.exit(0)


if __name__ == "__main__":
    main()