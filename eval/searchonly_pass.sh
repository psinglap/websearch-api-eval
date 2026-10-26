#!/usr/bin/env bash
# Config A: search only (SEARCH_ONLY=1), one request at a time (-j 1), no cache. Arg: run number.
set -uo pipefail
cd "$(dirname "$0")"; set -a; . ./.env; set +a
export SEARCH_ONLY=1 PROMPTFOO_PYTHON="$PWD/.venv/bin/python" PROMPTFOO_DISABLE_TELEMETRY=1
n="$1"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p out/searchonly
for uc in gtm insurance finance; do
  npx --no-install promptfoo eval -c "promptfooconfig.searchonly_$uc.yaml" -j 1 --repeat 1 --no-cache \
    -o "out/searchonly/${uc}_run${n}_$STAMP.json" >> "out/searchonly/run${n}.log" 2>&1 || true
  [ "$n" = "1" ] && .venv/bin/python evidence/capture.py --usecase "$uc" --phase "searchonly_run1_$STAMP" --realtime-only >> "out/searchonly/run1_evidence.log" 2>&1
done
echo "search-only run $n done $STAMP" | tee -a out/searchonly/progress.log
