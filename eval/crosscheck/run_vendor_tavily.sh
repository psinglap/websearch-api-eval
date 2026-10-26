#!/usr/bin/env bash
# Run the 20-question SimpleQA sample through Tavily's harness (tavily-ai/tavily-search-evals).
# Supported providers there: tavily, exa, brave, serper, perplexity_search, perplexity, gptr.
# NOT supported: You.com, Parallel, Firecrawl, Linkup, Claude web_search.
# Needs in eval/.env: TAVILY_API_KEY EXA_API_KEY OPENAI_API_KEY (gpt-4.1 post-processing + grader by default).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; EVAL="$(dirname "$HERE")"; V="$HERE/vendor/tavily-search-evals"
[ -f "$HERE/simpleqa_sample20.csv" ] || "$EVAL/.venv/bin/python" "$HERE/make_sample.py"
set -a; source "$EVAL/.env"; set +a
cp "$V/datasets/simple_qa_test_set.csv" "$V/datasets/simple_qa_test_set.csv.orig"
trap 'mv "$V/datasets/simple_qa_test_set.csv.orig" "$V/datasets/simple_qa_test_set.csv"' EXIT
cp "$HERE/simpleqa_sample20.csv" "$V/datasets/simple_qa_test_set.csv"
OUT="$EVAL/out/crosscheck/tavily_harness"; mkdir -p "$OUT"
( cd "$V" && .venv/bin/python run_evaluation.py --evaluation_type simpleqa --config "$HERE/tavily_harness_config.json" \
    --output_dir "$OUT" ) 2>&1 | tee "$OUT/run_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "results in $OUT"
