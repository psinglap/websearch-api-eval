# Web Search API Eval: MCP server

A read-only [MCP](https://modelcontextprotocol.io) server that lets Claude, ChatGPT and other AI assistants answer questions about the [Web Search API Eval](https://psinglap.github.io/websearch-api-eval/) benchmark (You.com, Tavily, Exa and Parallel on 30 agent queries).

**Endpoint:** `https://websearch-api-eval.psberkeleymba.workers.dev/mcp` · Streamable HTTP · no sign-in

## Tools

All tools are read-only (`readOnlyHint: true`). Nothing calls a search API, needs your keys, or stores anything.

| Tool | Returns |
|---|---|
| `get_overall_results` | Headline, overall scorecard, per-use-case summary, which API fits which agent, developer activation |
| `get_scorecard` | Full scorecard for `overall`, `gtm`, `insurance` or `finance` |
| `compare_providers` | Two or more providers side by side, optionally filtered by metric keyword |
| `recommend_provider` | Which API fits an agent's need, with supporting numbers |
| `list_questions` | The 30 questions, filterable by use case |
| `get_question` | One question: task, search call, answer key, sources, what each API returned and its score |
| `get_charts` | The published graphs; with `chart_id`, also the image |
| `get_methodology` | How tests ran and were graded, the 10 metrics and their standards, limits |
| `how_to_run_locally` | Steps and keys to rerun the benchmark on your own machine |
| `search`, `fetch` | Generic search and document fetch (used by ChatGPT research features) |

## Data and updates

The server reads `data/*.json` from the published site (cached for 5 minutes). Those files are built from the Evaluation page by [`data/build_data.py`](../data/build_data.py). After a new benchmark run, rebuild the data and push: the server picks it up with no redeploy. Every answer states the run date (currently Oct 8, 2026).

## Develop and deploy

```bash
cd mcp
npm install
npx wrangler dev      # local server at http://localhost:8787/mcp
npx @modelcontextprotocol/inspector@0.17.2   # connect to the local URL to call tools by hand
npx wrangler deploy   # deploy to Cloudflare Workers
```

Built with the official [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) (stateless Streamable HTTP transport) on Cloudflare Workers. Registry metadata is in [`server.json`](server.json).

## Privacy

No sign-in, no cookies, no storage. The server does not log request contents. Cloudflare may keep standard request logs for its platform.
