#!/usr/bin/env bash
set -euo pipefail

SRC="$HOME/.hermes/skills/productivity/ask"
DST="$HOME/.hermes/hermes-skills-marketplace/skills/ask"

if diff -rq \
    -x '__pycache__' \
    -x '.pytest_cache' \
    -x '.coverage' \
    "$SRC" "$DST"; then
  echo "OK: installed ask skill and marketplace copy are in sync"
  exit 0
else
  echo "DRIFT DETECTED between $SRC and $DST" >&2
  exit 1
fi
