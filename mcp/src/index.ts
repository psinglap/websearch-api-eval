/**
 * Web Search API Eval: read-only MCP server.
 *
 * Serves the published benchmark (You.com, Tavily, Exa, Parallel; 30 agent queries; run 2026-10-08)
 * to Claude, ChatGPT and other MCP clients. Nothing here calls a search API or stores anything:
 * every tool reads the data/*.json files published on the GitHub Pages site.
 *
 * Transport: Streamable HTTP at /mcp, stateless (a fresh server per request), JSON responses.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { CfWorkerJsonSchemaValidator } from "@modelcontextprotocol/sdk/validation/cfworker";
import { z } from "zod";

interface Env {
  DATA_BASE: string;
}

const VERSION = "1.0.0";
const SITE = "https://psinglap.github.io/websearch-api-eval/";
const REPO = "https://github.com/psinglap/websearch-api-eval";
const PROVIDERS = ["You.com", "Tavily", "Exa", "Parallel"] as const;
const USE_CASES = ["gtm", "insurance", "finance"] as const;
const UC_NAMES: Record<string, string> = { gtm: "GTM agent", insurance: "Insurance agent", finance: "Finance agent" };

// Every tool only reads published data, so clients can skip approval prompts.
const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

// ---------- data loading (cached for 5 minutes per Worker instance and at Cloudflare's edge) ----------

type Json = any;
const cache = new Map<string, { at: number; data: Json }>();
const TTL_MS = 5 * 60 * 1000;

async function load(env: Env, name: string): Promise<Json> {
  const hit = cache.get(name);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.data;
  const res = await fetch(new URL(`data/${name}.json`, env.DATA_BASE), { cf: { cacheTtl: 300, cacheEverything: true } } as RequestInit);
  if (!res.ok) throw new Error(`Could not load ${name}.json (HTTP ${res.status})`);
  const data = await res.json();
  cache.set(name, { at: Date.now(), data });
  return data;
}

// ---------- formatting helpers ----------

function table(rows: Record<string, string>[], cols: string[], labels?: string[]): string {
  const head = `| ${(labels ?? cols).join(" | ")} |\n|${cols.map(() => "---").join("|")}|`;
  const body = rows.map((r) => `| ${cols.map((c) => String(r[c] ?? "").replace(/\|/g, "/")).join(" | ")} |`).join("\n");
  return `${head}\n${body}`;
}

function footer(asOf: string): string {
  return `\n\n_Published benchmark snapshot, run ${asOf} (not live data). Full results: ${SITE} · Run it yourself: ${REPO}_`;
}

function text(s: string) {
  return { content: [{ type: "text" as const, text: s }] };
}

function scoreLabel(v: number | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  return `${v.toFixed(2)} / 2`;
}

// ---------- server ----------

function buildServer(env: Env): McpServer {
  const server = new McpServer(
    { name: "websearch-api-eval", title: "Web Search API Eval", version: VERSION, websiteUrl: SITE },
    {
      jsonSchemaValidator: new CfWorkerJsonSchemaValidator(),
      instructions:
        "Published benchmark of four web search APIs for AI agents (You.com, Tavily, Exa, Parallel): 30 agent-style queries " +
        "across GTM, insurance and finance, 3 runs each, run on 2026-10-08. Use get_overall_results for the headline and overall " +
        "scorecard, get_scorecard or compare_providers for numbers, recommend_provider for 'which API should I use', get_question " +
        "for a specific query, get_charts for the published graphs, get_methodology for how it was measured, and how_to_run_locally " +
        "to rerun it. Results are a fixed snapshot; always mention the run date and link the site.",
    },
  );

  server.registerTool(
    "get_overall_results",
    {
      title: "Overall results",
      description:
        "Headline findings and the overall scorecard across all 30 queries (90 calls per API): accuracy, fully correct, precision@5, " +
        "freshness, empty responses, failed calls, latency p50/p95, cost per correct answer. Also the per-use-case summary, which API fits " +
        "which agent, and developer activation time. Use this first for any general question about the benchmark.",
      annotations: { ...READ_ONLY, title: "Overall results" },
    },
    async () => {
      const r = await load(env, "results");
      const out = [
        `## Web Search API Eval: overall results\n\n${r.headline}`,
        `### Overall scorecard (${r.overall.basis})\n\n${table(r.overall.metrics, ["metric", ...PROVIDERS], ["Metric", ...PROVIDERS])}\n\nChart: ${r.overall.chart}`,
        `### By use case (${r.by_use_case_summary.basis})\n\n${table(r.by_use_case_summary.rows, ["use_case", "agent_job", ...PROVIDERS], ["Use case", "Agent job", ...PROVIDERS])}`,
        `### Which API fits which agent\n\n${table(r.which_api_for_which_agent, ["if_your_agent", "pick", "why"], ["If your agent…", "Pick", "Why"])}`,
        `### Developer activation (${r.developer_activation.basis})\n\n${table(r.developer_activation.metrics, ["metric", "Tavily", "You.com", "Parallel", "Exa"], ["", "Tavily", "You.com", "Parallel", "Exa"])}`,
      ];
      return text(out.join("\n\n") + footer(r.as_of));
    },
  );

  server.registerTool(
    "get_scorecard",
    {
      title: "Scorecard",
      description:
        "Full metric scorecard for one use case (gtm, insurance, finance) or 'overall'. Metrics: search-only latency p50/p95 (server and client), " +
        "calls under 1 s, accuracy, freshness (% in window, newest relevant result age), content in one call, tokens, search cost.",
      inputSchema: { use_case: z.enum(["overall", ...USE_CASES]).describe("overall, gtm, insurance or finance") },
      annotations: { ...READ_ONLY, title: "Scorecard" },
    },
    async ({ use_case }) => {
      const r = await load(env, "results");
      if (use_case === "overall") {
        return text(`## Overall scorecard (${r.overall.basis})\n\n${table(r.overall.metrics, ["metric", ...PROVIDERS], ["Metric", ...PROVIDERS])}\n\nChart: ${r.overall.chart}` + footer(r.as_of));
      }
      const s = r.scorecards[use_case];
      return text(
        `## ${s.use_case} scorecard\n\nAgent job: ${s.agent_job}\n\n${table(s.metrics, ["metric", ...PROVIDERS], ["Metric", ...PROVIDERS])}\n\nChart: ${SITE}img/${use_case}_key_metrics.png` +
          footer(r.as_of),
      );
    },
  );

  server.registerTool(
    "compare_providers",
    {
      title: "Compare providers",
      description:
        "Compare two or more of You.com, Tavily, Exa and Parallel side by side, overall or within one use case, optionally filtered to metrics " +
        "whose name contains a keyword (e.g. 'latency', 'accuracy', 'fresh', 'cost', 'empty').",
      inputSchema: {
        providers: z.array(z.enum(PROVIDERS)).min(2).describe("Two or more of: You.com, Tavily, Exa, Parallel"),
        use_case: z.enum(["overall", ...USE_CASES]).default("overall").describe("overall, gtm, insurance or finance"),
        metric_filter: z.string().optional().describe("Optional keyword to keep only matching metrics"),
      },
      annotations: { ...READ_ONLY, title: "Compare providers" },
    },
    async ({ providers, use_case, metric_filter }) => {
      const r = await load(env, "results");
      let rows: Record<string, string>[] = use_case === "overall" ? r.overall.metrics : r.scorecards[use_case].metrics;
      if (metric_filter) {
        const k = metric_filter.toLowerCase();
        const kept = rows.filter((m) => m.metric.toLowerCase().includes(k));
        if (kept.length) rows = kept;
      }
      const title = use_case === "overall" ? "Overall" : UC_NAMES[use_case];
      return text(`## ${providers.join(" vs ")}: ${title}\n\n${table(rows, ["metric", ...providers], ["Metric", ...providers])}` + footer(r.as_of));
    },
  );

  server.registerTool(
    "recommend_provider",
    {
      title: "Recommend a provider",
      description:
        "Which web search API fits an agent, based on this benchmark: live voice/chat turns, deep research, semantic or long-tail queries, " +
        "docs lookups, or a specific use case (GTM, insurance, finance). Returns the guidance with the supporting numbers.",
      inputSchema: {
        agent_need: z.string().optional().describe("What the agent does, e.g. 'voice agent answering in under a second' or 'finance research'"),
      },
      annotations: { ...READ_ONLY, title: "Recommend a provider" },
    },
    async ({ agent_need }) => {
      const r = await load(env, "results");
      const need = (agent_need ?? "").toLowerCase();
      const words = need.split(/\W+/).filter((w) => w.length > 3);
      const scored = r.which_api_for_which_agent
        .map((p: Record<string, string>) => ({ p, hits: words.filter((w) => (p.if_your_agent + " " + p.why).toLowerCase().includes(w)).length }))
        .sort((a: { hits: number }, b: { hits: number }) => b.hits - a.hits);
      const best = need && scored[0].hits > 0 ? scored[0].p : null;
      const uc = USE_CASES.find((u) => need.includes(u) || (u === "gtm" && /sales|signal|prospect|developer/.test(need)));
      const parts = [
        best ? `## Best fit for "${agent_need}": ${best.pick}\n\n${best.why}.` : "## Which web search API fits which agent",
        table(r.which_api_for_which_agent, ["if_your_agent", "pick", "why"], ["If your agent…", "Pick", "Why"]),
        `### Supporting numbers (overall, ${r.overall.basis})\n\n${table(
          r.overall.metrics.filter((m: Record<string, string>) => /accuracy|window|empty|latency p50 \/ p95|cost/i.test(m.metric)),
          ["metric", ...PROVIDERS],
          ["Metric", ...PROVIDERS],
        )}`,
      ];
      if (uc) {
        const s = r.scorecards[uc];
        parts.push(`### ${s.use_case}\n\n${table(s.metrics.slice(0, 5), ["metric", ...PROVIDERS], ["Metric", ...PROVIDERS])}`);
      }
      parts.push("Test with your own queries before deciding: see how_to_run_locally.");
      return text(parts.join("\n\n") + footer(r.as_of));
    },
  );

  server.registerTool(
    "list_questions",
    {
      title: "List questions",
      description: "The 30 benchmark questions (G1-G10 GTM, I1-I10 insurance, F1-F10 finance): ID, what the agent is asked, the search call and freshness.",
      inputSchema: { use_case: z.enum(["all", ...USE_CASES]).default("all").describe("all, gtm, insurance or finance") },
      annotations: { ...READ_ONLY, title: "List questions" },
    },
    async ({ use_case }) => {
      const q = await load(env, "questions");
      const rows = q.questions
        .filter((x: Json) => use_case === "all" || x.use_case === use_case)
        .map((x: Json) => ({ ...x, uc: UC_NAMES[x.use_case] }));
      return text(
        `## Benchmark questions (${rows.length})\n\n${table(rows, ["id", "uc", "task", "search_call", "parameters", "freshness"], ["ID", "Use case", "Task", "Search call", "Parameters", "Freshness"])}\n\nUse get_question with an ID for the answer key and what each API returned.` +
          footer(q.as_of),
      );
    },
  );

  server.registerTool(
    "get_question",
    {
      title: "Get a question",
      description: "One benchmark question by ID (e.g. G3, I4, F5): the task, search call, parameters, answer key with sources, and what each API returned with its accuracy score (0-2, mean of 3 runs).",
      inputSchema: { id: z.string().describe("Question ID, e.g. G3, I4 or F5") },
      annotations: { ...READ_ONLY, title: "Get a question" },
    },
    async ({ id }) => {
      const q = await load(env, "questions");
      const x = q.questions.find((y: Json) => y.id.toLowerCase() === id.trim().toLowerCase());
      if (!x) return { ...text(`No question "${id}". IDs are G1-G10, I1-I10 and F1-F10.`), isError: true };
      const res = PROVIDERS.map((p) => ({ provider: p, returned: x.results[p]?.returned ?? "", score: scoreLabel(x.results[p]?.accuracy_0_2) }));
      const src = [...x.answer_key_links, ...x.sources].map((l: Json) => `- ${l.text}: ${l.url}`).join("\n");
      return text(
        `## ${x.id} (${UC_NAMES[x.use_case]})\n\n**Task:** ${x.task}\n**Search call:** \`${x.search_call}\`\n**Parameters:** ${x.parameters}\n**Needs back:** ${x.needs_back}\n**Freshness:** ${x.freshness}\n\n**Answer key:** ${x.answer_key}\n\n${src ? `**Sources:**\n${src}\n\n` : ""}### What each API returned\n\n${table(res, ["provider", "returned", "score"], ["API", "Returned", "Accuracy (mean of 3 runs)"])}` +
          footer(q.as_of),
      );
    },
  );

  server.registerTool(
    "get_charts",
    {
      title: "Charts",
      description:
        "The published graphs: overall scorecard, key metrics and per-query grids for GTM, insurance and finance, and developer activation. " +
        "Without chart_id, lists them with titles and image links. With chart_id, also returns the image itself.",
      inputSchema: {
        chart_id: z.string().optional().describe("e.g. overall_scorecard, finance_key_metrics, gtm_query_grid, time_steps_activation"),
        use_case: z.enum(["all", "gtm", "insurance", "finance", "setup"]).default("all").describe("Filter the list"),
      },
      annotations: { ...READ_ONLY, title: "Charts" },
    },
    async ({ chart_id, use_case }) => {
      const c = await load(env, "charts");
      const list = c.charts.filter((x: Json) => use_case === "all" || x.use_case === use_case || x.use_case === "all");
      if (!chart_id) {
        const lines = list.map((x: Json) => `- **${x.title}** (\`${x.id}\`): ${x.caption} ${x.image_url}`).join("\n");
        return text(`## Published charts\n\n${lines}\n\nCall get_charts with a chart_id to get the image.` + footer(c.as_of));
      }
      const ch = c.charts.find((x: Json) => x.id === chart_id.trim());
      if (!ch) return { ...text(`No chart "${chart_id}". Available: ${c.charts.map((x: Json) => x.id).join(", ")}`), isError: true };
      const img = await fetch(ch.image_url, { cf: { cacheTtl: 3600, cacheEverything: true } } as RequestInit);
      const content: Json[] = [{ type: "text", text: `## ${ch.title}\n\n${ch.caption}\n\nImage: ${ch.image_url}` + footer(c.as_of) }];
      if (img.ok) {
        const bytes = new Uint8Array(await img.arrayBuffer());
        let bin = "";
        for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        content.push({ type: "image", data: btoa(bin), mimeType: "image/png" });
      }
      return { content };
    },
  );

  server.registerTool(
    "get_methodology",
    {
      title: "Methodology",
      description: "How the benchmark was run and graded: query design, identical request parameters, 3 runs per query, latency timing, SimpleQA and FreshQA grading, the 10 metrics and the standards they follow, and limits.",
      annotations: { ...READ_ONLY, title: "Methodology" },
    },
    async () => {
      const m = await load(env, "methodology");
      const files = Object.entries(m.files).map(([k, v]) => `- ${k.replace(/_/g, " ")}: ${v}`).join("\n");
      return text(
        `## Methodology\n\n${m.summary}\n\n### Metrics\n\n${table(m.metrics, ["n", "metric", "how_measured", "standard"], ["#", "Metric", "How measured", "Standard"])}\n\n${m.statistics}\n\n### Limits\n\n${m.limits.map((l: string) => `- ${l}`).join("\n")}\n\n### Files\n\n${files}` +
          footer(m.as_of),
      );
    },
  );

  server.registerTool(
    "how_to_run_locally",
    {
      title: "Run it yourself",
      description: "How to rerun this benchmark on your own machine with your own API keys, including on your own queries. Nothing runs on this server.",
      annotations: { ...READ_ONLY, title: "Run it yourself" },
    },
    async () => {
      const r = await load(env, "run_locally");
      return text(
        `## Run the benchmark yourself\n\n${r.summary}\n\n\`\`\`bash\n${r.steps.join("\n")}\n\`\`\`\n\n**API keys you need (in eval/.env):**\n${r.keys_needed.map((k: string) => `- ${k}`).join("\n")}\n\n**Use your own queries:** ${r.use_your_own_queries}\n\nFull guide: ${r.docs}` +
          footer(r.as_of),
      );
    },
  );

  // ChatGPT research features look for generic `search` and `fetch` tools that return JSON.
  server.registerTool(
    "search",
    {
      title: "Search the benchmark",
      description: "Search the Web Search API Eval benchmark (results, questions, methodology, charts, how to run). Returns matching document IDs to pass to fetch.",
      inputSchema: { query: z.string().describe("What to look for") },
      annotations: { ...READ_ONLY, title: "Search the benchmark" },
    },
    async ({ query }) => {
      const docs = await allDocs(env);
      const words = query.toLowerCase().split(/\W+/).filter((w) => w.length > 1);
      const results = docs
        .map((d) => ({ d, score: words.reduce((s, w) => s + (d.title.toLowerCase().includes(w) ? 3 : 0) + (d.text.toLowerCase().includes(w) ? 1 : 0), 0) }))
        .filter((x) => x.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 10)
        .map(({ d }) => ({ id: d.id, title: d.title, url: d.url }));
      return text(JSON.stringify({ results }));
    },
  );

  server.registerTool(
    "fetch",
    {
      title: "Fetch a benchmark document",
      description: "Fetch the full text of a document returned by search, by its ID.",
      inputSchema: { id: z.string().describe("Document ID from search") },
      annotations: { ...READ_ONLY, title: "Fetch a benchmark document" },
    },
    async ({ id }) => {
      const doc = (await allDocs(env)).find((d) => d.id === id);
      if (!doc) return { ...text(JSON.stringify({ error: `Unknown id ${id}` })), isError: true };
      return text(JSON.stringify({ id: doc.id, title: doc.title, text: doc.text, url: doc.url, metadata: { as_of: doc.as_of } }));
    },
  );

  return server;
}

// Documents used by the generic search/fetch tools.
async function allDocs(env: Env): Promise<{ id: string; title: string; text: string; url: string; as_of: string }[]> {
  const [r, q, m, c, run] = await Promise.all(["results", "questions", "methodology", "charts", "run_locally"].map((n) => load(env, n)));
  const docs = [
    { id: "overall", title: "Overall results and headline", text: `${r.headline}\n\n${table(r.overall.metrics, ["metric", ...PROVIDERS])}\n\n${table(r.which_api_for_which_agent, ["if_your_agent", "pick", "why"])}`, url: SITE },
    ...USE_CASES.map((u) => ({ id: `scorecard-${u}`, title: `${UC_NAMES[u]} scorecard`, text: `${r.scorecards[u].agent_job}\n\n${table(r.scorecards[u].metrics, ["metric", ...PROVIDERS])}`, url: SITE })),
    ...q.questions.map((x: Json) => ({
      id: `question-${x.id}`,
      title: `${x.id}: ${x.task}`,
      text: `Search call: ${x.search_call}\nParameters: ${x.parameters}\nAnswer key: ${x.answer_key}\n` + PROVIDERS.map((p) => `${p}: ${x.results[p]?.returned} (score ${scoreLabel(x.results[p]?.accuracy_0_2)})`).join("\n"),
      url: SITE,
    })),
    { id: "methodology", title: "Methodology and metrics", text: `${m.summary}\n\n${table(m.metrics, ["metric", "how_measured", "standard"])}`, url: SITE },
    { id: "charts", title: "Published charts", text: c.charts.map((x: Json) => `${x.title}: ${x.caption} ${x.image_url}`).join("\n"), url: SITE },
    { id: "run-locally", title: "How to run the benchmark yourself", text: `${run.summary}\n${run.steps.join("\n")}\nKeys: ${run.keys_needed.join(", ")}`, url: REPO },
  ];
  return docs.map((d) => ({ ...d, as_of: r.as_of }));
}

// ---------- HTTP entry point ----------

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, Authorization, Mcp-Session-Id, Mcp-Protocol-Version, Last-Event-ID",
  "Access-Control-Expose-Headers": "Mcp-Session-Id, Mcp-Protocol-Version",
};

function withCors(res: Response): Response {
  const h = new Headers(res.headers);
  for (const [k, v] of Object.entries(CORS)) h.set(k, v);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

const LANDING = `Web Search API Eval: MCP server (read-only, v${VERSION})

Published benchmark of You.com, Tavily, Exa and Parallel on 30 agent queries.
MCP endpoint: <this host>/mcp  (Streamable HTTP, no sign-in)

Claude: Settings > Connectors > Add custom connector > paste the /mcp URL
ChatGPT: Developer mode > Create app > paste the /mcp URL, no authentication
Claude Code: claude mcp add --transport http websearch-api-eval <this host>/mcp

Results: ${SITE}
Code and run-it-yourself: ${REPO}
Privacy: no sign-in, no cookies, nothing stored; requests are not logged by this server.
`;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    if (url.pathname === "/" || url.pathname === "") {
      return withCors(new Response(LANDING.replaceAll("<this host>", url.origin), { headers: { "Content-Type": "text/plain; charset=utf-8" } }));
    }

    if (url.pathname === "/mcp") {
      if (request.method !== "POST") {
        // Stateless server: no server-initiated stream and no sessions to delete.
        return withCors(new Response(JSON.stringify({ jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed" }, id: null }), {
          status: 405,
          headers: { "Content-Type": "application/json", Allow: "POST, OPTIONS" },
        }));
      }
      const server = buildServer(env);
      const transport = new WebStandardStreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
      await server.connect(transport);
      const res = await transport.handleRequest(request);
      return withCors(res);
    }

    return withCors(new Response("Not found. The MCP endpoint is /mcp", { status: 404 }));
  },
};
