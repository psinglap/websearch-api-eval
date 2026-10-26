#!/usr/bin/env bash
# Run the 20-question SimpleQA sample through You.com's harness (youdotcom-oss/web-search-api-evals).
# Supported providers there: You.com, Exa, Parallel, Tavily (+ Google/SerpAPI, Perplexity).
# NOT supported: Firecrawl, Linkup, Claude web_search -> covered only by our promptfoo harness.
# Needs in eval/.env: YDC_API_KEY EXA_API_KEY PARALLEL_API_KEY TAVILY_API_KEY OPENAI_API_KEY
# (its synthesis and grader models are OpenAI models set in src/evals/constants.py).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; EVAL="$(dirname "$HERE")"; V="$HERE/vendor/web-search-api-evals"
SAMPLERS="${SAMPLERS:-you_search exa_search_with_text parallel_search_basic tavily_search}"
[ -f "$HERE/simpleqa_sample20.csv" ] || "$EVAL/.venv/bin/python" "$HERE/make_sample.py"
set -a; source "$EVAL/.env"; set +a
cp "$V/data/simpleqa_full_dataset.csv" "$V/data/simpleqa_full_dataset.csv.orig"
trap 'mv "$V/data/simpleqa_full_dataset.csv.orig" "$V/data/simpleqa_full_dataset.csv"' EXIT
cp "$HERE/simpleqa_sample20.csv" "$V/data/simpleqa_full_dataset.csv"   # same 20 questions, no --limit (its --limit samples without a seed)
OUT="$EVAL/out/crosscheck/youcom_harness/$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"
( cd "$V" && .venv/bin/python src/evals/eval_runner.py --samplers $SAMPLERS --datasets simpleqa --clean ) 2>&1 | tee "$OUT/run.log"
cp -R "$V/src/evals/results/." "$OUT/" 2>/dev/null || true
echo "results copied to $OUT"
