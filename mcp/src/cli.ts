#!/usr/bin/env node
/**
 * Web Search API Eval: local MCP server for the npm package (`npx websearch-api-eval-mcp`).
 *
 * Runs on your own machine over stdio. It has every read-only tool from the hosted server, plus
 * run_live_search, which sends one query to You.com, Tavily, Exa and Parallel using the API keys
 * in your own environment (YDC_API_KEY, TAVILY_API_KEY, EXA_API_KEY, PARALLEL_API_KEY).
 * Keys never leave your machine except in the request to each provider.
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { buildServer, PROVIDERS, REPO, table, text } from "./server";

const DATA_BASE = process.env.WEBSEARCH_EVAL_DATA_BASE ?? "https://psinglap.github.io/websearch-api-eval/";

type Provider = (typeof PROVIDERS)[number];
type Hit = { title: string; url: string; date: string };

// Request shapes match the benchmark harness (eval/providers/*.py): search only, no page content.
const CALLS: Record<Provider, { key: string; run: (q: string, n: number, key: string) => Promise<Response>; parse: (j: any) => Hit[] }> = {
  "You.com": {
    key: "YDC_API_KEY",
    run: (q, n, key) =>
      fetch("https://ydc-index.io/v1/search", { method: "POST", headers: { "X-API-Key": key, "Content-Type": "application/json" }, body: JSON.stringify({ query: q, count: n }) }),
    parse: (j) => [...(j?.results?.web ?? []), ...(j?.results?.news ?? [])].map((r: any) => ({ title: r.title, url: r.url, date: r.page_age ?? "" })),
  },
  Tavily: {
    key: "TAVILY_API_KEY",
    run: (q, n, key) =>
      fetch("https://api.tavily.com/search", { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" }, body: JSON.stringify({ query: q, max_results: n, search_depth: "basic" }) }),
    parse: (j) => (j?.results ?? []).map((r: any) => ({ title: r.title, url: r.url, date: r.published_date ?? "" })),
  },
  Exa: {
    key: "EXA_API_KEY",
    run: (q, n, key) =>
      fetch("https://api.exa.ai/search", { method: "POST", headers: { "x-api-key": key, "Content-Type": "application/json" }, body: JSON.stringify({ query: q, type: "auto", numResults: n }) }),
    parse: (j) => (j?.results ?? []).map((r: any) => ({ title: r.title, url: r.url, date: r.publishedDate ?? "" })),
  },
  Parallel: {
    key: "PARALLEL_API_KEY",
    run: (q, n, key) =>
      fetch("https://api.parallel.ai/v1/search", { method: "POST", headers: { "x-api-key": key, "Content-Type": "application/json" }, body: JSON.stringify({ search_queries: [q], advanced_settings: { max_results: n } }) }),
    parse: (j) => (j?.results ?? []).map((r: any) => ({ title: r.title, url: r.url, date: r.publish_date ?? "" })),
  },
};

async function timed(p: Provider, query: string, n: number) {
  const key = process.env[CALLS[p].key];
  if (!key) return { provider: p, status: `skipped: set ${CALLS[p].key}`, ms: "", n: "", top: "" };
  const t0 = performance.now();
  try {
    const res = await CALLS[p].run(query, n, key);
    const ms = Math.round(performance.now() - t0);
    if (!res.ok) return { provider: p, status: `HTTP ${res.status}`, ms: String(ms), n: "0", top: "" };
    const hits = CALLS[p].parse(await res.json()).slice(0, n);
    const top = hits.slice(0, 3).map((h) => `${h.title ?? "(untitled)"}${h.date ? ` (${String(h.date).slice(0, 10)})` : ""} ${h.url}`).join("<br>");
    return { provider: p, status: hits.length ? "ok" : "empty", ms: String(ms), n: String(hits.length), top };
  } catch (e) {
    return { provider: p, status: `error: ${(e as Error).message}`, ms: String(Math.round(performance.now() - t0)), n: "0", top: "" };
  }
}

const server = buildServer({ DATA_BASE });

server.registerTool(
  "run_live_search",
  {
    title: "Run a live search test",
    description:
      "Send one query to You.com, Tavily, Exa and Parallel right now, using the API keys set in your own environment " +
      "(YDC_API_KEY, TAVILY_API_KEY, EXA_API_KEY, PARALLEL_API_KEY; providers without a key are skipped). Returns each " +
      "provider's client-side latency, result count and top results. Calls use your own provider credits.",
    inputSchema: {
      query: z.string().min(1).describe("The search query, e.g. one of the benchmark's search calls"),
      providers: z.array(z.enum(PROVIDERS)).optional().describe("Subset of You.com, Tavily, Exa, Parallel (default: all with a key)"),
      max_results: z.number().int().min(1).max(10).default(5).describe("Results per provider (1-10)"),
    },
    annotations: { title: "Run a live search test", readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  },
  async ({ query, providers, max_results }) => {
    const list = (providers?.length ? providers : [...PROVIDERS]) as Provider[];
    // One provider at a time, so the latency of one call isn't skewed by the others.
    const rows = [];
    for (const p of list) rows.push(await timed(p, query, max_results));
    return text(
      `## Live search: "${query}"\n\n${table(rows, ["provider", "status", "ms", "n", "top"], ["Provider", "Status", "Latency (ms, client)", "Results", "Top results"])}\n\n` +
        `_One live call per provider from your machine, ${new Date().toISOString()}. A single call is a spot check, not a benchmark: ` +
        `for graded results across 30 queries see get_overall_results, or rerun the full harness (${REPO})._`,
    );
  },
);

await server.connect(new StdioServerTransport());
