#!/usr/bin/env python3
"""
Generate .well-known/skills/index.json from actual skill directories.
Also regenerates CATALOG.md from the index.
"""

import json
import os
import re
import yaml
import sys
from pathlib import Path


def parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    m = re.search(r'\n---\s*\n', content[3:])
    if not m:
        return {}
    try:
        fm = yaml.safe_load(content[3:m.start()+3])
        return fm if isinstance(fm, dict) else {}
    except Exception:
        return {}


def main():
    quiet = "--quiet" in sys.argv
    repo_root = Path(__file__).parent.parent
    skills_dir = repo_root / "skills"
    
    entries = []
    
    if skills_dir.exists():
        for skill_md in skills_dir.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            rel = skill_dir.relative_to(repo_root)
            
            content = skill_md.read_text()
            fm = parse_frontmatter(content)
            
            meta = (fm.get("metadata") or {}).get("hermes") or {}
            config_keys = [c.get("key", "") for c in (meta.get("config") or []) if isinstance(c, dict)]
            env_vars = fm.get("required_environment_variables") or []
            env_names = [ev.get("name", "") for ev in env_vars if isinstance(ev, dict)]
            cred_files = fm.get("required_credential_files") or []
            cred_paths = [cf.get("path", "") for cf in cred_files if isinstance(cf, dict)]
            
            # Category from path
            parts = skill_dir.relative_to(skills_dir).parts
            category = parts[0] if parts else meta.get("category", "productivity")
            
            entries.append({
                "name": fm.get("name", skill_dir.name),
                "description": str(fm.get("description", ""))[:200],
                "category": category,
                "version": str(fm.get("version", "1.0.0")),
                "author": fm.get("author", ""),
                "license": fm.get("license", "MIT"),
                "platforms": fm.get("platforms", ["linux", "macos", "windows"]),
                "requires_toolsets": meta.get("requires_toolsets", []),
                "config_keys": config_keys,
                "required_env": env_names,
                "required_credentials": cred_paths,
                "path": str(rel) + "/SKILL.md",
            })
    
    entries.sort(key=lambda x: x["name"])
    
    # Write index.json
    index_path = repo_root / ".well-known" / "skills" / "index.json"
    index_data = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Hermes Skills Marketplace",
        "description": "Custom skills marketplace for Hermes Agent — config-code separation enforced",
        "skills": entries,
    }
    with open(index_path, "w") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
    
    # Write CATALOG.md
    catalog_path = repo_root / "CATALOG.md"
    lines = [
        "# Hermes Skills Marketplace Catalog",
        "",
        f"<!-- Auto-generated from .well-known/skills/index.json — {len(entries)} skills -->",
        "",
        "## All Skills",
        "",
        "| Name | Category | Description | Platforms | Author |",
        "|------|----------|-------------|----------|--------|",
    ]
    for e in entries:
        platforms = ", ".join(e["platforms"]) if isinstance(e["platforms"], list) else e["platforms"]
        desc = e["description"][:80].replace("|", "\\|")
        lines.append(f"| [{e['name']}]({e['path']}) | {e['category']} | {desc} | {platforms} | {e['author']} |")
    
    lines.extend([
        "",
        "---",
        f"_Install: `hermes skills tap add whichguy/hermes-skills-marketplace` then `hermes skills install {entries[0]['name'] if entries else 'skill-name'}`_",
    ])
    
    with open(catalog_path, "w") as f:
        f.write("\n".join(lines))
    
    if not quiet:
        print(f"Generated index.json ({len(entries)} skills) + CATALOG.md")


if __name__ == "__main__":
    main()