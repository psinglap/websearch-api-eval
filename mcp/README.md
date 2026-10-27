# Web Search API Eval: MCP server

An [MCP](https://modelcontextprotocol.io) server that lets Claude, ChatGPT, Cursor and other AI assistants answer questions about the [Web Search API Eval](https://psinglap.github.io/websearch-api-eval/) benchmark (You.com, Tavily, Exa and Parallel on 30 agent queries), and run your own live search spot checks.

Use it two ways:

| | Hosted (no install) | Local (npm) |
|---|---|---|
| Connect | `https://websearch-api-eval.psberkeleymba.workers.dev/mcp` | `npx -y websearch-api-eval-mcp` |
| Works in | Claude, ChatGPT, any remote MCP client | Claude Desktop, Claude Code, Cursor, VS Code, any stdio MCP client |
| Benchmark tools | ✅ | ✅ |
| `run_live_search` with your own keys | — | ✅ |

## Install

**Claude Code**

```bash
claude mcp add websearch-api-eval -- npx -y websearch-api-eval-mcp
```

**Claude Desktop, Cursor, VS Code** (add to the client's MCP config):

```json
{
  "mcpServers": {
    "websearch-api-eval": {
      "command": "npx",
      "args": ["-y", "websearch-api-eval-mcp"],
      "env": {
        "YDC_API_KEY": "optional",
        "TAVILY_API_KEY": "optional",
        "EXA_API_KEY": "optional",
        "PARALLEL_API_KEY": "optional"
      }
    }
  }
}
```

The keys are optional and only used by `run_live_search`. Leave out any provider you don't have a key for. Requires Node.js 18 or later.

**Hosted, no install:** in Claude, Settings → Connectors → Add custom connector → paste the hosted URL. In ChatGPT, create an app in Developer mode with the same URL and no authentication.

## Tools

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
| `how_to_run_locally` | Steps and keys to rerun the full benchmark on your own machine |
| `search`, `fetch` | Generic search and document fetch (used by ChatGPT research features) |
| `run_live_search` (local only) | Sends one query to each provider using your own API keys and returns latency, result count and top results |

The benchmark tools are read-only and read the published results (run Oct 8, 2026). `run_live_search` calls the providers directly from your machine with your keys and uses your own credits; a single call is a spot check, not a graded benchmark. For the full graded run, use the [harness](https://github.com/psinglap/websearch-api-eval/tree/main/eval).

## Example questions

- "Which web search API is fastest for a voice agent?"
- "Compare Exa and Parallel on finance."
- "What was question F5 and who got it right?"
- "Show me the overall scorecard chart."
- "Run a live search for 'FOMC minutes' and compare the providers."

## Data and updates

Results come from `data/*.json` on the published site, built from the Evaluation page by [`data/build_data.py`](https://github.com/psinglap/websearch-api-eval/blob/main/data/build_data.py). After a new benchmark run, rebuild the data and push; both the hosted and npm servers pick it up with no redeploy or new release.

## Develop

```bash
cd mcp
npm install
npx wrangler dev        # hosted server locally at http://localhost:8787/mcp
npm run build           # npm package entry at dist/cli.js
npx @modelcontextprotocol/inspector@0.17.2 node dist/cli.js   # call tools by hand
npx wrangler deploy     # deploy the hosted server
npm publish             # publish the npm package
```

Built with the official [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk). Registry entry: `io.github.psinglap/websearch-api-eval` ([`server.json`](https://github.com/psinglap/websearch-api-eval/blob/main/mcp/server.json)).

## Privacy and support

No sign-in, no cookies, no storage, no request logging. [Privacy Policy](https://psinglap.github.io/websearch-api-eval/privacy/) · [Terms](https://psinglap.github.io/websearch-api-eval/terms/) · [Support](https://psinglap.github.io/websearch-api-eval/support/) · MIT License
