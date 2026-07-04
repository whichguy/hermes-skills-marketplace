#!/usr/bin/env bash
# Aggregate dev check for the plan-review handlers: sync integrity + both gate suites.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
fails=0
bash "$HERE/verify-sync.sh"              || fails=$((fails+1))
bash "$HERE/plan-unknowns-gate.test.sh"  || fails=$((fails+1))
bash "$HERE/plan-worktree-gate.test.sh"  || fails=$((fails+1))
echo; [ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails CHECK(S) FAILED"; exit "$fails"
