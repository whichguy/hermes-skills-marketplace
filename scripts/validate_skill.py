#!/usr/bin/env python3
"""
Validate a single skill directory — frontmatter, config-code separation,
and marketplace readiness.

Usage:
    python scripts/validate_skill.py skills/productivity/wellness-finder/

Exits 0 if valid, 1 if any check fails.
"""

import sys
import os
import re
import yaml
import json
from pathlib import Path


# ── Limits ──
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_CONTENT_CHARS = 150_000
RECOMMENDED_MAX_SKILL_CHARS = 15_000

# ── Required frontmatter fields ──
REQUIRED_FIELDS = ["name", "description", "version", "author", "license", "platforms"]

# ── Allowed subdirectories ──
ALLOWED_SUBDIRS = {"scripts", "templates", "references", "assets", "prompts", "tests", "examples", "evals", "workflows", "shared", "agents"}


def parse_frontmatter(content: str) -> tuple[dict | None, str | None]:
    """Parse YAML frontmatter from SKILL.md content."""
    if not content.startswith("---"):
        return None, "File must start with '---'"

    match = re.search(r'\n---\s*\n', content[3:])
    if not match:
        return None, "Frontmatter not closed with '---'"

    try:
        fm = yaml.safe_load(content[3:match.start() + 3])
    except yaml.YAMLError as e:
        return None, f"YAML parse error: {e}"

    if not isinstance(fm, dict):
        return None, "Frontmatter is not a YAML mapping"

    return fm, None


def validate_skill(skill_dir: str) -> list[str]:
    """Validate a skill directory. Returns list of error messages (empty = valid)."""
    errors = []
    skill_path = Path(skill_dir)
    skill_md = skill_path / "SKILL.md"

    # ── SKILL.md exists ──
    if not skill_md.exists():
        errors.append(f"SKILL.md not found in {skill_dir}")
        return errors

    content = skill_md.read_text()

    # ── Frontmatter parse ──
    fm, err = parse_frontmatter(content)
    if err:
        errors.append(f"Frontmatter: {err}")
        return errors

    # ── Required fields ──
    for field in REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"Missing required field: {field}")

    # ── Name constraints ──
    name = fm.get("name", "")
    if name:
        if len(name) > MAX_NAME_LENGTH:
            errors.append(f"name too long: {len(name)} > {MAX_NAME_LENGTH} chars")
        if not re.match(r'^[a-z][a-z0-9-]*$', name):
            errors.append(f"name must be lowercase + hyphens + digits, got: '{name}'")

    # ── Description constraints ──
    desc = fm.get("description", "")
    if desc:
        if len(desc) > MAX_DESCRIPTION_LENGTH:
            errors.append(f"description too long: {len(desc)} > {MAX_DESCRIPTION_LENGTH} chars")

    # ── Content size ──
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        errors.append(f"SKILL.md too large: {len(content)} > {MAX_SKILL_CONTENT_CHARS} chars")

    # ── Config declaration (warning only, not failure) ──
    meta = fm.get("metadata", {}).get("hermes", {})
    config_keys = meta.get("config", [])

    # ── Required env vars ──
    env_vars = fm.get("required_environment_variables", [])
    # Built-in env vars that don't need declaration
    BUILTIN_ENV = {"HERMES_HOME", "HERMES_SESSION_ID", "HERMES_SKILL_DIR", "PATH", "HOME", "USER", "HERMES_GWS_BIN"}
    # Check scripts don't reference env vars not declared
    scripts_dir = skill_path / "scripts"
    if scripts_dir.exists():
        for py_file in scripts_dir.glob("*.py"):
            script_content = py_file.read_text()
            # Find os.getenv("VAR_NAME") calls
            getenv_calls = re.findall(r'os\.getenv\(["\'](\w+)["\']', script_content)
            for var in getenv_calls:
                # Skip built-in env vars and template variables
                if var in BUILTIN_ENV:
                    continue
                if var.startswith("SKILL_") and not env_vars:
                    continue
                declared = any(ev.get("name") == var for ev in env_vars) if env_vars else False
                if not declared and not var.startswith("SKILL_"):
                    errors.append(
                        f"scripts/{py_file.name}: os.getenv('{var}') not declared in "
                        f"required_environment_variables"
                    )

    # ── Check for hardcoded secrets in scripts ──
    if scripts_dir.exists():
        secret_patterns = [
            (r'sk-[a-zA-Z0-9]{20,}', "hardcoded API key (sk- format)"),
            (r'ghp_[a-zA-Z0-9]{36,}', "hardcoded GitHub token"),
            (r'AIza[a-zA-Z0-9_-]{35}', "hardcoded Google API key"),
            (r'xox[baprs]-[a-zA-Z0-9-]+', "hardcoded Slack token"),
            (r'AKIA[0-9A-Z]{16}', "hardcoded AWS access key"),
            (r'-----BEGIN (RSA |EC )?PRIVATE KEY-----', "private key block"),
        ]
        for py_file in scripts_dir.glob("*.py"):
            script_content = py_file.read_text()
            for pattern, desc in secret_patterns:
                if re.search(pattern, script_content):
                    errors.append(f"scripts/{py_file.name}: {desc} detected")

    # ── Check for hardcoded config in SKILL.md prose ──
    # Skip code blocks (``` ... ```) since those are examples, not instructions
    prose_content = re.sub(r'```[\s\S]*?```', '', content)
    hardcoded_indicators = [
        (r'replace\s+\w+\s+with\s+your\s+', "instruction to replace a value (should be config)"),
        (r'change\s+the\s+\w+\s+to\s+\d+', "instruction to change a numeric value (should be config)"),
        (r'set\s+\w+\s+to\s+["\']\w+["\']', "instruction to set a string value (should be config)"),
    ]
    for pattern, desc in hardcoded_indicators:
        matches = re.findall(pattern, prose_content, re.IGNORECASE)
        if matches:
            errors.append(f"SKILL.md: {desc} — move to metadata.hermes.config")

    # ── Subdirectory check (skip hidden dirs like .pytest_cache) ──
    for child in skill_path.iterdir():
        if child.is_dir() and not child.name.startswith(".") and child.name not in ALLOWED_SUBDIRS:
            errors.append(
                f"unexpected subdirectory: {child.name}/ "
                f"(allowed: {', '.join(sorted(ALLOWED_SUBDIRS))})"
            )

    # ── Platforms check ──
    platforms = fm.get("platforms")
    if platforms:
        valid_platforms = {"linux", "macos", "windows"}
        invalid = set(platforms) - valid_platforms
        if invalid:
            errors.append(f"invalid platform values: {invalid} (valid: {valid_platforms})")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_skill.py <skill-dir>")
        sys.exit(1)

    skill_dir = sys.argv[1]
    if not os.path.isdir(skill_dir):
        print(f"ERROR: {skill_dir} is not a directory")
        sys.exit(1)

    errors = validate_skill(skill_dir)

    if errors:
        print(f"\n❌ {skill_dir} — {len(errors)} issue(s):\n")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)
    else:
        print(f"✅ {skill_dir} — all checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()