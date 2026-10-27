---
name: evaluate-web-search-apis
description: Choose or benchmark a web search API (You.com, Tavily, Exa, Parallel) for an AI agent. Use when the user asks which search API to use for an agent, RAG or voice/chat assistant, wants to compare search providers on speed, accuracy, freshness or cost, or wants to run a web search API evaluation on their own queries.
---

# Evaluate web search APIs for an agent

This plugin's `websearch-api-eval` MCP server has the published Web Search API Eval benchmark (You.com, Tavily, Exa and Parallel; 30 agent-style queries across GTM, insurance and finance; 3 runs each; run Oct 8, 2026) and a live spot-check tool.

Work through the levels below in order and stop at the one that answers the user's question.

## 1. Start from the published results

- Clarify the agent's job if it isn't stated: live voice/chat turn, background research, docs lookup, monitoring, or a specific domain (GTM, insurance, finance).
- Call `recommend_provider` with that need, then `get_scorecard` for the closest use case (or `overall`).
- Use `compare_providers` when the user names two or more providers, and `get_question` to show a concrete example query with its answer key and what each API returned.
- Use `get_charts` when a visual helps, and `get_methodology` when the user asks how a number was measured.
- Always state that these are published results from the Oct 8, 2026 run, not live data, and link https://psinglap.github.io/websearch-api-eval/.

## 2. Spot-check on the user's own query

- Offer `run_live_search` with a query from the user's real workload. It calls each provider with the API keys in the user's environment (`YDC_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`, `PARALLEL_API_KEY`); providers without a key are skipped and the output says which key to set.
- These calls use the user's own provider credits. Ask before running more than a few.
- Present latency, result count and the top results side by side, and say clearly that one call is a spot check, not a benchmark.

## 3. Full benchmark on their own queries

When the user wants graded, repeatable results, guide a local run of the open-source harness (call `how_to_run_locally` for the current steps):

1. `git clone https://github.com/psinglap/websearch-api-eval.git && cd websearch-api-eval/eval`
2. `./run.sh setup --playwright`, then `cp .env.example .env` and add their own keys. Never ask the user to paste keys into the chat.
3. Write their queries in `reports/Agent queries.md` and answer keys in `eval/answer_keys.csv`, then rebuild tests with `eval/tests/build_tests.py`.
4. `./run.sh smoke`, then `./run.sh run <usecase>`, then `./run.sh analyze`. Metric definitions are in `eval/METRICS.md`.

## Guardrails

- Don't present a single live call or a single query as a ranking.
- Keep provider comparisons tied to the metric and use case they came from; don't generalize one use case's winner to all agents.
- Don't run the full harness without the user's explicit go-ahead; it calls paid APIs many times.
