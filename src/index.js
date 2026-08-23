/**
 * recon-nlq-proxy — Cloudflare Worker
 *
 * This is the ONLY place your real Anthropic API key ever lives. The browser
 * (your deployed GitHub Pages app) sends the system prompt + the scout's query
 * to THIS worker; this worker attaches the key and calls Anthropic; the result
 * comes back to the browser. The key itself never touches the browser, never
 * touches your GitHub repo, never touches GitHub Pages' public files.
 *
 * Deploy this by pasting it into the Cloudflare dashboard's Worker editor —
 * see the deployment steps below the code. No terminal, no git, no local
 * install needed for this part.
 */

export default {
  async fetch(request, env) {
    // Handle the browser's CORS preflight check first.
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed — POST only.", { status: 405 });
    }

    let body;
    try {
      body = await request.json(); // expects { system: "...", userText: "..." }
    } catch (e) {
      return jsonResponse({ error: "Invalid JSON body" }, 400);
    }

    if (!body.system || !body.userText) {
      return jsonResponse({ error: "Request must include 'system' and 'userText'" }, 400);
    }

    try {
      const anthropicRes = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": env.ANTHROPIC_API_KEY, // set as a Worker secret — see deployment steps, never hardcoded here
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify({
          model: "claude-haiku-4-5-20251001", // fast + cheap — right fit for structured extraction, not complex reasoning
          max_tokens: 300,
          system: body.system,
          messages: [{ role: "user", content: body.userText }],
        }),
      });

      const data = await anthropicRes.json();
      return jsonResponse(data, anthropicRes.status);
    } catch (err) {
      return jsonResponse({ error: "Proxy failed to reach Anthropic: " + err.message }, 502);
    }
  },
};

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*", // fine for this low-sensitivity use case; tighten to your exact GitHub Pages URL later if you want it stricter
    },
  });
}