"""
cache-team-stats.py

Fetch and cache REAL season stats (fixtures, wins/draws/losses, goals, form)
across ALL your Championship clubs — by NAME, no need to hunt down team IDs
yourself. Processes a SAFE BATCH of new clubs per run (not all at once — with
22 clubs, doing them all in one run could approach the 100/day free-tier
limit), so run it a few times to cover everyone, same "run it again for the
next batch" pattern as fetch-player-stats.js.

Also maintains data/team-stats/index.json — a simple {club name: team id} map
that recon-mobile.html reads automatically, so adding a club here is the ONLY
step needed; there's no second place in the app to hand-edit.

Usage:
    python cache-team-stats.py YOUR_REAL_KEY

    (Key goes on the command line, not hardcoded in the file — same reason as
    your other scripts: this file is safe to commit, your key never is.)

Output:
    ./data/team-stats/{team_id}_{season}.json — one file per club per season
    ./data/team-stats/index.json             — {club name: team id}, read by the app

NOTE: Rangers and PSV Eindhoven are deliberately NOT in this list — they don't
play in the Championship (LEAGUE_ID=40 below), so this specific script can't
fetch stats for them. Same honest gap as the openfootball/football-data.org
sources — those two clubs just aren't covered by any English-league-scoped
free source used in this app.

NOTE: API-Football's free plan only allows seasons 2022-2024, not the current
season — confirmed by testing. SEASONS below reflects that.
"""

import json
import os
import sys
import time

import requests

BASE = "https://v3.football.api-sports.io"

# All real Championship clubs currently in the app's illustrative pool.
# Rangers and PSV excluded on purpose — see note above.
CLUBS = [
    "Preston North End", "Leeds United", "Crewe Alexandra", "Sunderland",
    "Middlesbrough", "Norwich City", "Sheffield United", "West Bromwich Albion",
    "Coventry City", "Bristol City", "Watford", "Hull City", "Millwall",
    "Swansea City", "Cardiff City", "Stoke City", "Blackburn Rovers",
    "Derby County", "Luton Town", "Oxford United", "Sheffield Wednesday",
    "Portsmouth",
]
LEAGUE_ID = 40  # Championship
SEASONS = [2022, 2023, 2024]  # the only seasons the free plan actually allows
BATCH_SIZE_NEW_CLUBS = 5  # how many NOT-yet-fully-cached clubs to process per run
REQUEST_DELAY = 6.5  # seconds between calls — free tier is rate-limited per minute, not just per day

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "team-stats")
INDEX_PATH = os.path.join(OUT_DIR, "index.json")


def load_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_index(index):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def api_get(endpoint, api_key, params, retries=2):
    for attempt in range(retries + 1):
        res = requests.get(f"{BASE}{endpoint}", headers={"x-apisports-key": api_key}, params=params, timeout=30)
        try:
            data = res.json()
        except Exception:
            data = None

        if res.status_code == 429 and attempt < retries:
            wait = 20 * (attempt + 1)
            print(f"    Rate limited — waiting {wait}s before retrying...")
            time.sleep(wait)
            continue

        if res.status_code != 200:
            raise RuntimeError(f"HTTP {res.status_code} — {data if data else res.text[:200]}")
        if data and data.get("errors") and len(data["errors"]) > 0:
            raise RuntimeError(f"API-Football error: {data['errors']}")
        return data
    raise RuntimeError("Still rate-limited after retries — try again in a minute or two.")


_league_teams_cache = None

def load_league_teams(api_key, league_id, season):
    """Fetch the REAL list of teams in a league/season once — this is the fix for the
    reserves/U21/women's-team mismatch: only genuine first-team Championship clubs can
    ever be matched this way, unlike a raw name search which returns every similarly
    named team regardless of level."""
    global _league_teams_cache
    if _league_teams_cache is not None:
        return _league_teams_cache
    data = api_get("/teams", api_key, {"league": league_id, "season": season})
    _league_teams_cache = data.get("response", [])
    time.sleep(REQUEST_DELAY)
    return _league_teams_cache


def find_team_id(api_key, club_name):
    teams = load_league_teams(api_key, LEAGUE_ID, SEASONS[-1])
    if not teams:
        raise RuntimeError("Could not load the Championship team list at all")
    exact = next((t for t in teams if t["team"]["name"].lower() == club_name.lower()), None)
    if exact:
        return exact["team"]["id"], exact["team"]["name"]
    # loose fallback: club_name is a substring of the real team name or vice versa
    loose = next((t for t in teams
                  if club_name.lower() in t["team"]["name"].lower()
                  or t["team"]["name"].lower() in club_name.lower()), None)
    if loose:
        return loose["team"]["id"], loose["team"]["name"]
    raise RuntimeError(f'"{club_name}" not found in the real Championship team list for season {SEASONS[-1]} — check spelling, or this club may not be in the Championship that season')


def cache_path(team_id, season):
    return os.path.join(OUT_DIR, f"{team_id}_{season}.json")


def fetch_season(api_key, team_id, season):
    path = cache_path(team_id, season)
    if os.path.exists(path):
        print(f"    Season {season}: already cached. No API call made.")
        return

    print(f"    Season {season}: not cached — calling the API...")
    data = api_get("/teams/statistics", api_key, {"team": team_id, "season": season, "league": LEAGUE_ID})
    data["_cachedAt"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"    Season {season}: fetched and cached.")
    time.sleep(REQUEST_DELAY)


def club_fully_cached(index, club_name):
    if club_name not in index:
        return False
    team_id = index[club_name]
    return all(os.path.exists(cache_path(team_id, s)) for s in SEASONS)


def main():
    if len(sys.argv) < 2:
        print("Usage: python cache-team-stats.py YOUR_REAL_KEY")
        sys.exit(1)
    api_key = sys.argv[1]

    index = load_index()

    already_done = [c for c in CLUBS if club_fully_cached(index, c)]
    still_needed = [c for c in CLUBS if not club_fully_cached(index, c)]

    print(f"{len(already_done)} of {len(CLUBS)} clubs already fully cached (all {len(SEASONS)} seasons).")
    if not still_needed:
        print("Everyone in CLUBS is fully cached — nothing to do. Add more clubs to CLUBS to continue.")
        return

    batch = still_needed[:BATCH_SIZE_NEW_CLUBS]
    print(f"Processing {len(batch)} club(s) this run: {', '.join(batch)}")

    for club_name in batch:
        print(f"\n=== {club_name} ===")
        if club_name in index:
            team_id = index[club_name]
            print(f"  Team ID already known: {team_id} (no lookup call needed)")
        else:
            try:
                team_id, official_name = find_team_id(api_key, club_name)
                print(f"  Found: {official_name} (id {team_id})")
                index[club_name] = team_id
                save_index(index)  # save immediately so a later failure doesn't lose this lookup
            except Exception as err:
                print(f"  Failed to find team ID: {err}")
                continue

        for season in SEASONS:
            try:
                fetch_season(api_key, team_id, season)
            except Exception as err:
                print(f"    Season {season}: failed — {err}")

    remaining = len(still_needed) - len(batch)
    print(f"\nDone this run. {remaining} more club(s) left — run again for the next batch." if remaining
          else "\nDone — that was the last batch, all clubs in CLUBS are now fully cached.")
    print("Commit data/team-stats/ (including index.json) — no API key is in any of it.")
    print("The app reads index.json automatically — no need to edit recon-mobile.html for new clubs.")


if __name__ == "__main__":
    main()
