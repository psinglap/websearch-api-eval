---
license: mit
pretty_name: Web Search API Eval
language:
- en
size_categories:
- n<1K
task_categories:
- question-answering
- text-retrieval
tags:
- web-search
- search-api
- benchmark
- evaluation
- rag
- ai-agents
- freshness
- you.com
- tavily
- exa
- parallel
configs:
- config_name: questions
  data_files: questions.jsonl
  default: true
- config_name: results
  data_files: results.jsonl
- config_name: scorecards
  data_files: scorecards.jsonl
---

# Web Search API Eval

A live, side-by-side benchmark of four web search APIs for AI agents: **You.com, Tavily, Exa and Parallel**. It covers 30 agent-style queries across three use cases (GTM, insurance, finance), with 3 runs per query (90 calls per API), run on **October 8, 2026**.

- **Full results and charts:** https://psinglap.github.io/websearch-api-eval/
- **Code, harness and methodology:** https://github.com/psinglap/websearch-api-eval
- **Use it from Claude, ChatGPT or Cursor (MCP):** `https://websearch-api-eval.psberkeleymba.workers.dev/mcp` or `npx -y websearch-api-eval-mcp`

## Subsets

| Config | Rows | What each row is |
|---|---|---|
| `questions` (default) | 30 | One agent query: the upstream task, the exact search call sent to every API, its parameters (freshness window, domain filters), what the agent needs back, the answer key captured live, and source URLs |
| `results` | 120 | One query × provider: a short summary of what the API returned and its accuracy score (0–2, mean of 3 runs, SimpleQA rubric) |
| `scorecards` | 136 | One metric × provider × scope (`overall`, `gtm`, `insurance`, `finance`): latency, accuracy, freshness, empty responses, content, tokens and cost, as published |

```python
from datasets import load_dataset

questions = load_dataset("psinglap/websearch-api-eval", "questions", split="train")
results = load_dataset("psinglap/websearch-api-eval", "results", split="train")
```

## Headline results (overall, 90 calls per API)

| Metric | You.com | Tavily | Exa | Parallel |
|---|---|---|---|---|
| Accuracy score (% of max) | 63% | 51% | 53% | **67%** |
| Queries fully correct in all 3 repeats | **57%** | 37% | 50% | **57%** |
| Results dated inside the query's window | **59%** | 37% | 44% | 29% |
| Empty responses (of 90) | **0** | 27 | 12 | 3 |
| Latency p50 / p95, client (ms) | **593 / 804** | 1,864 / 3,305 | 1,106 / 3,997 | 2,038 / 4,117 |
| Search cost per correct answer | $0.026 | $0.016 | $0.012 | **$0.008** |

## Methodology

- **Queries.** Each query is written the way an agent calls web search: an upstream task, the search call, its parameters and what the agent needs back. Every use case has at least 4 real-time queries; the rest use 24-hour, 48-hour, 7-day or 1-year windows. Some queries expect "none" as the correct answer.
- **Same request for every API.** 10 results, full content where supported, the freshness window, and domain filters where supported.
- **Runs.** promptfoo, 3 runs per query. Latency is client wall-clock around the HTTP request after a discarded warm-up call; server-reported latency is kept alongside.
- **Grading.** Answers were graded from each provider's saved top-5 results with the published [SimpleQA](https://arxiv.org/abs/2411.04368) grader rubric (correct = 2, partial list = 1, incorrect or not attempted = 0). "None" answers and stale results follow [FreshQA](https://arxiv.org/abs/2310.03214) strict rules. Answer keys were captured at run time and archived to the Wayback Machine.
- **Full metric definitions:** [eval/METRICS.md](https://github.com/psinglap/websearch-api-eval/blob/main/eval/METRICS.md).

## Limits

- 10 queries per use case is a focused test, not a leaderboard; differences of a query or two are within noise.
- Results reflect one run day (Oct 8, 2026). Freshness and accuracy depend on what was published that day, so answer keys for real-time queries are only valid for that date.
- Costs are vendor list prices on the run date and cover search only.
- `returned` is a short human-written summary, not the raw API response.

## Citation

```bibtex
@misc{singla2026websearchapieval,
  title  = {Web Search API Eval: You.com, Tavily, Exa and Parallel on 30 agent queries},
  author = {Singla, Pallavi},
  year   = {2026},
  url    = {https://github.com/psinglap/websearch-api-eval}
}
```

## License

MIT. Product names and trademarks belong to their owners. This benchmark is independent and was not sponsored by any provider.
