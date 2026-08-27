/**
 * fetch-lowerleague-team-stats.js
 *
 * Real team-season stats (2022-2024) for League One and League Two — but only
 * for Recon's already-configured clubs (same restriction and reasoning as
 * fetch-lowerleague-squads.js).
 *
 * Unlike cache-team-stats.py, this doesn't need a hardcoded TEAM_ID/LEAGUE_ID
 * edited in by hand — both are looked up dynamically by name at runtime, the
 * same safe pattern fetch-efl-squads.js already uses. A wrong hand-typed ID
 * silently returns empty or wrong data with no obvious error; a name lookup
 * either finds the real thing or fails loudly and says so.
 *
 * Usage:
 *   API_FOOTBALL_KEY=your-real-key node fetch-lowerleague-team-stats.js
 *
 * Same caching behavior as cache-team-stats.py: a team/season already fetched
 * costs zero API calls on a re-run. Delete the specific file in
 * ./data/team-stats/ if you want to force a refresh.
 *
 * Fetches ALL THREE allowed seasons (2022, 2023, 2024) per club automatically —
 * no need to hand-edit a season constant and re-run three times.
 *
 * Quota: up to ~26 requests total on a completely fresh run (2 league lookups
 * + 8 team searches + up to 24 stats calls, 3 seasons × 8 clubs) — comfortably
 * under the 100/day limit. Re-runs cost far less since already-cached
 * team/season combinations are skipped.
 */

const API_KEY = process.env.API_FOOTBALL_KEY || "PASTE_YOUR_KEY_HERE";
const BASE = "https://v3.football.api-sports.io";
const SEASONS = [2022, 2023, 2024]; // every season the free tier actually allows, fetched in one run instead of three manual edits

// Must match GEN_CLUBS_BY_LEAGUE exactly, in recon-mobile.html.
const TARGET_CLUBS = {
  "League One": ["Wrexham", "Bolton Wanderers", "Barnsley", "Peterborough United"],
  "League Two": ["Crewe Alexandra", "Notts County", "Walsall", "Doncaster Rovers"],
};

const fs = require("fs");
const path = require("path");
const OUT_DIR = path.join(__dirname, "data", "team-stats");

function cachePath(teamId, season) {
  return path.join(OUT_DIR, `${teamId}_${season}.json`);
}

async function apiGet(endpoint, retriesLeft = 2) {
  const res = await fetch(`${BASE}${endpoint}`, {
    headers: { "x-apisports-key": API_KEY },
  });
  let data;
  try { data = await res.json(); } catch (e) { data = null; }

  if (res.status === 429 && retriesLeft > 0) {
    console.log(`  Rate limited — waiting 20s before retrying (${retriesLeft} retr${retriesLeft===1?'y':'ies'} left)...`);
    await sleep(20000);
    return apiGet(endpoint, retriesLeft - 1);
  }

  if (!res.ok) {
    throw new Error(`${endpoint} -> HTTP ${res.status} ${res.statusText}\n${JSON.stringify(data)}`);
  }
  if (data && data.errors && Object.keys(data.errors).length > 0) {
    throw new Error(`${endpoint} -> API-Football returned an error: ${JSON.stringify(data.errors)}`);
  }
  return data;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function findLeague(name) {
  const data = await apiGet(`/leagues?name=${encodeURIComponent(name)}&country=England`);
  if (!data.response || data.response.length === 0) {
    throw new Error(`No league found for "${name}"`);
  }
  const entry = data.response[0];
  // Free tier only has access to 2022-2024 — same fix as fetch-lowerleague-squads.js.
  const allowedSeasons = entry.seasons.filter((s) => s.year <= 2024);
  const bestSeason = allowedSeasons.length > 0
    ? allowedSeasons.reduce((a, b) => (b.year > a.year ? b : a))
    : entry.seasons[entry.seasons.length - 1];
  return { id: entry.league.id, name: entry.league.name, season: bestSeason.year };
}

// Searches by name rather than trusting a hardcoded ID — takes the exact
// match if one exists, otherwise the first result (same fallback fetch-
// player-stats.js already uses for its own team lookups).
async function findTeamId(name) {
  const data = await apiGet(`/teams?search=${encodeURIComponent(name)}`);
  if (!data.response || data.response.length === 0) throw new Error(`No team found for "${name}"`);
  const exact = data.response.find((r) => r.team.name.toLowerCase() === name.toLowerCase());
  return (exact || data.response[0]).team;
}

async function fetchTeamStats(teamId, leagueId, season) {
  const data = await apiGet(`/teams/statistics?team=${teamId}&season=${season}&league=${leagueId}`);
  return data;
}

async function main() {
  if (!API_KEY || API_KEY === "PASTE_YOUR_KEY_HERE") {
    console.error("No API key set. Run with API_FOOTBALL_KEY=your-key node fetch-lowerleague-team-stats.js");
    process.exit(1);
  }

  fs.mkdirSync(OUT_DIR, { recursive: true });
  let callCount = 0;

  // The app resolves club -> teamId through this shared index (used by both Championship and
  // now these lower-league clubs). Load the existing one so Championship's entries aren't lost.
  const indexPath = path.join(OUT_DIR, "index.json");
  let index = {};
  if (fs.existsSync(indexPath)) {
    try { index = JSON.parse(fs.readFileSync(indexPath, "utf8")); }
    catch (e) { console.error("Warning: existing index.json couldn't be parsed, starting fresh — check it wasn't corrupted:", e.message); }
  }

  for (const [leagueName, clubNames] of Object.entries(TARGET_CLUBS)) {
    console.log(`\n=== ${leagueName} ===`);
    let league;
    try {
      league = await findLeague(leagueName);
      callCount++;
      await sleep(6500);
      console.log(`Found: ${league.name} (id ${league.id})`);
    } catch (err) {
      console.error(`Failed to find league "${leagueName}":`, err.message);
      continue;
    }

    for (const clubName of clubNames) {
      let team;
      try {
        team = await findTeamId(clubName);
        callCount++;
        await sleep(6500);
      } catch (err) {
        console.error(`  Failed to find team "${clubName}":`, err.message);
        continue;
      }

      index[clubName] = team.id; // merged in regardless of whether stats were already cached, so the index stays accurate even on a re-run

      for (const season of SEASONS) {
        const outPath = cachePath(team.id, season);
        if (fs.existsSync(outPath)) {
          console.log(`  ${clubName} ${season} (id ${team.id}): already cached, no API call made.`);
          continue;
        }

        try {
          console.log(`  Fetching stats: ${clubName} ${season} (matched "${team.name}", id ${team.id})...`);
          const stats = await fetchTeamStats(team.id, league.id, season);
          callCount++;
          await sleep(6500);
          stats._cachedAt = new Date().toISOString();
          fs.writeFileSync(outPath, JSON.stringify(stats, null, 2));
          console.log(`    -> wrote ${outPath} (total API calls so far: ${callCount})`);
        } catch (err) {
          console.error(`  Failed to fetch stats for ${clubName} ${season}:`, err.message);
        }
      }
    }
  }

  fs.writeFileSync(indexPath, JSON.stringify(index, null, 2));
  console.log(`\nUpdated ${indexPath} with ${Object.keys(index).length} total clubs.`);
  console.log(`Done. ${callCount} API calls used this run. Commit any new/changed files in ./data/team-stats/ — no key is inside them.`);
}

main();
