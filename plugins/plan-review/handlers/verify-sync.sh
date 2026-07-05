#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
sha256sum -c CANONICAL.sha256
