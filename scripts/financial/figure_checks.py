"""
Checks that every club finance figure Recon publishes is believable.

Figures are read from club accounts, and reading goes wrong in a handful of recognisable
ways: a year read as an amount, a minus sign lost, a total read from the wrong line, a
figure in thousands taken as millions. Each rule below spots one of those. A figure that
fails is withheld (set to null) by publish_figures.py rather than shown wrong, and the
release gate (`publish_figures.py --check`) fails if a failing figure is still showing.

Rules run in order over every year of a club's `history`. A rule skips figures an
earlier rule already failed, so each figure is reported once, for its first fault.

Standard library only, so the release gate runs on a bare CI runner.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from statistics import median

from derived_figures import ACCOUNT_FIELDS, LABELS

# Figures that can never be negative in a set of accounts.
_NEVER_NEGATIVE = (
    "revenue_total_m", "costs_total_m", "costs_wages_m", "costs_amortisation_m",
    "total_assets_m", "total_liabilities_m", "current_assets_m", "current_liabilities_m",
    "cash_and_equivalents_m", "debt_total_m",
)


@dataclass(frozen=True)
class Finding:
    year: int
    field: str
    rule: str
    reason: str
    value: float

    @property
    def label(self) -> str:
        return LABELS.get(self.field, self.field)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _tolerance(scale: float) -> float:
    """Rounding room when figures that should add up are compared: 2% of the size of
    the club's numbers, and never less than £/€0.2m."""
    return max(0.2, 0.02 * abs(scale))


class ClubYears:
    """One club's history, with the figures earlier rules already failed."""

    def __init__(self, club: dict):
        self.club = club
        self.rows = sorted(club.get("history", []), key=lambda r: r["year"])
        self.failed: set[tuple[int, str]] = set()

    def value(self, row: dict, field: str):
        if (row["year"], field) in self.failed or not _num(row.get(field)):
            return None
        return row[field]

    def typical(self, field: str, except_year: int) -> float | None:
        """The club's usual size for a figure, from its other years."""
        vals = [abs(r[field]) for r in self.rows if r["year"] != except_year and _num(r.get(field))]
        return median(vals) if vals else None


def negative_size(c: ClubYears) -> Iterator[Finding]:
    for row in c.rows:
        for f in _NEVER_NEGATIVE:
            v = c.value(row, f)
            if v is not None and v < 0:
                yield Finding(row["year"], f, "negative_size", f"{LABELS[f]} can't be negative", v)


def year_as_money(c: ClubYears) -> Iterator[Finding]:
    """A figure that is exactly a calendar year and far bigger than the club's other
    years was almost certainly read from a date or a heading."""
    for row in c.rows:
        for f in ACCOUNT_FIELDS:
            v = c.value(row, f)
            if v is None or not float(v).is_integer() or not 1990 <= abs(v) <= 2040:
                continue
            usual = c.typical(f, row["year"])
            if usual is not None and abs(v) > 10 * max(usual, 1):
                yield Finding(row["year"], f, "year_as_money", f"{LABELS[f]} reads as the year {int(abs(v))}", v)


def wages_exceed_costs(c: ClubYears) -> Iterator[Finding]:
    for row in c.rows:
        wages, costs = c.value(row, "costs_wages_m"), c.value(row, "costs_total_m")
        if wages is not None and costs is not None and wages > costs + _tolerance(costs):
            yield Finding(row["year"], "costs_wages_m", "wages_exceed_costs",
                          "Wages are larger than the total costs they are part of", wages)


def revenue_jump(c: ClubYears) -> Iterator[Finding]:
    """Revenue more than three times (or under a third of) both neighbouring years: the
    shape of a unit slip, not a real season."""
    for i, row in enumerate(c.rows):
        v = c.value(row, "revenue_total_m")
        if v is None or v <= 0:
            continue
        neighbours = [c.value(r, "revenue_total_m") for r in c.rows[max(0, i - 1):i] + c.rows[i + 1:i + 2]]
        neighbours = [n for n in neighbours if n is not None and n > 0]
        if neighbours and all(v / n > 3 or n / v > 3 for n in neighbours):
            yield Finding(row["year"], "revenue_total_m", "revenue_jump",
                          "Revenue is out of line with the years either side", v)


def operating_sum(c: ClubYears) -> Iterator[Finding]:
    """Operating profit or loss must be revenue minus total costs."""
    for row in c.rows:
        rev, costs, op = (c.value(row, f) for f in ("revenue_total_m", "costs_total_m", "operating_profit_loss_m"))
        if None in (rev, costs, op):
            continue
        if abs((rev - costs) - op) > _tolerance(rev):
            yield Finding(row["year"], "operating_profit_loss_m", "operating_sum",
                          "Operating result isn't revenue minus costs", op)


def lost_minus_sign(c: ClubYears) -> Iterator[Finding]:
    """A net result with the right size but the wrong sign: the bracket around a loss
    was dropped when it was read."""
    for row in c.rows:
        net = c.value(row, "net_profit_loss_m")
        expected = _expected_net(c, row)
        if net is None or expected is None or abs(expected) < 0.5:
            continue
        tol = _tolerance(c.value(row, "revenue_total_m") or expected)
        if abs(net + expected) <= tol and abs(net - expected) > tol:
            yield Finding(row["year"], "net_profit_loss_m", "lost_minus_sign",
                          "Net result has the right size but the wrong sign", net)


def net_sum(c: ClubYears) -> Iterator[Finding]:
    """The net result must follow from the operating result and the lines below it."""
    for row in c.rows:
        net, expected = c.value(row, "net_profit_loss_m"), _expected_net(c, row)
        if net is None or expected is None:
            continue
        if abs(net - expected) > _tolerance(c.value(row, "revenue_total_m") or expected):
            yield Finding(row["year"], "net_profit_loss_m", "net_sum",
                          "Net result doesn't follow from the operating result", net)


def _expected_net(c: ClubYears, row: dict) -> float | None:
    parts = [c.value(row, f) for f in ("operating_profit_loss_m", "profit_on_player_sales_m", "finance_costs_m", "tax_m")]
    if None in parts:
        return None
    op, sales, finance, tax = parts
    return op + sales - finance - tax


def balance_sheet(c: ClubYears) -> Iterator[Finding]:
    """Net assets must be total assets minus total liabilities."""
    for row in c.rows:
        assets, liabilities, net = (c.value(row, f) for f in ("total_assets_m", "total_liabilities_m", "net_assets_m"))
        if None in (assets, liabilities, net):
            continue
        if abs((assets - liabilities) - net) > _tolerance(assets):
            yield Finding(row["year"], "net_assets_m", "balance_sheet",
                          "Net assets aren't total assets minus total liabilities", net)


# Order matters: the specific misreads come before the sums that would also trip on them.
RULES: tuple[Callable[[ClubYears], Iterator[Finding]], ...] = (
    negative_size,
    year_as_money,
    wages_exceed_costs,
    revenue_jump,
    operating_sum,
    lost_minus_sign,
    net_sum,
    balance_sheet,
)


def check_club(club: dict) -> list[Finding]:
    """Every failing figure in one club's history, each reported once."""
    years = ClubYears(club)
    findings: list[Finding] = []
    for rule in RULES:
        for finding in rule(years):
            key = (finding.year, finding.field)
            if key in years.failed:
                continue
            years.failed.add(key)
            findings.append(finding)
    return findings
