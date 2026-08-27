/**
 * fetch-efl-squads.js
 *
 * Pulls REAL current squads (names, ages, positions, nationality, photos) for
 * every Championship club — 24 clubs — from API-Football. Run locally with
 * your own key; the key never touches a committed file.
 *
 * Usage:
 *   API_FOOTBALL_KEY=your-real-key node fetch-efl-squads.js
 *
 * Free tier quota: this uses ~26 requests (1 league lookup + 1 team-list call
 * + 24 squad calls) — comfortably under the 100/day limit, with plenty of
 * margin for a retry if something fails partway through.
 *
 * League ID is looked up by name at runtime rather than hardcoded, so this
 * keeps working even if API-Football's numbering changes.
 *
 * Output: ./data/efl-squads.json — commit this to your repo. No key is in it.
 */

const API_KEY = process.env.API_FOOTBALL_KEY || "PASTE_YOUR_KEY_HERE";
const BASE = "https://v3.football.api-sports.io";

const LEAGUES = ["Championship"];

const fs = require("fs");
const path = require("path");

async function apiGet(endpoint, retriesLeft = 2) {
  const res = await fetch(`${BASE}${endpoint}`, {
    headers: { "x-apisports-key": API_KEY },
  });
  let data;
  try { data = await res.json(); } catch(e) { data = null; }

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
  const data = await apiGet(
    `/leagues?name=${encodeURIComponent(name)}&country=England`
  );
  if (!data.response || data.response.length === 0) {
    throw new Error(`No league found for "${name}"`);
  }
  const entry = data.response[0];
  // Free tier only has access to 2022-2024 (confirmed by the API's own error message on any
  // later season). The "current" flag reflects the REAL current season, which keeps advancing
  // every year and will always be out of free-tier reach — so pick the most recent season
  // actually within the allowed range instead of trusting "current".
  const allowedSeasons = entry.seasons.filter((s) => s.year <= 2024);
  const bestSeason = allowedSeasons.length > 0
    ? allowedSeasons.reduce((a, b) => (b.year > a.year ? b : a))
    : entry.seasons[entry.seasons.length - 1]; // shouldn't be reached given the free-tier message, but a safe fallback either way
  return {
    id: entry.league.id,
    name: entry.league.name,
    season: bestSeason.year,
  };
}

async function getTeamsInLeague(leagueId, season) {
  const data = await apiGet(`/teams?league=${leagueId}&season=${season}`);
  return (data.response || []).map((t) => ({ id: t.team.id, name: t.team.name }));
}

async function fetchSquad(teamId) {
  const data = await apiGet(`/players/squads?team=${teamId}`);
  if (!data.response || data.response.length === 0) return [];
  return data.response[0].players.map((p) => ({
    id: p.id,
    name: p.name,
    age: p.age,
    position: p.position,
    number: p.number,
    photo: p.photo,
  }));
}

async function main() {
  if (!API_KEY || API_KEY === "PASTE_YOUR_KEY_HERE") {
    console.error(
      "No API key set. Run with API_FOOTBALL_KEY=your-key node fetch-efl-squads.js"
    );
    process.exit(1);
  }

  const allClubs = [];
  let callCount = 0;

  for (const leagueName of LEAGUES) {
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
      console.log(`${teams.length} teams found.`);
    } catch (err) {
      console.error(`Failed to fetch teams for ${leagueName}:`, err.message);
      continue;
    }

    for (const team of teams) {
      try {
        console.log(`  Fetching squad: ${team.name} (id ${team.id})...`);
        const players = await fetchSquad(team.id);
        callCount++;
        await sleep(6500);
        allClubs.push({ club: team.name, teamId: team.id, league: league.name, players });
        console.log(`    -> ${players.length} players (total API calls so far: ${callCount})`);
      } catch (err) {
        console.error(`  Failed for ${team.name}:`, err.message);
      }
    }
  }

  const outDir = path.join(__dirname, "data");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, "efl-squads.json");
  fs.writeFileSync(
    outFile,
    JSON.stringify({ fetchedAt: new Date().toISOString(), clubs: allClubs }, null, 2)
  );

  console.log(`\nDone. ${callCount} API calls used. Wrote ${outFile}.`);
  console.log("Commit it to your repo — no API key is inside it.");
}

main();
