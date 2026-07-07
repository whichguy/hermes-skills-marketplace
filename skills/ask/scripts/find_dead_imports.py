#!/usr/bin/env python3
"""find_dead_imports — Find Python files in a skill directory that are never imported.

Scans all .py files in the directory and checks which are imported by any other
file. Files that are never imported (and aren't __init__.py or __main__.py) are
reported as potentially dead code.

Usage:
    python3 find_dead_imports.py [directory]
    python3 find_dead_imports.py /opt/data/skills/productivity/ask/scripts

Exit codes: 0 = no dead files found, 1 = dead files found, 2 = error.
"""
import os
import re
import sys


def find_dead_imports(skill_dir: str) -> list:
    """Find .py files never imported by any other .py file in the directory.

    Args:
        skill_dir: Directory to scan.

    Returns:
        List of (filename, path) tuples for files that appear to be dead code.
    """
    all_files = {}  # basename -> full path
    imported_names = set()

    for root, _, files in os.walk(skill_dir):
        for f in files:
            if f.endswith('.py') and f not in ('__init__.py', '__main__.py', 'setup.py'):
                path = os.path.join(root, f)
                all_files[f] = path
                # Read the file and collect what it imports
                try:
                    with open(path) as fh:
                        for line in fh:
                            # Match: from <module> import ...  OR  import <module>
                            m = re.match(r'(?:from|import)\s+([\w.]+)', line)
                            if m:
                                # Extract the base module name (first segment)
                                base = m.group(1).split('.')[0]
                                imported_names.add(base + '.py')
                except (IOError, UnicodeDecodeError):
                    pass

    # A file is "alive" if it's imported by at least one other file,
    # OR if it's a CLI entry point (contains __main__ guard or argparse)
    dead = []
    for basename, path in all_files.items():
        if basename in imported_names:
            continue
        # Check if it's a CLI entry point (has argparse or __main__)
        try:
            with open(path) as fh:
                content = fh.read()
                if 'argparse' in content or '__main__' in content:
                    continue  # CLI entry point — not dead
        except (IOError, UnicodeDecodeError):
            pass
        dead.append((basename, path))

    return dead


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(target):
        print(f"Error: {target} is not a directory", file=sys.stderr)
        sys.exit(2)

    dead_files = find_dead_imports(target)
    if not dead_files:
        print("No dead imports found.")
        sys.exit(0)
    else:
        print(f"Found {len(dead_files)} potentially dead file(s):")
        for name, path in sorted(dead_files):
            print(f"  DEAD: {name} ({path})")
        sys.exit(1)