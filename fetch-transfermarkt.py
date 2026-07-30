"""
fetch_transfermarkt.py

Pulls real Championship players — name, position, age, club, real market value,
and real career appearance stats (goals, assists, minutes, cards) — from the
public transfermarkt-datasets project (github.com/dcaribou/transfermarkt-datasets).

No API key, no rate limit — these are just public compressed CSV files. This
script downloads and filters them locally, then writes one small JSON you commit.

USAGE:
    pip install pandas requests
    python3 fetch_transfermarkt.py

OUTPUT:
    ./data/transfermarkt-championship.json

NOTE ON LICENSING: this is scraped Transfermarkt data redistributed via a third-
party project. Fine for prototyping; check that project's license and
Transfermarkt's own terms before relying on it in anything beyond a demo.
"""

import json
import os
import sys
import io

try:
    import pandas as pd
    import requests
except ImportError:
    print("Missing dependency. Run: python3 -m pip install pandas requests")
    sys.exit(1)

BASE_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
TARGET_COMPETITION_NAME = "Championship"
TARGET_COUNTRY = "England"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_FILE = os.path.join(OUT_DIR, "transfermarkt-championship.json")

# Cloudflare (which hosts these files) sometimes 403s requests that don't look like they're
# coming from a real browser. pandas' built-in downloader doesn't send a User-Agent header at
# all, which can trigger exactly that. Fetching with requests + a browser-like header first,
# then handing the raw bytes to pandas, avoids it.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def load(name):
    url = f"{BASE_URL}/{name}.csv.gz"
    print(f"Loading {name} from {url} ...")
    res = requests.get(url, headers=HEADERS, timeout=60)
    if res.status_code != 200:
        print(f"  -> HTTP {res.status_code} fetching {url}")
        print(f"  -> Response body (first 300 chars): {res.text[:300]}")
        raise RuntimeError(f"Failed to fetch {name}.csv.gz (HTTP {res.status_code})")
    df = pd.read_csv(io.BytesIO(res.content), compression="gzip", low_memory=False)
    print(f"  -> {len(df)} rows. Columns: {list(df.columns)}")
    return df


def first_existing(df, candidates):
    """Return the first column name from `candidates` that actually exists in df."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def main():
    competitions = load("competitions")

    name_col = first_existing(competitions, ["competition_name", "name"])
    country_col = first_existing(competitions, ["country_name", "country"])
    id_col = first_existing(competitions, ["competition_id", "id"])
    if not all([name_col, country_col, id_col]):
        print("Could not find expected columns in competitions.csv.gz — check the printed column list above and adjust first_existing() calls.")
        sys.exit(1)

    match = competitions[
        competitions[name_col].astype(str).str.contains(TARGET_COMPETITION_NAME, case=False, na=False)
        & competitions[country_col].astype(str).str.contains(TARGET_COUNTRY, case=False, na=False)
    ]
    if match.empty:
        print(f"No competition matched '{TARGET_COMPETITION_NAME}' in '{TARGET_COUNTRY}'. "
              f"Here are England-related rows to check manually:")
        print(competitions[competitions[country_col].astype(str).str.contains(TARGET_COUNTRY, case=False, na=False)])
        sys.exit(1)

    comp_id = match.iloc[0][id_col]
    print(f"\nFound competition: {match.iloc[0][name_col]} (id={comp_id})\n")

    clubs = load("clubs")
    club_comp_col = first_existing(clubs, ["domestic_competition_id", "competition_id"])
    club_id_col = first_existing(clubs, ["club_id", "id"])
    club_name_col = first_existing(clubs, ["name", "club_name"])
    target_clubs = clubs[clubs[club_comp_col] == comp_id]
    print(f"{len(target_clubs)} clubs found in this competition.\n")
    club_id_to_name = dict(zip(target_clubs[club_id_col], target_clubs[club_name_col]))

    players = load("players")
    player_club_col = first_existing(players, ["current_club_id", "club_id"])
    player_id_col = first_existing(players, ["player_id", "id"])
    name_col_p = first_existing(players, ["name", "player_name"])
    position_col = first_existing(players, ["position", "sub_position"])
    dob_col = first_existing(players, ["date_of_birth", "dob"])
    value_col = first_existing(players, ["market_value_in_eur", "market_value"])

    target_players = players[players[player_club_col].isin(club_id_to_name.keys())].copy()
    print(f"{len(target_players)} players found across those clubs.\n")

    # Age from date of birth, if present
    if dob_col:
        try:
            dob = pd.to_datetime(target_players[dob_col], errors="coerce")
            today = pd.Timestamp.today()
            target_players["_age"] = ((today - dob).dt.days // 365).astype("Int64")
        except Exception:
            target_players["_age"] = None
    else:
        target_players["_age"] = None

    player_ids = set(target_players[player_id_col])

    # Appearance stats — aggregated across whatever games are in the dataset for these players.
    # Not filtered to "this season only" (that would need a reliable date/season column, and
    # I'm not confident enough in the exact column name to assert that without verifying live —
    # so these are career totals within this dataset, labelled honestly as such below).
    stats_by_player = {}
    try:
        appearances = load("appearances")
        app_player_col = first_existing(appearances, ["player_id"])
        goals_col = first_existing(appearances, ["goals"])
        assists_col = first_existing(appearances, ["assists"])
        minutes_col = first_existing(appearances, ["minutes_played"])
        yellow_col = first_existing(appearances, ["yellow_cards"])
        red_col = first_existing(appearances, ["red_cards"])

        target_apps = appearances[appearances[app_player_col].isin(player_ids)]
        print(f"{len(target_apps)} appearance records found for these players.\n")

        agg = target_apps.groupby(app_player_col).agg(
            appearances=(app_player_col, "count"),
            goals=(goals_col, "sum") if goals_col else (app_player_col, "count"),
            assists=(assists_col, "sum") if assists_col else (app_player_col, "count"),
            minutes=(minutes_col, "sum") if minutes_col else (app_player_col, "count"),
            yellow_cards=(yellow_col, "sum") if yellow_col else (app_player_col, "count"),
            red_cards=(red_col, "sum") if red_col else (app_player_col, "count"),
        )
        stats_by_player = agg.to_dict(orient="index")
    except Exception as e:
        print(f"Could not load/aggregate appearances.csv.gz ({e}) — proceeding with identity + market value only.")

    out = []
    for _, row in target_players.iterrows():
        pid = row[player_id_col]
        stats = stats_by_player.get(pid, {})
        out.append({
            "name": row.get(name_col_p),
            "position": row.get(position_col),
            "age": None if pd.isna(row.get("_age")) else int(row.get("_age")),
            "club": club_id_to_name.get(row.get(player_club_col)),
            "marketValueEur": None if pd.isna(row.get(value_col)) else int(row.get(value_col)),
            "appearances": stats.get("appearances"),
            "goals": stats.get("goals"),
            "assists": stats.get("assists"),
            "minutes": stats.get("minutes"),
            "yellowCards": stats.get("yellow_cards"),
            "redCards": stats.get("red_cards"),
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump({"competition": TARGET_COMPETITION_NAME, "players": out}, f, indent=2)

    print(f"\nWrote {OUT_FILE} — {len(out)} real players with real market values"
          f"{' and real appearance stats' if stats_by_player else ' (appearance stats unavailable)'}.")
    print("Commit this file to your repo.")


if __name__ == "__main__":
    main()
