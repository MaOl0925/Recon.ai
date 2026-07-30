/**
 * fetch-player-stats.js
 *
 * Pulls REAL season stats (appearances, rating, goals, assists, pass accuracy,
 * tackles, duels won, dribbles, cards) for real players at your chosen clubs —
 * but only 5 NEW players per run. Run it again later and it automatically picks
 * up where it left off, skipping anyone already fetched.
 *
 * Usage:
 *   API_FOOTBALL_KEY=your-real-key node fetch-player-stats.js
 *
 * Quota per run: 1 call per club (to get the squad + real player IDs) + up to
 * 5 calls (one per new player's stats) = usually well under 10 requests total,
 * however many clubs you list below. Free tier is 100/day, so you have huge
 * headroom to run this many times.
 *
 * Output: ./data/player-stats.json — a growing list, 5 longer each run.
 * Commit it to your repo after each run. No API key is ever inside it.
 */

const API_KEY = process.env.API_FOOTBALL_KEY || "PASTE_YOUR_KEY_HERE";
const BASE = "https://v3.football.api-sports.io";
const BATCH_SIZE = 5;

// Edit this list to whichever real clubs you want players pulled from.
const CLUBS = ["Preston North End", "Leeds United"];

const fs = require("fs");
const path = require("path");
const outFile = path.join(__dirname, "data", "player-stats.json");
const squadsFile = path.join(__dirname, "data", "efl-squads.json");

async function apiGet(endpoint) {
  const res = await fetch(`${BASE}${endpoint}`, {
    headers: { "x-apisports-key": API_KEY },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${endpoint} -> ${res.status} ${res.statusText}\n${body}`);
  }
  return res.json();
}
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function findTeamId(name) {
  const data = await apiGet(`/teams?search=${encodeURIComponent(name)}`);
  if (!data.response || data.response.length === 0) throw new Error(`No team for "${name}"`);
  const exact = data.response.find((r) => r.team.name.toLowerCase() === name.toLowerCase());
  return (exact || data.response[0]).team;
}

async function getSquad(teamId, clubName) {
  const data = await apiGet(`/players/squads?team=${teamId}`);
  if (!data.response || data.response.length === 0) return [];
  return data.response[0].players.map((p) => ({ id: p.id, name: p.name, club: clubName }));
}

/**
 * Builds the candidate list. Prefers reading data/efl-squads.json — which already has
 * player IDs, no extra API calls needed — and only calls the API to re-fetch squads for
 * any configured club that isn't in that file yet (or if the file doesn't exist at all).
 */
async function buildCandidates() {
  let fromFile = [];
  let coveredClubs = new Set();

  if (fs.existsSync(squadsFile)) {
    const squadsData = JSON.parse(fs.readFileSync(squadsFile, "utf8"));
    (squadsData.clubs || []).forEach((c) => {
      if (CLUBS.some((wanted) => wanted.toLowerCase() === c.club.toLowerCase())) {
        coveredClubs.add(c.club.toLowerCase());
        (c.players || []).forEach((p) => {
          if (p.id) fromFile.push({ id: p.id, name: p.name, club: c.club });
        });
      }
    });
    if (fromFile.length > 0) {
      console.log(`Loaded ${fromFile.length} candidates from data/efl-squads.json (no API calls needed for these clubs).`);
    }
  }

  const missingClubs = CLUBS.filter((c) => !coveredClubs.has(c.toLowerCase()));
  const fromApi = [];
  for (const clubName of missingClubs) {
    try {
      console.log(`"${clubName}" not found in efl-squads.json — fetching squad directly...`);
      const team = await findTeamId(clubName);
      await sleep(1300);
      const squad = await getSquad(team.id, team.name);
      await sleep(1300);
      fromApi.push(...squad);
      console.log(`  ${team.name}: ${squad.length} players`);
    } catch (err) {
      console.error(`  Failed for ${clubName}:`, err.message);
    }
  }

  return [...fromFile, ...fromApi];
}

async function getSeasonStats(playerId, season) {
  const data = await apiGet(`/players?id=${playerId}&season=${season}`);
  if (!data.response || data.response.length === 0) return null;
  const entry = data.response[0];
  const stat = (entry.statistics || [])[0];
  if (!stat) return null;
  return {
    name: entry.player.name,
    photo: entry.player.photo,
    team: stat.team ? stat.team.name : null,
    appearances: stat.games ? stat.games.appearences : null,
    rating: stat.games ? stat.games.rating : null,
    goals: stat.goals ? stat.goals.total : null,
    assists: stat.goals ? stat.goals.assists : null,
    passesTotal: stat.passes ? stat.passes.total : null,
    passAccuracy: stat.passes ? stat.passes.accuracy : null,
    tackles: stat.tackles ? stat.tackles.total : null,
    interceptions: stat.tackles ? stat.tackles.interceptions : null,
    duelsTotal: stat.duels ? stat.duels.total : null,
    duelsWon: stat.duels ? stat.duels.won : null,
    dribblesAttempts: stat.dribbles ? stat.dribbles.attempts : null,
    dribblesSuccess: stat.dribbles ? stat.dribbles.success : null,
    yellowCards: stat.cards ? stat.cards.yellow : null,
    redCards: stat.cards ? stat.cards.red : null,
  };
}

function currentSeasonGuess() {
  // English domestic season spans Aug-May; API-Football labels a season by its start year.
  const now = new Date();
  const y = now.getFullYear();
  return now.getMonth() >= 6 ? y : y - 1; // from July onward, assume the new season's start year
}

async function main() {
  if (!API_KEY || API_KEY === "PASTE_YOUR_KEY_HERE") {
    console.error("No API key set. Run with API_FOOTBALL_KEY=your-key node fetch-player-stats.js");
    process.exit(1);
  }

  let existing = { fetchedAt: null, players: [] };
  if (fs.existsSync(outFile)) {
    existing = JSON.parse(fs.readFileSync(outFile, "utf8"));
    console.log(`Found existing file with ${existing.players.length} players already fetched.`);
  }
  const alreadyFetchedIds = new Set(existing.players.map((p) => p.id));

  console.log("Building candidate list...");
  const candidates = await buildCandidates();

  const notYetFetched = candidates.filter((c) => !alreadyFetchedIds.has(c.id));
  const batch = notYetFetched.slice(0, BATCH_SIZE);

  if (batch.length === 0) {
    console.log("\nEveryone in your configured clubs already has stats fetched. Add more clubs to CLUBS to continue.");
    return;
  }

  console.log(`\nFetching real season stats for ${batch.length} new player(s):`);
  const season = currentSeasonGuess();
  for (const player of batch) {
    try {
      console.log(`  ${player.name} (${player.club})...`);
      const stats = await getSeasonStats(player.id, season);
      await sleep(1300);
      if (stats) {
        existing.players.push({ id: player.id, club: player.club, ...stats });
        console.log(`    -> got stats (season ${season})`);
      } else {
        console.log(`    -> no stats returned for season ${season} (may not have played, or thin lower-league coverage)`);
      }
    } catch (err) {
      console.error(`    Failed:`, err.message);
    }
  }

  existing.fetchedAt = new Date().toISOString();
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(existing, null, 2));

  console.log(`\nWrote ${outFile} — ${existing.players.length} players total now.`);
  console.log(`${notYetFetched.length - batch.length} more available in your configured clubs — run again for the next ${BATCH_SIZE}.`);
  console.log("Commit the file to your repo — no API key is inside it.");
}

main();
