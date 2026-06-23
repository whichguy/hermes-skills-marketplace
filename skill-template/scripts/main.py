#!/usr/bin/env python3
"""
Skill script template — pure logic, reads ALL config from environment.

Hermes injects metadata.hermes.config values and required_environment_variables
into the terminal/execute_code sandbox as environment variables. This script
NEVER hardcodes user-tunable values.

Usage:
    python main.py --query "steam room gym" --location "Colorado Springs"

Config is read from env vars (set by Hermes from config.yaml + .env):
    SKILL_SEARCH_RADIUS_KM   (default: 10)
    SKILL_API_ENDPOINT       (default: https://api.example.com/v1/search)
    SKILL_API_KEY            (required — no default, should come from .env)
    SKILL_TIMEZONE           (default: UTC)
    SKILL_OUTPUT_FORMAT      (default: markdown)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime


def get_config():
    """Read all config from environment — never hardcode."""
    return {
        "radius_km": os.getenv("SKILL_SEARCH_RADIUS_KM", "10"),
        "api_endpoint": os.getenv("SKILL_API_ENDPOINT", "https://api.example.com/v1/search"),
        "api_key": os.getenv("SKILL_API_KEY", ""),
        "timezone": os.getenv("SKILL_TIMEZONE", "UTC"),
        "output_format": os.getenv("SKILL_OUTPUT_FORMAT", "markdown"),
    }


def search(query: str, location: str, config: dict) -> dict:
    """Pure logic — uses config from env, no hardcoded values."""
    if not config["api_key"]:
        return {"error": "SKILL_API_KEY not set. Run skill setup to configure."}

    params = {
        "query": query,
        "location": location,
        "radius_km": config["radius_km"],
    }

    url = f"{config['api_endpoint']}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def format_output(results: dict, template_path: str = None) -> str:
    """Format results using a template from templates/ dir (swappable)."""
    if template_path and os.path.exists(template_path):
        with open(template_path) as f:
            template = f.read()
        # Simple template substitution — replace {{key}} placeholders
        for key, value in results.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))
        return template

    # Default: JSON output
    return json.dumps(results, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Skill search script")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--location", required=True, help="Location to search")
    parser.add_argument("--template", help="Path to output template (optional)")
    args = parser.parse_args()

    config = get_config()

    if not config["api_key"]:
        print("ERROR: SKILL_API_KEY not set. Configure via skill setup.", file=sys.stderr)
        sys.exit(1)

    results = search(args.query, args.location, config)

    # Use template from skill dir if available
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_template = os.path.join(skill_dir, "templates", "output.md")
    template_path = args.template or default_template

    output = format_output(results, template_path)
    print(output)


if __name__ == "__main__":
    main()