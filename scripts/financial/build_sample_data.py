"""
Build the sample club finance league files in data/financial/, then publish them.

    python scripts/financial/build_sample_data.py

Every club here is fictional, and so is every figure. Recon.ai's repository is public,
and made-up accounts for real clubs would read as claims about real companies, so the
finance view ships with sample clubs until real figures (in the same format) replace them.

The figures are built from their parts (wages, other costs, player sales, finance costs,
tax, owner money) so they add up the way real accounts do. Three clubs then get one
figure deliberately misread, the way reading real accounts goes wrong, so the checks in
figure_checks.py have something to withhold:
  - Westmarsh City: 2024 revenue read as the year "2024"
  - Fennick Rovers: 2023 net assets read from the wrong line
  - SC Duinwijk: 2024 net result with its minus sign lost

Deterministic (seeded per club), so running it again gives the same figures and any
accepted assessment stays up. Assessments already in the files are kept.

Standard library only.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import derived_figures as derived  # noqa: E402
import publish_figures  # noqa: E402

DATA_DIR = publish_figures.DATA_DIR
YEARS = (2020, 2021, 2022, 2023, 2024)
CAVEAT = ("Sample figures for a fictional club, generated to demonstrate Recon's finance "
          "pipeline. Not real accounts.")

# Each club's financial character. revenue: 2020 revenue (m); growth: yearly change;
# wages: wage-to-revenue ratio in 2020 and its yearly drift; amort/other: shares of
# revenue; sales: profit on player sales as a share of revenue; owner: money the owner
# puts in each year as a share of revenue (equity, not a loan); assets: total assets as
# a multiple of revenue; debt: share of liabilities that is borrowing; cash: share of
# current assets held as cash; position: where the club sits now; net_spend: 3-year net
# transfer spend (m, negative = net seller).
LEAGUES = {
    "championship": {
        "label": "Championship", "currency": "GBP", "period_end": "05-31",
        "clubs": {
            "Kingsmere United": dict(revenue=31, growth=0.06, wages=1.08, drift=0.03, amort=0.22, other=0.30, sales=0.05, owner=0.55, assets=2.4, debt=0.55, cash=0.35, position=1, net_spend=24.5),
            "Ravensholme Town": dict(revenue=28, growth=0.04, wages=0.82, drift=0.01, amort=0.16, other=0.28, sales=0.10, owner=0.18, assets=1.6, debt=0.45, cash=0.30, position=4, net_spend=16.2),
            "Calderbrook Athletic": dict(revenue=24, growth=0.05, wages=0.64, drift=-0.01, amort=0.12, other=0.27, sales=0.30, owner=0.0, assets=1.3, debt=0.25, cash=0.45, position=3, net_spend=-14.8),
            "Westmarsh City": dict(revenue=36, growth=0.03, wages=0.86, drift=0.02, amort=0.18, other=0.29, sales=0.08, owner=0.20, assets=2.0, debt=0.50, cash=0.30, position=6, net_spend=6.1),
            "Fennick Rovers": dict(revenue=19, growth=0.02, wages=0.74, drift=0.0, amort=0.10, other=0.30, sales=0.12, owner=0.05, assets=1.1, debt=0.40, cash=0.35, position=7, net_spend=-3.4),
            "Hollowfield United": dict(revenue=22, growth=-0.04, wages=0.95, drift=0.03, amort=0.14, other=0.31, sales=0.04, owner=0.0, assets=1.2, debt=0.65, cash=0.15, position=8, net_spend=1.9),
            "Brackwater Albion": dict(revenue=26, growth=0.07, wages=0.58, drift=0.0, amort=0.09, other=0.25, sales=0.14, owner=0.0, assets=1.5, debt=0.15, cash=0.75, position=2, net_spend=-6.7),
            "Elmstead County": dict(revenue=17, growth=0.03, wages=0.80, drift=0.01, amort=0.08, other=0.30, sales=0.06, owner=0.12, assets=0.9, debt=0.35, cash=0.40, position=5, net_spend=0.8, abbreviated=True),
        },
    },
    "eredivisie": {
        "label": "Eredivisie", "currency": "EUR", "period_end": "06-30",
        "clubs": {
            "FC Zandmeer": dict(revenue=96, growth=0.08, wages=0.52, drift=0.01, amort=0.20, other=0.24, sales=0.22, owner=0.0, assets=2.2, debt=0.30, cash=0.40, position=1, net_spend=21.4),
            "SV Kanaalstad": dict(revenue=41, growth=0.05, wages=0.50, drift=0.01, amort=0.15, other=0.26, sales=0.45, owner=0.0, assets=1.7, debt=0.25, cash=0.50, position=2, net_spend=-38.6),
            "SC Duinwijk": dict(revenue=23, growth=0.01, wages=0.72, drift=0.03, amort=0.12, other=0.29, sales=0.05, owner=0.10, assets=1.4, debt=0.50, cash=0.25, position=4, net_spend=3.2),
            "FC Polderburg": dict(revenue=15, growth=0.03, wages=0.60, drift=0.0, amort=0.08, other=0.27, sales=0.10, owner=0.0, assets=1.0, debt=0.20, cash=0.45, position=3, net_spend=-2.1),
        },
    },
}

_FIRST = "ABCDEFGHJKLMNPRSTW"
_SURNAMES = ["Varga", "Holm", "Achterberg", "Mbeki", "Lindgren", "Okoro", "Sauer", "Pellow",
             "Dragovic", "Ferro", "Quist", "Nakamura", "Brennan", "Tiago", "Vos", "Kerrigan"]
_BUYERS = ["a Bundesliga club", "a Premier League club", "a Serie A club", "a Ligue 1 club",
           "a La Liga club", "a club in Portugal", "a league rival"]


def _slug(name: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in name).split())


def _r(x: float) -> float:
    return round(x + 0.0, 1)


def build_club(name: str, p: dict, period_end: str) -> dict:
    rng = random.Random(f"recon-finance-{name}")
    history = []
    revenue = p["revenue"]
    wages_ratio = p["wages"]
    assets = p["revenue"] * p["assets"]
    net_assets = assets * rng.uniform(0.15, 0.45)
    for year in YEARS:
        if year != YEARS[0]:
            revenue *= 1 + p["growth"] + rng.uniform(-0.03, 0.03)
            wages_ratio += p["drift"] + rng.uniform(-0.015, 0.015)
            assets *= 1 + p["growth"] + rng.uniform(-0.04, 0.04)
        rev = _r(revenue)
        wages = _r(rev * wages_ratio)
        amort = _r(rev * (p["amort"] + rng.uniform(-0.01, 0.01)))
        other = _r(rev * (p["other"] + rng.uniform(-0.015, 0.015)))
        costs = _r(wages + amort + other)
        operating = _r(rev - costs)
        sales = _r(rev * p["sales"] * rng.uniform(0.6, 1.4))
        liabilities_guess = max(assets - net_assets, assets * 0.3)
        finance = _r(liabilities_guess * p["debt"] * rng.uniform(0.04, 0.07))
        pre_tax = operating + sales - finance
        tax = _r(max(0.0, pre_tax) * 0.2)
        net = _r(operating + sales - finance - tax)
        net_assets += net + rev * p["owner"]
        total_assets = _r(max(assets, net_assets + assets * 0.3))
        net_assets_r = _r(net_assets)
        liabilities = _r(total_assets - net_assets_r)
        current_assets = _r(total_assets * rng.uniform(0.18, 0.32))
        current_liabilities = _r(liabilities * rng.uniform(0.35, 0.55))
        history.append({
            "year": year,
            "revenue_total_m": rev,
            "costs_total_m": costs,
            "costs_wages_m": wages,
            "costs_amortisation_m": amort,
            "operating_profit_loss_m": operating,
            "profit_on_player_sales_m": sales,
            "finance_costs_m": finance,
            "tax_m": tax,
            "net_profit_loss_m": net,
            "total_assets_m": total_assets,
            "total_liabilities_m": liabilities,
            "net_assets_m": net_assets_r,
            "current_assets_m": current_assets,
            "current_liabilities_m": current_liabilities,
            "cash_and_equivalents_m": _r(current_assets * p["cash"] * rng.uniform(0.85, 1.15)),
            "debt_total_m": _r(liabilities * p["debt"]),
        })

    if p.get("abbreviated"):
        # Small companies may file abbreviated accounts: a balance sheet, no profit and loss.
        for row in history:
            for f in ("revenue_total_m", "costs_total_m", "costs_wages_m", "costs_amortisation_m",
                      "operating_profit_loss_m", "profit_on_player_sales_m", "finance_costs_m",
                      "tax_m", "net_profit_loss_m"):
                row[f] = None

    latest = history[-1]
    current_ratio = latest["current_assets_m"] / latest["current_liabilities_m"]
    going_concern = latest["net_assets_m"] < 0 and current_ratio < 0.8

    sales = []
    if p["sales"] >= 0.2 and latest["profit_on_player_sales_m"]:
        for i in range(2 if p["sales"] >= 0.4 else 1):
            player = f"{rng.choice(_FIRST)}. {rng.choice(_SURNAMES)}"
            fee = _r(latest["profit_on_player_sales_m"] * (0.55 if i == 0 else 0.3) * rng.uniform(0.9, 1.3))
            sales.append({"player": player, "to": rng.choice(_BUYERS), "fee_m": fee, "year": YEARS[-1]})

    return {
        "club_name": name,
        "club_slug": _slug(name),
        "sample": True,
        "data_caveat": CAVEAT,
        "period_end": f"{YEARS[-1]}-{period_end}",
        "abbreviated_accounts": bool(p.get("abbreviated")),
        "going_concern_warning": going_concern,
        "league_position": p["position"],
        "net_transfer_spend_3yr_m": p["net_spend"],
        "notable_sales": sales,
        "history": history,
    }


def plant_misreads(league: dict) -> None:
    """The three misread figures described at the top of this file."""
    by_slug = {c["club_slug"]: c for c in league["clubs"]}
    rows = lambda slug: {r["year"]: r for r in by_slug[slug]["history"]}  # noqa: E731
    if "westmarsh-city" in by_slug:
        rows("westmarsh-city")[2024]["revenue_total_m"] = 2024.0
    if "fennick-rovers" in by_slug:
        row = rows("fennick-rovers")[2023]
        row["net_assets_m"] = row["total_assets_m"]  # read from the total assets line
    if "sc-duinwijk" in by_slug:
        row = rows("sc-duinwijk")[2024]
        row["net_profit_loss_m"] = abs(row["net_profit_loss_m"])


def build(data_dir: Path = DATA_DIR) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for slug, spec in LEAGUES.items():
        path = data_dir / f"{slug}.json"
        kept = {}
        if path.exists():
            for c in json.loads(path.read_text(encoding="utf-8")).get("clubs", []):
                kept[c["club_slug"]] = {k: c.get(k) for k in ("narrative", "narrative_figures", "_narrative_hash")}
        clubs = [build_club(name, p, spec["period_end"]) for name, p in spec["clubs"].items()]
        clubs.sort(key=lambda c: c["league_position"])
        league = {
            "league": slug,
            "leagueLabel": spec["label"],
            "currency": spec["currency"],
            "sample": True,
            "data_caveat": "Sample data: every club and figure here is fictional, generated by "
                           "scripts/financial/build_sample_data.py to demonstrate the finance pipeline.",
            "clubs": clubs,
        }
        plant_misreads(league)
        derived.apply_league(league)
        for club in clubs:
            club["excluded_figures"] = []
            club.update(kept.get(club["club_slug"], {"narrative": None, "narrative_figures": None, "_narrative_hash": None}))
        publish_figures.write_json(path, league)
        print(f"Built {publish_figures.rel(path)}: {len(clubs)} sample clubs")


if __name__ == "__main__":
    build()
    sys.exit(publish_figures.publish())
