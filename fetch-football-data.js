/**
 * fetch-football-data.js
 *
 * Run this LOCALLY, once (or whenever you want fresh data), with your own
 * football-data.org API key. It writes plain JSON files you commit to the
 * repo — the key itself never goes into any committed file or into the
 * deployed site, so there's nothing for a public GitHub Pages viewer to find.
 *
 * Usage:
 *   1. node --version   (needs Node 18+ for built-in fetch; if older, see note below)
 *   2. FOOTBALL_DATA_KEY=your-real-key node fetch-football-data.js
 *      (or paste your key into API_KEY below — just don't commit it)
 *   3. Commit the resulting files in ./data/ to your repo alongside recon-mobile.html
 *   4. The app reads them as plain static JSON at runtime — no key involved at that point.
 */

const API_KEY = process.env.FOOTBALL_DATA_KEY || "6acfa44e969d4ee4809651d4b9542c4d" ;
const BASE = "https://api.football-data.org/v4";

// Championship (Leeds, Preston) and Eredivisie (PSV). Add more codes if needed,
// e.g. "PL" (Premier League), "DED" (Eredivisie) — see /competitions for the full list.
const COMPETITIONS = [
  { code: "ELC", name: "championship" }, // English Championship
  { code: "DED", name: "eredivisie" },   // Dutch Eredivisie
];

const fs = require("fs");
const path = require("path");

async function apiGet(endpoint) {
  const res = await fetch(`${BASE}${endpoint}`, {
    headers: { "X-Auth-Token": API_KEY },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${endpoint} -> ${res.status} ${res.statusText}\n${body}`);
  }
  return res.json();
}

// football-data.org free tier allows 10 requests/minute — space calls out safely.
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchCompetition(comp) {
  console.log(`Fetching ${comp.name} (${comp.code})...`);

  const standings = await apiGet(`/competitions/${comp.code}/standings`);
  await sleep(6500); // stay comfortably under 10 req/min

  const matches = await apiGet(`/competitions/${comp.code}/matches?status=FINISHED`);
  await sleep(6500);

  const scorers = await apiGet(`/competitions/${comp.code}/scorers?limit=20`);
  await sleep(6500);

  return {
    competition: comp.name,
    code: comp.code,
    fetchedAt: new Date().toISOString(),
    standings,
    matches,
    scorers,
  };
}

async function main() {
  if (!API_KEY || API_KEY === "PASTE_YOUR_KEY_HERE") {
    console.error(
      "No API key set. Run with FOOTBALL_DATA_KEY=your-key node fetch-football-data.js\n" +
      "or edit API_KEY at the top of this file (then don't commit your key)."
    );
    process.exit(1);
  }

  const outDir = path.join(__dirname, "data");
  fs.mkdirSync(outDir, { recursive: true });

  for (const comp of COMPETITIONS) {
    try {
      const data = await fetchCompetition(comp);
      const outFile = path.join(outDir, `football-data-${comp.code.toLowerCase()}.json`);
      fs.writeFileSync(outFile, JSON.stringify(data, null, 2));
      console.log(`Wrote ${outFile}`);
    } catch (err) {
      console.error(`Failed to fetch ${comp.name}:`, err.message);
    }
  }

  console.log("\nDone. Commit the files in ./data/ to your repo — no API key is in them.");
}

main();
