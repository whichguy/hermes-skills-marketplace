#!/usr/bin/env bash
# Run the investigate-plan wrapper suite and its sibling hook regression suite.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
fails=0

if [ "${1:-}" = live ]; then
  INVESTIGATE_TEST_LIVE=1 bash "$HERE/run_investigator.test.sh" || fails=$((fails+1))
else
  INVESTIGATE_TEST_LIVE=0 bash "$HERE/run_investigator.test.sh" || fails=$((fails+1))
fi

GATE_TEST=""
for cand in "$ROOT/handlers/plan-unknowns-gate.test.sh" "$ROOT/hooks/plan-unknowns-gate.test.sh"; do
  [ -f "$cand" ] && GATE_TEST="$cand" && break
done
if [ -n "$GATE_TEST" ]; then
  bash "$GATE_TEST" || fails=$((fails+1))
else
  echo "plan-unknowns-gate.test.sh not found in handlers/ or hooks/"
  fails=$((fails+1))
fi

echo; [ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails SUITE(S) FAILED"; exit "$fails"
