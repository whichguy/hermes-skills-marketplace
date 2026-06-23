#!/usr/bin/env python3
"""Validate all skills in the marketplace repo."""

import sys
import os
from pathlib import Path

# Import the single-skill validator
sys.path.insert(0, os.path.dirname(__file__))
from validate_skill import validate_skill


def main():
    repo_root = Path(__file__).parent.parent
    skill_dirs = []

    # Find all SKILL.md files in skills/ and community/
    for base in ["skills", "community", "skill-template"]:
        base_path = repo_root / base
        if not base_path.exists():
            continue
        for skill_md in base_path.rglob("SKILL.md"):
            skill_dirs.append(skill_md.parent)

    if not skill_dirs:
        print("No skills found to validate.")
        return

    total = len(skill_dirs)
    passed = 0
    failed = 0

    for skill_dir in sorted(skill_dirs):
        rel = skill_dir.relative_to(repo_root)
        errors = validate_skill(str(skill_dir))
        if errors:
            failed += 1
            print(f"\n❌ {rel} — {len(errors)} issue(s):")
            for e in errors:
                print(f"   • {e}")
        else:
            passed += 1
            print(f"✅ {rel}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {total} total")

    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()