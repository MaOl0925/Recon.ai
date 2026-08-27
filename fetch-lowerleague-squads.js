/**
 * fetch-lowerleague-squads.js
 *
 * Pulls REAL current squads (names, ages, positions, photos) for League One
 * and League Two — but ONLY for the specific clubs already configured in
 * Recon's illustrative pool (GEN_CLUBS_BY_LEAGUE in recon-mobile.html), not
 * every club in either league.
 *
 * Why restricted rather than all 24 clubs per league: Recon's CLUB_LEAGUE
 * mapping only recognizes these specific club names as belonging to "League
 * One"/"League Two". Fetching every real club in the league would pull in
 * players whose club Recon has never heard of — they'd never surface in a
 * league-filtered search, so fetching them would just burn quota for nothing
 * usable. This keeps real data aligned with what the app can actually do
 * with it, and keeps quota usage small (8 squad calls total, not 40+).
 *
 * Usage:
 *   API_FOOTBALL_KEY=your-real-key node fetch-lowerleague-squads.js
 *
 * Free tier quota: ~10 requests (2 league lookups + 8 squad calls) — small
 * fraction of the 100/day limit, even combined with Championship's ~26.
 *
 * Output: ./data/lowerleague-squads.json — commit this to your repo.
 */

const API_KEY = process.env.API_FOOTBALL_KEY || "PASTE_YOUR_KEY_HERE";
const BASE = "https://v3.football.api-sports.io";

// Must match GEN_CLUBS_BY_LEAGUE exactly, in recon-mobile.html, so real and
// illustrative data agree on which clubs exist in each league.
const TARGET_CLUBS = {
  "League One": ["Wrexham", "Bolton Wanderers", "Barnsley", "Peterborough United"],
  "League Two": ["Crewe Alexandra", "Notts County", "Walsall", "Doncaster Rovers"],
};

const fs = require("fs");
const path = require("path");

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

// Same dynamic-lookup pattern as fetch-efl-squads.js — league ID is found by
// name at runtime, never hardcoded, so this keeps working even if
// API-Football's internal numbering ever changes.
async function findLeague(name) {
  const data = await apiGet(`/leagues?name=${encodeURIComponent(name)}&country=England`);
  if (!data.response || data.response.length === 0) {
    throw new Error(`No league found for "${name}" — double-check the exact name API-Football uses (try the /leagues Live Tester in your dashboard if this fails).`);
  }
  const entry = data.response[0];
  // Free tier only has access to 2022-2024 — "current" keeps advancing every real year and
  // will always be out of reach, so pick the most recent allowed season explicitly instead.
  const allowedSeasons = entry.seasons.filter((s) => s.year <= 2024);
  const bestSeason = allowedSeasons.length > 0
    ? allowedSeasons.reduce((a, b) => (b.year > a.year ? b : a))
    : entry.seasons[entry.seasons.length - 1];
  return { id: entry.league.id, name: entry.league.name, season: bestSeason.year };
}

async function getTeamsInLeague(leagueId, season) {
  const data = await apiGet(`/teams?league=${leagueId}&season=${season}`);
  return (data.response || []).map((t) => ({ id: t.team.id, name: t.team.name }));
}

async function fetchSquad(teamId) {
  const data = await apiGet(`/players/squads?team=${teamId}`);
  if (!data.response || data.response.length === 0) return [];
  return data.response[0].players.map((p) => ({
    id: p.id, name: p.name, age: p.age, position: p.position, number: p.number, photo: p.photo,
  }));
}

// Fuzzy-ish name match so "Bolton Wanderers" in our config still matches if
// the API returns it as "Bolton" or similar — case-insensitive substring
// check in both directions.
function findTargetMatch(apiTeams, targetName) {
  const lower = targetName.toLowerCase();
  return apiTeams.find((t) => {
    const tLower = t.name.toLowerCase();
    return tLower === lower || tLower.includes(lower) || lower.includes(tLower);
  });
}

async function main() {
  if (!API_KEY || API_KEY === "PASTE_YOUR_KEY_HERE") {
    console.error("No API key set. Run with API_FOOTBALL_KEY=your-key node fetch-lowerleague-squads.js");
    process.exit(1);
  }

  const allClubs = [];
  let callCount = 0;

  for (const [leagueName, targetClubNames] of Object.entries(TARGET_CLUBS)) {
    console.log(`\n=== ${leagueName} ===`);
    let league;
    try {
      league = await findLeague(leagueName);
      callCount++;
      await sleep(6500);
      console.log(`Found: ${league.name} (id ${league.id}, season ${league.season})`);
    } catch (err) {
      console.error(`Failed to find league "${leagueName}":`, err.message);
      continue;
    }

    let teams;
    try {
      teams = await getTeamsInLeague(league.id, league.season);
      callCount++;
      await sleep(6500);
      console.log(`${teams.length} total teams in league — filtering to our ${targetClubNames.length} configured clubs.`);
    } catch (err) {
      console.error(`Failed to fetch teams for ${leagueName}:`, err.message);
      continue;
    }

    for (const targetName of targetClubNames) {
      const match = findTargetMatch(teams, targetName);
      if (!match) {
        console.error(`  Could not find "${targetName}" in ${leagueName}'s team list — check spelling matches API-Football's naming exactly, or that this club is actually in this league this season (promotion/relegation can move it).`);
        continue;
      }
      try {
        console.log(`  Fetching squad: ${targetName} (matched "${match.name}", id ${match.id})...`);
        const players = await fetchSquad(match.id);
        callCount++;
        await sleep(6500);
        allClubs.push({ club: targetName, apiMatchedName: match.name, teamId: match.id, league: league.name, players });
        console.log(`    -> ${players.length} players (total API calls so far: ${callCount})`);
      } catch (err) {
        console.error(`  Failed for ${targetName}:`, err.message);
      }
    }
  }

  const outDir = path.join(__dirname, "data");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, "lowerleague-squads.json");
  fs.writeFileSync(outFile, JSON.stringify({ fetchedAt: new Date().toISOString(), clubs: allClubs }, null, 2));

  console.log(`\nDone. ${callCount} API calls used. Wrote ${outFile}.`);
  console.log("Commit it to your repo — no API key is inside it.");
}

main();
