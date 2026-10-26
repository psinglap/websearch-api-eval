#!/usr/bin/env bash
# One search-only latency pass for one use case, 4 providers in parallel (one call per provider at a time).
set -uo pipefail
cd "$(dirname "$0")"; set -a; . ./.env; set +a
export SEARCH_ONLY=1 PROMPTFOO_PYTHON="$PWD/.venv/bin/python" PROMPTFOO_DISABLE_TELEMETRY=1
n="$1"; uc="$2"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
npx --no-install promptfoo eval -c "promptfooconfig.searchonly_par_$uc.yaml" -j 4 --repeat 1 --no-cache \
  -o "out/searchonly/${uc}_run${n}_$STAMP.json" >> "out/searchonly/run${n}.log" 2>&1 || true
echo "search-only run $n $uc done $STAMP" | tee -a out/searchonly/progress.log
