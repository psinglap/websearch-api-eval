# Web Search API Eval

A live, side-by-side benchmark of four web search APIs for AI agents (**You.com, Tavily, Exa and Parallel**) on 30 agent-style queries across GTM, insurance and finance use cases, plus a buyer memo, a target-account list and a market map built on the results.

By Pallavi Singla · final run Oct 8, 2026

**Live site: https://psinglap.github.io/websearch-api-eval/**

## Contents

- [The four pages](#the-four-pages)
- [Results at a glance](#results-at-a-glance)
- [Results by use case](#results-by-use-case)
- [Methodology](#methodology)
- [Metrics and the benchmarks they follow](#metrics-and-the-benchmarks-they-follow)
- [Developer setup and friction](#developer-setup-and-friction)
- [Limits](#limits)
- [Sources](#sources)
- [Repo layout](#repo-layout)

## The four pages

| | Page | What it covers |
|---|---|---|
| [![Evaluation](img/pages/index.png)](https://psinglap.github.io/websearch-api-eval/) | **[Evaluation](https://psinglap.github.io/websearch-api-eval/)** | The full benchmark: every query, answer key, what each API returned, per-use-case scorecards and the setup friction log. [PDF](pdf/web-search-api-evaluation.pdf) |
| [![GTM memo](img/pages/memo.png)](https://psinglap.github.io/websearch-api-eval/memo/) | **[GTM memo](https://psinglap.github.io/websearch-api-eval/memo/)** | A one-page recommendation for an engineering lead choosing the web search API behind a live GTM chat agent. [PDF](pdf/gtm-memo.pdf) |
| [![Target accounts](img/pages/accounts.png)](https://psinglap.github.io/websearch-api-eval/accounts/) | **[Target accounts](https://psinglap.github.io/websearch-api-eval/accounts/)** | 60 accounts across 6 agent use cases, the developer pain behind them, seven GTM plays and where to reach buyers. Filterable. |
| [![Search Atlas](img/pages/atlas.png)](https://psinglap.github.io/websearch-api-eval/atlas/) | **[Search Atlas](https://psinglap.github.io/websearch-api-eval/atlas/)** | The six ways AI products get web search, with market size today and in 2030, who leads each way, how the market is moving and how to win. |

## Results at a glance

![Overall scorecard: 30 queries, 3 use cases, 4 search APIs](img/overall_scorecard.png)

| Metric (30 queries × 3 repeats = 90 calls per API) | You.com | Tavily | Exa | Parallel |
|---|---|---|---|---|
| Accuracy score (% of max) | 63% | 51% | 53% | **67%** |
| Queries fully correct in all 3 repeats | **57%** | 37% | 50% | **57%** |
| Precision@5 (on-topic share of top 5) | 37% | 26% | **40%** | 26% |
| Results dated inside the query's window | **59%** | 37% | 44% | 29% |
| Newest relevant result, median age | **4.1 h** | 11.9 h | 8.2 h | 16.6 h |
| Empty responses (of 90) | **0** | 27 | 12 | 3 |
| Failed calls: errors, timeouts (of 90) | **0** | **0** | **0** | **0** |
| Latency p50 / p95, client (ms) | **593 / 804** | 1,864 / 3,305 | 1,106 / 3,997 | 2,038 / 4,117 |
| Latency p50, server-reported (ms) | **379** | 1,650 | 831 | n/a |
| Search cost per correct answer | $0.026 | $0.016 | $0.012 | **$0.008** |

**Headline:** You.com is the fastest API tested and the most dependable at returning something fresh: it leads on freshness, reliability and search-only speed. Parallel leads accuracy, with You.com a close second and tied on fully correct queries. Exa returns the most on-topic top 5; Parallel is cheapest per correct answer.

**Which API fits which agent (from this test):**

| If your agent… | Pick | Why |
|---|---|---|
| Answers inside a live turn (voice, chat, alerts) | **You.com** | Fastest at p50 and p95, freshest results, never returned empty |
| Does deep research where seconds don't matter | **Parallel** | Highest finance accuracy; found the release pages and jobless-claims report others missed |
| Needs the most on-topic top 5 for semantic or long-tail queries | **Exa** | Best precision@5 in GTM and insurance; best insurance accuracy |
| Looks up docs or how-to answers | **Tavily** | Best GTM accuracy; correct on the config-docs query |

## Results by use case

Accuracy score (% of max) and search-only client latency p50:

| Use case | Agent job | You.com | Tavily | Exa | Parallel |
|---|---|---|---|---|---|
| **GTM** | Find fresh developer and company buying signals (issues, releases, funding, incidents) | 45% · 627 ms | 47% · 2,843 ms | 45% · 1,102 ms | 45% · 2,268 ms |
| **Insurance** | Voice and claims agent that needs live catastrophe status mid-call (500 ms budget) | 65% · 589 ms | 67% · 1,864 ms | **75%** · 1,093 ms | 67% · 2,038 ms |
| **Finance** | Analyst agent that needs exact, current numbers with primary-source citations | 80% · 592 ms | 40% · 1,642 ms | 40% · 1,106 ms | **88%** · 1,972 ms |

You.com answered all 30 search-only calls in under 1 second; no other provider managed more than 3 of 10 in any use case. Full scorecards, per-query grids and what each API returned are on the [Evaluation page](https://psinglap.github.io/websearch-api-eval/).

## Methodology

**Queries.** 30 queries, 10 per use case (GTM G1–G10, Insurance I1–I10, Finance F1–F10). Each is written the way an AI agent calls web search:

| Field | Example (G3) |
|---|---|
| Upstream task given to the agent | "Any new mentions of Apache Iggy in the last day?" |
| Search call the agent sends | `"Apache Iggy"` |
| Parameters | window 24h |
| What the agent needs back | Every mention (repo, blog, forum) in 24h, with date, or "none" |
| Answer key | Captured at run time, with source link and Wayback Machine snapshot |

Every use case has at least 4 real-time queries; the rest use 24-hour, 48-hour, 7-day or 1-year windows. Some queries expect "none" as the right answer, to test whether an API presents stale pages as current.

**Same request for everyone.** Each provider gets the exact query string with the same parameters: 10 results, full page content where supported, the freshness window, and domain filters where supported.

**Runs.** Searches ran in [promptfoo](https://www.promptfoo.dev/) with Python providers: 3 runs per query, 90 calls per API. Latency is client-side wall-clock time around the HTTP request only, on a persistent connection after one discarded warm-up call; provider-reported server latency is recorded alongside. Search-only speed comes from a run of first-time queries sent one at a time, so caching doesn't flatter repeats.

**Grading.** Answers were written and graded from each provider's saved results (top 5), using the published SimpleQA grader rubric for accuracy and FreshQA strict rules for "none" answers and stale results. Answer keys were captured live at run time and archived to the Wayback Machine.

**Evidence kept per call.** Raw provider JSON, result dates and how each date was found, relevance labels, grader output, and an automatic log of every API anomaly.

## Metrics and the benchmarks they follow

| # | Metric | How it's measured | Standard it follows |
|---|---|---|---|
| 1 | Latency p50 / p95, % within budget | Client wall-clock per call; budget 3 s (GTM, finance), 500 ms (insurance) | [Artificial Analysis search methodology](https://artificialanalysis.ai/methodology/search-api) |
| 2 | Accuracy (0–2) | Correct = 2, incorrect or not attempted = 0; a partly right list = 1 | [SimpleQA](https://arxiv.org/html/2411.04368) grader template, verbatim |
| 3 | Correct "none" | Says "none" when true without citing stale pages as current; never claims "none" when an answer exists | [FreshQA](https://arxiv.org/pdf/2310.03214) strict rules |
| 4 | Freshness: % in window | Share of returned results dated inside the query's window | Provider dates + [htmldate](https://htmldate.readthedocs.io/en/latest/evaluation.html) |
| 5 | Freshness: newest relevant result | Age in hours of the newest relevant result at run time | FreshQA |
| 6 | Precision@5 | Share of the top 5 judged relevant, time window included | TREC-style binary relevance |
| 7 | Content in one call | Search response itself includes usable page text, no second fetch | Measured directly |
| 8 | Token efficiency | Tokens in the top 5 results, per query and per correct answer | tiktoken (cl100k) |
| 9 | Cost per correct answer | Search list price × calls ÷ correct answers | Vendor list prices, dated |
| 10 | Reliability | Errors, timeouts and empty result lists per 90 calls | promptfoo |

With 10 queries per use case, results are reported per query ("won 7 of 10") rather than as percentage-point margins.

## Developer setup and friction

Each signup was screen-recorded from sign-in to a copied API key, then to a first successful call.

![Time and steps to activation](img/time_steps_activation.png)

| | Tavily | You.com | Parallel | Exa |
|---|---|---|---|---|
| Seconds from sign-in to copied key | **25 s** | 55 s | 60 s | 95 s |
| Steps (screens or clicks) | **3** | 11 | 10 | 13 |
| First API call | 1.28 s, HTTP 200 | **0.65 s**, HTTP 200 | 3.57 s, HTTP 200 | 3.20 s, HTTP 200 |

Every provider worked on the first call. The full timed friction log is on the [Evaluation page](https://psinglap.github.io/websearch-api-eval/).

## Limits

- 10 queries per use case is a focused test, not a leaderboard; differences of a query or two are within noise.
- Results reflect one run day (Oct 8, 2026); freshness and accuracy depend on what was published that day.
- Prices are vendor list prices as of the run date; cost covers search only, not the answering model.

## Sources

- **Harnesses and grading:** [promptfoo](https://www.promptfoo.dev/) · [You.com web-search-api-evals](https://github.com/youdotcom-oss/web-search-api-evals) · [Tavily tavily-search-evals](https://github.com/tavily-ai/tavily-search-evals) · [SimpleQA](https://arxiv.org/html/2411.04368) · [FreshLLMs / FreshQA](https://arxiv.org/pdf/2310.03214) · [htmldate evaluation](https://htmldate.readthedocs.io/en/latest/evaluation.html) · [Wayback Machine Save Page Now](https://web.archive.org/save)
- **Third-party benchmarks for comparison:** [Artificial Analysis Search Index](https://artificialanalysis.ai/agents/search-api) · [Openbenchmarks web search](https://openbenchmarks.com/web-search)
- Market and customer facts on the Target accounts and Search Atlas pages come from public sources (vendor case studies, docs, pricing pages, press) and are linked on each page.

## Repo layout

| Path | Contents |
|---|---|
| `index.html` | Evaluation page |
| `memo/` | GTM memo |
| `accounts/` | Target accounts |
| `atlas/` | Search Atlas |
| `img/` | Scorecards, per-query grids, activation charts and page screenshots |
| `pdf/` | PDF versions of the evaluation and memo |
