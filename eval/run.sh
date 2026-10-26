#!/usr/bin/env bash
# Live evaluation harness: 6 web search providers x 3 use cases (promptfoo 0.124.0).
# Default answer_mode=offline: search only, no Anthropic/OpenAI calls; Claude Code answers + grades afterwards.
#
#   ./run.sh setup [--playwright]   create .venv (uv), install Python + Node deps, build tests/configs
#   ./run.sh smoke                  1 query x 6 providers x 1 repeat (checks keys + wiring; costs cents)
#   ./run.sh keys <usecase>         pull open-API ground truth + capture evidence (Wayback, HTML, screenshot)
#   ./run.sh run <usecase>          evidence(before) -> promptfoo --repeat 3 --no-cache -> evidence(after, real-time)
#   ./run.sh export <usecase>       out/grading/<uc>_to_grade.jsonl (+ grading/grades_<uc>.csv template) for Claude Code
#   ./run.sh analyze                scorecards (+ grades, inclusion rule, 20% human-check sample), summary.md, charts
#   ./run.sh crosscheck             OPTIONAL: SimpleQA 20-q sample (needs ANTHROPIC + OPENAI keys; skipped by default)
#   ./run.sh view                   promptfoo web viewer
#   ./run.sh fixtures               offline FAKE end-to-end run (no keys) -> out/fixture_charts/
#   ./run.sh test                   unit tests (pytest, fixtures only)
set -euo pipefail
cd "$(dirname "$0")"
EVAL="$(pwd)"
UV="${UV:-$HOME/.local/bin/uv}"
PY="$EVAL/.venv/bin/python"
PF="npx --no-install promptfoo"
export PROMPTFOO_PYTHON="$PY"            # python used for python assertions
export PROMPTFOO_DISABLE_TELEMETRY=1
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

need_env() {
  [ -f .env ] || { echo "Missing eval/.env - copy .env.example and add your keys"; exit 1; }
  set -a; source .env; set +a
}

check_keys() {
  local missing=()
  for k in YDC_API_KEY TAVILY_API_KEY EXA_API_KEY PARALLEL_API_KEY; do
    [ -n "${!k:-}" ] || missing+=("$k")
  done
  if [ ${#missing[@]} -gt 0 ]; then echo "WARNING: missing keys: ${missing[*]} (those providers will error)"; fi
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  setup)
    [ -x "$PY" ] || "$UV" venv --python 3.12 .venv
    "$UV" pip install --python "$PY" -r requirements.txt
    npm install --no-audit --no-fund
    if [ "${1:-}" = "--playwright" ]; then "$UV" pip install --python "$PY" playwright && "$PY" -m playwright install chromium; fi
    "$PY" tests/build_tests.py
    "$PY" config/make_configs.py
    [ -f crosscheck/simpleqa_sample.yaml ] || "$PY" crosscheck/make_sample.py
    for c in promptfooconfig.*.yaml; do $PF validate -c "$c"; done
    echo "setup done. Next: cp .env.example .env, add keys, then ./run.sh smoke"
    ;;
  smoke)
    need_env; check_keys
    $PF eval -c promptfooconfig.smoke.yaml --repeat 1 --no-cache -o "out/smoke_results_$STAMP.json"
    echo "smoke results: out/smoke_results_$STAMP.json (raw provider JSON in out/raw/smoke/)"
    ;;
  keys)
    uc="${1:?usage: ./run.sh keys gtm|insurance|finance}"
    need_env
    "$PY" ground_truth/pull_all.py "$uc"
    "$PY" evidence/capture.py --usecase "$uc" --phase "keys_$STAMP"
    echo "Next: Claude Code drafts expected_answer / expect_none for $uc in answer_keys.csv from the archived official sources (wayback_url); you review, then ./run.sh run $uc"
    ;;
  run)
    uc="${1:?usage: ./run.sh run gtm|insurance|finance}"
    need_env; check_keys
    if grep -q "^[A-Z][0-9]*,$uc,.*\[FILL AT RUN TIME\]" answer_keys.csv; then
      echo "WARNING: some $uc answer keys are still [FILL AT RUN TIME]; those rows will be UNGRADED."
    fi
    "$PY" evidence/capture.py --usecase "$uc" --phase "before_$STAMP" --realtime-only
    "$PY" ground_truth/pull_all.py "$uc"
    $PF eval -c "promptfooconfig.$uc.yaml" --repeat 3 --no-cache \
      -o "out/${uc}_results_$STAMP.json" -o "out/${uc}_results_$STAMP.csv" || echo "promptfoo exit $? (assertion failures expected; continuing)"
    if [ "$uc" = "finance" ]; then
      $PF eval -c promptfooconfig.finance_f1_variant.yaml --repeat 3 --no-cache \
        -o "out/finance_f1_variant_results_$STAMP.json" -o "out/finance_f1_variant_results_$STAMP.csv" || echo "promptfoo exit $? (continuing)"
    fi
    "$PY" evidence/capture.py --usecase "$uc" --phase "after_$STAMP" --realtime-only
    echo "done: out/${uc}_results_$STAMP.json  (re-check real-time keys against evidence before/after). Next: ./run.sh export $uc"
    ;;
  export)
    uc="${1:?usage: ./run.sh export gtm|insurance|finance}"
    "$PY" grading/export.py "$uc"
    echo "Next: Claude Code grades out/grading/${uc}_to_grade.jsonl into grading/grades_${uc}.csv (grading/RUBRIC.md), then ./run.sh analyze"
    ;;
  crosscheck)
    # OPTIONAL and skipped by default: needs ANTHROPIC_API_KEY (our SimpleQA arm, api mode) and OPENAI_API_KEY (vendor harnesses)
    need_env
    [ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "crosscheck is optional and needs ANTHROPIC_API_KEY (+ OPENAI_API_KEY) - skipped."; exit 0; }
    [ -f crosscheck/simpleqa_sample.yaml ] || "$PY" crosscheck/make_sample.py
    $PF eval -c promptfooconfig.simpleqa.yaml --repeat 1 --no-cache -o out/simpleqa_results.json -o "out/simpleqa_results_$STAMP.csv"
    [ -d crosscheck/vendor/web-search-api-evals/.venv ] || bash crosscheck/setup_vendors.sh
    if [ -n "${OPENAI_API_KEY:-}" ]; then
      bash crosscheck/run_vendor_youcom.sh || echo "You.com harness failed (see log)"
      bash crosscheck/run_vendor_tavily.sh || echo "Tavily harness failed (see log)"
    else
      echo "OPENAI_API_KEY not set: both vendor harnesses use OpenAI models for synthesis/grading - skipped."
    fi
    "$PY" crosscheck/compare.py || true
    ;;
  analyze)
    "$PY" analysis/analyze.py "$@"
    ;;
  view)
    $PF view -y
    ;;
  fixtures)
    "$PY" tests/fixtures/make_fixtures.py && "$PY" analysis/analyze.py --fixture
    ;;
  test)
    "$PY" -m pytest -q tests/unit
    ;;
  *)
    sed -n '2,15p' "$0"
    ;;
esac
