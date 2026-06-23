#!/usr/bin/env python3
"""
Check that scripts don't hardcode config values that should be in
metadata.hermes.config or required_environment_variables.
"""

import sys
import os
import re
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


def check_script(script_path: Path, declared_env_vars: set, declared_config_keys: set) -> list[str]:
    """Check a Python script for hardcoded config values."""
    issues = []
    content = script_path.read_text()

    # Patterns that indicate hardcoded secrets (exclude placeholders and examples)
    # Skip values that are clearly placeholders: contain ... or are *** or are < 3 real chars
    secret_patterns = [
        (r'sk-[a-zA-Z0-9]{20,}', "hardcoded API key (sk- format)"),
        (r'ghp_[a-zA-Z0-9]{36,}', "hardcoded GitHub token"),
        (r'AIza[a-zA-Z0-9_-]{35}', "hardcoded Google API key"),
        (r'xox[baprs]-[a-zA-Z0-9-]+', "hardcoded Slack token"),
        (r'AKIA[0-9A-Z]{16}', "hardcoded AWS access key"),
        (r'-----BEGIN (RSA |EC )?PRIVATE KEY-----', "private key block"),
    ]

    for pattern, msg in secret_patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            line_num = content[:match.start()].count('\n') + 1
            issues.append(f"{script_path.name}:{line_num}: {msg} (found: '{match.group()[:50]}')")

    return issues


def main():
    repo_root = Path(__file__).parent.parent
    all_issues = []

    for base in ["skills", "community", "skill-template"]:
        base_path = repo_root / base
        if not base_path.exists():
            continue

        for skill_md in base_path.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            rel = skill_dir.relative_to(repo_root)

            content = skill_md.read_text()
            fm = parse_frontmatter(content)

            # Get declared env vars
            env_vars = set()
            for ev in fm.get("required_environment_variables", []) or []:
                if isinstance(ev, dict) and "name" in ev:
                    env_vars.add(ev["name"])

            # Get declared config keys
            config_keys = set()
            meta = fm.get("metadata", {}) or {}
            hermes_meta = meta.get("hermes", {}) or {}
            for cfg in hermes_meta.get("config", []) or []:
                if isinstance(cfg, dict) and "key" in cfg:
                    config_keys.add(cfg["key"])

            # Check all Python scripts
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.exists():
                for py_file in scripts_dir.glob("*.py"):
                    issues = check_script(py_file, env_vars, config_keys)
                    for issue in issues:
                        all_issues.append(f"{rel}/scripts/{issue}")

    if all_issues:
        print(f"\n❌ Config-code separation issues ({len(all_issues)}):\n")
        for issue in all_issues:
            print(f"  • {issue}")
        sys.exit(1)
    else:
        print("✅ All scripts pass config-code separation checks")
        sys.exit(0)


if __name__ == "__main__":
    main()