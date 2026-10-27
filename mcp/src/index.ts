/**
 * Web Search API Eval: hosted MCP server on Cloudflare Workers.
 *
 * Transport: Streamable HTTP at /mcp, stateless (a fresh server per request), JSON responses.
 * The tools live in server.ts and are shared with the npm package (cli.ts).
 */
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { buildServer, VERSION, SITE, REPO, type Env } from "./server";

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
Local, with live search on your own keys: npx -y websearch-api-eval-mcp

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
