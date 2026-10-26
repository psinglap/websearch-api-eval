# Cross-check with the vendors' own harnesses

**Goal:** show that our promptfoo harness grades the same way as the harnesses that You.com and Tavily publish. All three run the same 20 SimpleQA questions, then `compare.py` reports per-question agreement and Cohen's kappa.

## Control sample
- **Source:** the official SimpleQA test set used by `openai/simple-evals` (`simpleqa_eval.py`): https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv
  - 4,326 rows; sha256 in `simple_qa_test_set.sha256`.
- **Sample:** `pandas.DataFrame.sample(n=20, random_state=42)`.
  - `simpleqa_sample20.csv` uses the official columns, so it drops into both vendor harnesses.
  - `simpleqa_sample.yaml` holds the same questions as promptfoo tests.
- **Our run:** `promptfooconfig.simpleqa.yaml` (7 providers, no date filter).

## Vendor harnesses (verified 2026-10-08)

| Harness | Commit | Providers it supports | Missing from our 7 | How the wrapper runs it |
|---|---|---|---|---|
| [youdotcom-oss/web-search-api-evals](https://github.com/youdotcom-oss/web-search-api-evals) | `2e3e1b5` (2026-10-08) | You.com (`you_search`, `you_search_with_livecrawl`, research tiers), Exa, Parallel, Tavily, Google (SerpAPI), Perplexity | Firecrawl, Linkup, Claude web_search | `run_vendor_youcom.sh` swaps `data/simpleqa_full_dataset.csv` for our sample (its `--limit` samples without a seed), runs `eval_runner.py --samplers you_search exa_search_with_text parallel_search_basic tavily_search --datasets simpleqa`, then restores the file |
| [tavily-ai/tavily-search-evals](https://github.com/tavily-ai/tavily-search-evals) | `99feb7d` (2026-01-29) | Tavily, Exa, Brave, Serper, Perplexity Search, Perplexity, GPT Researcher | You.com, Parallel, Firecrawl, Linkup, Claude web_search | `run_vendor_tavily.sh` swaps `datasets/simple_qa_test_set.csv`, runs `run_evaluation.py --evaluation_type simpleqa --config crosscheck/tavily_harness_config.json` (Tavily basic depth, 10 results, to match ours), then restores the file |

Providers covered by more than one harness:
- **Tavily and Exa:** all three harnesses.
- **You.com and Parallel:** ours and You.com's.
- **Firecrawl, Linkup and Claude web_search:** ours only (no vendor harness supports them).

**Grader templates.**
- You.com's SimpleQA grader is byte-identical to OpenAI's, and to our `asserts/simpleqa_grader_template.txt`.
- Tavily's `OPENAI_GRADER_TEMPLATE` matches it line for line, except for indentation and the placeholder name `{reference_answer}`. Checked with an AST diff on 2026-10-08.

**Models differ.**
- Both vendor harnesses use OpenAI models (You.com's `constants.py`: synthesis `gpt-5.6-luna`, grader `gpt-5.4-mini`; Tavily's: `gpt-4.1` for post-processing and grading). They therefore need `OPENAI_API_KEY`.
- Our harness answers and grades with Claude.
- Treat disagreements as answer-model and grader effects, not search-quality differences; the kappa shows how large they are.

## Run

```bash
./run.sh crosscheck        # = make_sample (if needed) + our simpleqa run + setup_vendors.sh + both vendor runs + compare.py
# or step by step
.venv/bin/python crosscheck/make_sample.py
bash crosscheck/setup_vendors.sh           # clones at the pinned commits, one uv venv (Python 3.12) each
bash crosscheck/run_vendor_youcom.sh       # needs YDC/EXA/PARALLEL/TAVILY/OPENAI keys in eval/.env
bash crosscheck/run_vendor_tavily.sh       # needs TAVILY/EXA/OPENAI keys
.venv/bin/python crosscheck/compare.py     # -> out/crosscheck/agreement.{csv,md}
```

Cost: 20 questions × 4 providers in each vendor harness, plus 20 × 7 in ours.
