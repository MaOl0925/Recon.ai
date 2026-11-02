"""
Figures Recon works out from a club's accounts: ratios, the distress score and risk
level, the wage-spend ranking, the European outlook and the labels shown on each club.

build_sample_data.py uses these functions to fill in each league file, and
publish_figures.py runs them again after withholding any figure that fails a check.
DERIVED_FROM and LABEL_INPUTS say which figures from the accounts each worked-out figure
is calculated from, so publish_figures.py knows what to list as withheld alongside it.
The declarations sit next to the code that uses them so the two can't drift apart
(test_financial.py checks them).

Standard library only, so the release gate runs on a bare CI runner.
"""

from __future__ import annotations

from statistics import median

# Figures read from a club's accounts, one value per year, all in millions except
# where the name says otherwise. Each league file keeps them per year in `history`;
# the latest year is repeated at the top level of the club for the site's headline.
ACCOUNT_FIELDS: tuple[str, ...] = (
    "revenue_total_m",
    "costs_total_m",
    "costs_wages_m",
    "costs_amortisation_m",
    "operating_profit_loss_m",
    "profit_on_player_sales_m",
    "finance_costs_m",
    "tax_m",
    "net_profit_loss_m",
    "total_assets_m",
    "total_liabilities_m",
    "net_assets_m",
    "current_assets_m",
    "current_liabilities_m",
    "cash_and_equivalents_m",
    "debt_total_m",
)

LABELS: dict[str, str] = {
    "revenue_total_m": "Revenue",
    "costs_total_m": "Total costs",
    "costs_wages_m": "Wages",
    "costs_amortisation_m": "Player amortisation",
    "operating_profit_loss_m": "Operating profit or loss",
    "profit_on_player_sales_m": "Profit on player sales",
    "finance_costs_m": "Finance costs",
    "tax_m": "Tax",
    "net_profit_loss_m": "Net profit or loss",
    "total_assets_m": "Total assets",
    "total_liabilities_m": "Total liabilities",
    "net_assets_m": "Net assets",
    "current_assets_m": "Current assets",
    "current_liabilities_m": "Current liabilities",
    "cash_and_equivalents_m": "Cash",
    "debt_total_m": "Debt",
}

_DISTRESS_INPUTS = (
    "costs_wages_m",
    "revenue_total_m",
    "net_assets_m",
    "net_profit_loss_m",
    "current_assets_m",
    "current_liabilities_m",
)
_SQUAD_COST_INPUTS = ("costs_wages_m", "costs_amortisation_m", "revenue_total_m")

# Each worked-out figure on a club, and the account figures (latest year) it reads.
DERIVED_FROM: dict[str, tuple[str, ...]] = {
    "costs_wages_ratio": ("costs_wages_m", "revenue_total_m"),
    "debt_to_equity_ratio": ("debt_total_m", "net_assets_m"),
    "current_ratio": ("current_assets_m", "current_liabilities_m"),
    "owner_dependency": ("costs_wages_m", "revenue_total_m"),
    "revenue_vs_peers": ("revenue_total_m",),
    "financial_distress_score": _DISTRESS_INPUTS,
    "risk_level": _DISTRESS_INPUTS,
    "wage_spend_rank": ("costs_wages_m",),
    "wage_position_variance": ("costs_wages_m",),
    "wage_position_summary": ("costs_wages_m",),
    "european_outlook.eu_scr": _SQUAD_COST_INPUTS,
    "european_outlook.eu_scr_breach": _SQUAD_COST_INPUTS,
    "european_outlook.eu_adjusted_wage_ratio": ("costs_wages_m", "revenue_total_m"),
}

# Each label a club can carry, and the figures it reads. Figures that are not account
# figures (like net transfer spend) never get withheld, so they don't need listing.
LABEL_INPUTS: dict[str, tuple[str, ...]] = {
    "Owner-funded": ("costs_wages_m", "revenue_total_m"),
    "Loss-making": ("net_profit_loss_m",),
    "Negative net assets": ("net_assets_m",),
    "Cash-rich": ("cash_and_equivalents_m", "costs_total_m"),
    "Heavily indebted": ("debt_total_m", "revenue_total_m"),
    "Net seller": (),
    "Heavy investor": (),
}

# The share of revenue UEFA lets squad costs (wages plus amortisation) reach.
SQUAD_COST_LIMIT = 0.70
# Sample assumption for the revenue a European campaign adds, by how likely it is.
EUROPEAN_REVENUE_BOOST = {"strong": 0.25, "possible": 0.12}

_ORDINAL_WORDS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
    7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth",
}
_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
                8: "eight", 9: "nine", 10: "ten", 11: "eleven"}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _ratio(a, b) -> float | None:
    if not (_num(a) and _num(b)) or b == 0:
        return None
    return round(a / b, 3)


def ordinal_word(n: int) -> str:
    return _ORDINAL_WORDS.get(n, f"{n}th")


def risk_band(score: float) -> str:
    if score < 25:
        return "Low"
    if score < 50:
        return "Medium"
    if score < 75:
        return "High"
    return "Critical"


def distress_score(row: dict, going_concern: bool) -> float | None:
    """0 to 100, higher is worse. None when any input is missing: a partial score would
    look like a real one."""
    if any(not _num(row.get(f)) for f in _DISTRESS_INPUTS) or row["revenue_total_m"] <= 0:
        return None
    wages_ratio = row["costs_wages_m"] / row["revenue_total_m"]
    points = 0.0
    points += 30 if wages_ratio > 0.9 else 20 if wages_ratio > 0.7 else 10 if wages_ratio > 0.6 else 0
    points += 25 if row["net_assets_m"] < 0 else 0
    loss_share = -row["net_profit_loss_m"] / row["revenue_total_m"]
    points += 20 if loss_share > 0.3 else 12 if loss_share > 0.15 else 6 if loss_share > 0.05 else 0
    current = _ratio(row["current_assets_m"], row["current_liabilities_m"])
    points += 15 if current is not None and current < 0.5 else 8 if current is not None and current < 1 else 0
    points += 10 if going_concern else 0
    return float(min(100, points))


def wage_position_summary(position: int, rank: int) -> str:
    gap = rank - position
    bill = "the largest wage bill" if rank == 1 else f"the {ordinal_word(rank)}-largest wage bill"
    where = f"{ordinal_word(position).capitalize()} in the table with {bill}"
    if gap > 0:
        return f"{where}: {_COUNT_WORDS.get(gap, str(gap))} place{'s' if gap > 1 else ''} better than its spending would suggest."
    if gap < 0:
        return f"{where}: {_COUNT_WORDS.get(-gap, str(-gap))} place{'s' if gap < -1 else ''} worse than its spending would suggest."
    return f"{where}: exactly where its spending would put it."


def european_outlook(club: dict, league_slug: str) -> dict | None:
    """Only the sample Eredivisie has European places. A sketch of the real model: who
    is likely to qualify, and what a campaign does to the wage and squad-cost ratios."""
    if league_slug != "eredivisie":
        return None
    position = club.get("league_position")
    likelihood = "strong" if position in (1, 2) else "possible" if position == 3 else None
    if likelihood is None:
        return None
    wages, amort, revenue = (club.get(f) for f in _SQUAD_COST_INPUTS)
    scr = round((wages + amort) / revenue, 3) if all(_num(v) for v in (wages, amort, revenue)) and revenue > 0 else None
    boost = EUROPEAN_REVENUE_BOOST[likelihood]
    adjusted = round(wages / (revenue * (1 + boost)), 3) if _num(wages) and _num(revenue) and revenue > 0 else None
    return {
        "eu_likelihood": likelihood,
        "eu_competition_label": "Champions League" if position == 1 else "Europa League" if position == 2 else "Conference League",
        "eu_revenue_boost_pct": round(boost * 100),
        "eu_adjusted_wage_ratio": adjusted,
        "eu_scr": scr,
        "eu_scr_breach": None if scr is None else scr > SQUAD_COST_LIMIT,
    }


def labels(club: dict) -> list[str]:
    """Plain labels shown on a club. Each needs every figure it reads; a missing figure
    means no label rather than a guessed one."""
    out = []
    rev, wages = club.get("revenue_total_m"), club.get("costs_wages_m")
    if _num(rev) and _num(wages) and wages > rev:
        out.append("Owner-funded")
    if _num(club.get("net_profit_loss_m")) and club["net_profit_loss_m"] < 0:
        out.append("Loss-making")
    if _num(club.get("net_assets_m")) and club["net_assets_m"] < 0:
        out.append("Negative net assets")
    cash, costs = club.get("cash_and_equivalents_m"), club.get("costs_total_m")
    if _num(cash) and _num(costs) and costs > 0 and cash >= 0.25 * costs:
        out.append("Cash-rich")
    debt = club.get("debt_total_m")
    if _num(debt) and _num(rev) and rev > 0 and debt > rev:
        out.append("Heavily indebted")
    net_spend = club.get("net_transfer_spend_3yr_m")
    if _num(net_spend) and net_spend <= -10:
        out.append("Net seller")
    if _num(net_spend) and net_spend >= 15:
        out.append("Heavy investor")
    return out


def apply_league(league: dict) -> None:
    """Fill in every worked-out figure for every club in one league file, in place.
    The headline figures are always the latest year of `history`."""
    clubs = league["clubs"]
    for club in clubs:
        for row in club["history"]:
            row["costs_wages_ratio"] = _ratio(row.get("costs_wages_m"), row.get("revenue_total_m"))
        latest = max(club["history"], key=lambda r: r["year"])
        club["filing_year"] = latest["year"]
        for f in ACCOUNT_FIELDS:
            club[f] = latest.get(f)

    revenues = [c["revenue_total_m"] for c in clubs if _num(c["revenue_total_m"])]
    typical = median(revenues) if revenues else None

    for club in clubs:
        rev, wages = club["revenue_total_m"], club["costs_wages_m"]
        club["costs_wages_ratio"] = _ratio(wages, rev)
        club["debt_to_equity_ratio"] = (
            _ratio(club["debt_total_m"], club["net_assets_m"])
            if _num(club["net_assets_m"]) and club["net_assets_m"] > 0 else None
        )
        club["current_ratio"] = _ratio(club["current_assets_m"], club["current_liabilities_m"])
        club["owner_dependency"] = (wages > rev) if _num(wages) and _num(rev) else None
        club["revenue_vs_peers"] = round(rev / typical, 2) if _num(rev) and typical else None
        score = distress_score(club, bool(club.get("going_concern_warning")))
        club["financial_distress_score"] = score
        club["risk_level"] = risk_band(score) if score is not None else None
        club["european_outlook"] = european_outlook(club, league["league"])
        club["descriptors"] = labels(club)

    # Wage-spend rank among the clubs whose wage bill we have.
    ranked = sorted((c for c in clubs if _num(c["costs_wages_m"])), key=lambda c: -c["costs_wages_m"])
    for club in clubs:
        club["wage_spend_rank"] = None
        club["wage_position_variance"] = None
        club["wage_position_summary"] = None
    for rank, club in enumerate(ranked, start=1):
        club["wage_spend_rank"] = rank
        if _num(club.get("league_position")):
            club["wage_position_variance"] = rank - club["league_position"]
            club["wage_position_summary"] = wage_position_summary(club["league_position"], rank)
