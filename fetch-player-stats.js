/**
 * fetch-player-stats.js
 *
 * Pulls REAL season stats (appearances, rating, goals, assists, pass accuracy,
 * tackles, duels won, dribbles, cards, shots, fouls, penalties) for real
 * players — 5 NEW players per run. Run it again later and it automatically
 * picks up where it left off, skipping anyone already fetched.
 *
 * Draws candidates from BOTH data/efl-squads.json (Championship) and
 * data/lowerleague-squads.json (League One/Two) — whichever of the two
 * exist. Run fetch-efl-squads.js and/or fetch-lowerleague-squads.js first;
 * no club list to maintain here for either league.
 *
 * Usage:
 *   API_FOOTBALL_KEY=your-real-key node fetch-player-stats.js
 *
 * Quota per run: just 5 stats calls (one per new player, drawn from whichever
 * leagues have squad data available), plus one-time lookups if using the
 * FALLBACK_CLUBS live-lookup path. Free tier is 100/day, so you have huge
 * headroom to run this repeatedly.
 *
 * Output: ./data/player-stats.json — a growing list, 5 longer each run.
 * Commit it to your repo after each run. No API key is ever inside it.
 */

const API_KEY = process.env.API_FOOTBALL_KEY || "PASTE_YOUR_KEY_HERE";
const BASE = "https://v3.football.api-sports.io";
const BATCH_SIZE = 5;

// Only used as a fallback for clubs NOT already in data/efl-squads.json (rare, once
// you've run fetch-efl-squads.js — that file covers all 24 Championship clubs already).
const FALLBACK_CLUBS = ["Preston North End", "Leeds United"];

const fs = require("fs");
const path = require("path");
const outFile = path.join(__dirname, "data", "player-stats.json");
const squadsFile = path.join(__dirname, "data", "efl-squads.json");
const lowerLeagueSquadsFile = path.join(__dirname, "data", "lowerleague-squads.json"); // League One/Two — see fetch-lowerleague-squads.js

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
 * Builds the candidate list from BOTH squads files — Championship (efl-squads.json)
 * and League One/Two (lowerleague-squads.json) — merged into one pool, whichever of
 * the two actually exist. No club list to maintain here for either; running either
 * fetch-efl-squads.js or fetch-lowerleague-squads.js (or both) is all that's needed
 * for this script to see those players as candidates. Only falls back to a live API
 * lookup for FALLBACK_CLUBS if NEITHER file exists yet.
 */
function readSquadsFile(filePath, label){
  if (!fs.existsSync(filePath)) return [];
  const squadsData = JSON.parse(fs.readFileSync(filePath, "utf8"));
  const fromFile = [];
  (squadsData.clubs || []).forEach((c) => {
    (c.players || []).forEach((p) => {
      if (p.id) fromFile.push({ id: p.id, name: p.name, club: c.club, league: c.league || label });
    });
  });
  console.log(`Loaded ${fromFile.length} candidates across ${(squadsData.clubs||[]).length} clubs from ${label} (zero API calls needed for this step).`);
  return fromFile;
}

async function buildCandidates() {
  const championship = readSquadsFile(squadsFile, "efl-squads.json (Championship)");
  const lowerLeague = readSquadsFile(lowerLeagueSquadsFile, "lowerleague-squads.json (League One/Two)");
  const combined = championship.concat(lowerLeague);

  if (combined.length > 0) return combined;

  console.log("Neither efl-squads.json nor lowerleague-squads.json found yet — falling back to a live lookup for FALLBACK_CLUBS. Run fetch-efl-squads.js and/or fetch-lowerleague-squads.js first for full coverage instead.");
  const fromApi = [];
  for (const clubName of FALLBACK_CLUBS) {
    try {
      console.log(`Fetching squad for "${clubName}" directly...`);
      const team = await findTeamId(clubName);
      await sleep(6500);
      const squad = await getSquad(team.id, team.name);
      await sleep(6500);
      fromApi.push(...squad);
      console.log(`  ${team.name}: ${squad.length} players`);
    } catch (err) {
      console.error(`  Failed for ${clubName}:`, err.message);
    }
  }
  return fromApi;
}

async function getSeasonStats(playerId, season) {
  const data = await apiGet(`/players?id=${playerId}&season=${season}`);
  if (!data.response || data.response.length === 0) return null;
  const entry = data.response[0];
  const stat = (entry.statistics || [])[0];
  if (!stat) return null;

  const shotsTotal = stat.shots ? stat.shots.total : null;
  const shotsOn = stat.shots ? stat.shots.on : null;
  const foulsDrawn = stat.fouls ? stat.fouls.drawn : null;
  const foulsCommitted = stat.fouls ? stat.fouls.committed : null;
  const goals = stat.goals ? stat.goals.total : null;
  const tackles = stat.tackles ? stat.tackles.total : null;
  const interceptions = stat.tackles ? stat.tackles.interceptions : null;

  return {
    name: entry.player.name,
    photo: entry.player.photo,
    team: stat.team ? stat.team.name : null,
    appearances: stat.games ? stat.games.appearences : null,
    rating: stat.games ? stat.games.rating : null,
    goals,
    assists: stat.goals ? stat.goals.assists : null,
    passesTotal: stat.passes ? stat.passes.total : null,
    passAccuracy: stat.passes ? stat.passes.accuracy : null,
    keyPasses: stat.passes ? stat.passes.key : null, // was available in the same response all along, just never captured
    tackles,
    interceptions,
    duelsTotal: stat.duels ? stat.duels.total : null,
    duelsWon: stat.duels ? stat.duels.won : null,
    dribblesAttempts: stat.dribbles ? stat.dribbles.attempts : null,
    dribblesSuccess: stat.dribbles ? stat.dribbles.success : null,
    yellowCards: stat.cards ? stat.cards.yellow : null,
    redCards: stat.cards ? stat.cards.red : null,
    // New raw fields — genuinely free, since they arrive in this exact response already,
    // just weren't being read before.
    shotsTotal, shotsOn, foulsDrawn, foulsCommitted,
    penaltyScored: stat.penalty ? stat.penalty.scored : null,
    penaltyMissed: stat.penalty ? stat.penalty.missed : null,
    // Derived metrics — computed here from the raw fields above, stored alongside them so
    // the app doesn't need to recompute from scratch. Each guards against null/zero
    // denominators rather than producing NaN or Infinity in the output file.
    shotConversionRate: (goals != null && shotsTotal) ? Math.round((goals / shotsTotal) * 1000) / 1000 : null,
    shotAccuracy: (shotsOn != null && shotsTotal) ? Math.round((shotsOn / shotsTotal) * 1000) / 1000 : null,
    disciplineRatio: (foulsCommitted != null && (tackles || interceptions)) ? Math.round((foulsCommitted / ((tackles||0)+(interceptions||0))) * 1000) / 1000 : null,
  };
}

const SEASONS = [2022, 2023, 2024]; // every season the free tier allows — matches fetch-lowerleague-team-stats.js's approach, no calendar-guessing needed since this list is fixed and explicit

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
  const byId = new Map(existing.players.map((p) => [p.id, p]));

  console.log("Building candidate list...");
  const candidates = await buildCandidates();

  if (candidates.length === 0) {
    console.log(
      "\nFound ZERO candidates across your configured clubs — this is not the same as " +
      "'everyone already has stats'. Likely causes:\n" +
      "  - A club name in CLUBS doesn't exactly match what the API (or efl-squads.json) uses\n" +
      "  - The squad fetch for that club failed (check for a 'Failed for ...' line above)\n" +
      "  - efl-squads.json/lowerleague-squads.json exists but uses different club name spelling\n" +
      "Nothing was fetched. Check the log above this message for the actual cause."
    );
    return;
  }

  // A candidate still needs work if any of the three seasons hasn't been ATTEMPTED yet —
  // present-but-null (a season genuinely had no data, e.g. too young to have played) still
  // counts as done, so it's never retried forever burning quota for nothing new.
  const needsWork = candidates.filter((c) => {
    const entry = byId.get(c.id);
    if (!entry || !entry.seasons) return true;
    return SEASONS.some((s) => !(s in entry.seasons));
  });
  const batch = needsWork.slice(0, BATCH_SIZE);

  if (batch.length === 0) {
    console.log(
      `\nFound ${candidates.length} candidate(s), and all of them already have every season ` +
      `(${SEASONS.join("/")}) either fetched or confirmed empty — you've genuinely covered ` +
      `everyone available right now.`
    );
    return;
  }

  console.log(`\nFetching real season stats for ${batch.length} player(s), up to ${SEASONS.length} seasons each:`);
  let callCount = 0;
  for (const player of batch) {
    const entry = byId.get(player.id) || { id: player.id, club: player.club, league: player.league, seasons: {} };
    console.log(`  ${player.name} (${player.club}):`);

    for (const season of SEASONS) {
      if (season in entry.seasons) {
        console.log(`    ${season}: already fetched (or confirmed empty) — no API call made.`);
        continue;
      }
      try {
        const stats = await getSeasonStats(player.id, season);
        callCount++;
        await sleep(6500);
        entry.seasons[season] = stats; // null is a valid, final result here — recorded so it's never retried
        if (stats) {
          entry.name = stats.name; // identity fields kept fresh from whichever season last returned data
          entry.photo = stats.photo;
          console.log(`    ${season}: got stats.`);
        } else {
          console.log(`    ${season}: no data returned (may not have played that season, or thin lower-league coverage) — recorded as empty, won't retry.`);
        }
      } catch (err) {
        // Genuine failure (network/API error) — do NOT record the season key, so this is
        // retried next run rather than permanently treated as "confirmed empty".
        console.error(`    ${season}: failed —`, err.message);
      }
    }

    byId.set(player.id, entry);
  }

  existing.players = Array.from(byId.values());
  existing.fetchedAt = new Date().toISOString();
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(existing, null, 2));

  const stillNeedingWork = needsWork.length - batch.length;
  console.log(`\nWrote ${outFile} — ${existing.players.length} players total now. ${callCount} API calls used this run.`);
  console.log(`${stillNeedingWork} more player(s) still need at least one season fetched — run again for the next ${BATCH_SIZE}.`);
  console.log("Commit the file to your repo — no API key is inside it.");
}

main();
