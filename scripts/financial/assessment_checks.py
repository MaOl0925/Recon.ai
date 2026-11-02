"""
Keeps each club's written assessment in step with the figures it describes.

An assessment is written from the figures at the time. Text can't be checked figure by
figure the way the tables are, so:

  - every accepted assessment is stamped with a fingerprint of the club's figures
    (`narrative_figures`) and of its own text (`_narrative_hash`); if the figures change
    while the text stays the same, the assessment comes down until it is rewritten
  - any assessment that quotes a figure we couldn't read reliably comes down

A rewrite is recognised because its text differs from the text that came down, so no one
has to approve it by hand. Putting the old text back keeps it down.

Standard library only, so the release gate runs on a bare CI runner.
"""

from __future__ import annotations

import hashlib
import json
import re

# Keys that belong to the assessment itself, not the figures it describes.
_ASSESSMENT_KEYS = {"narrative", "narrative_figures", "_narrative_hash"}

# An amount in the text: "£12.3m", "€4m", "12.3 million", "£1.2bn". A bare number with
# no currency and no unit (a year, a league position) is never treated as an amount.
_AMOUNT = re.compile(
    r"(?P<cur>[£€])?\s?(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<unit>bn|billion|m\b|million)?",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s?(?:%|per\s?cent)", re.IGNORECASE)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def text_hash(text: str) -> str:
    """The same words, however they are spaced, hash the same."""
    return _short_hash(" ".join(text.split()))


def figures_fingerprint(club: dict) -> str:
    """A fingerprint of everything an assessment could describe: every figure on the club
    except the assessment and its own entry in `excluded_figures`."""
    data = {k: v for k, v in club.items() if k not in _ASSESSMENT_KEYS}
    data["excluded_figures"] = [e for e in club.get("excluded_figures", []) if e.get("field") != "narrative"]
    return _short_hash(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def stamp(club: dict) -> None:
    """Accept the club's current assessment for the figures it now has."""
    club["narrative_figures"] = figures_fingerprint(club)
    club["_narrative_hash"] = text_hash(club["narrative"])


def is_stamped_for_current_figures(club: dict) -> bool:
    text = club.get("narrative")
    return (
        bool(text)
        and club.get("_narrative_hash") == text_hash(text)
        and club.get("narrative_figures") == figures_fingerprint(club)
    )


def _amounts(text: str) -> list[tuple[float, bool]]:
    """Every amount quoted in millions, with whether it was quoted to a decimal place."""
    found = []
    for m in _AMOUNT.finditer(text):
        if not (m.group("cur") or m.group("unit")):
            continue
        raw = m.group("num").replace(",", "")
        value = float(raw)
        unit = (m.group("unit") or "").lower()
        if unit in ("bn", "billion"):
            value *= 1000
        found.append((value, "." in raw))
    return found


def quoted_figures(text: str | None, withheld: list[dict]) -> list[dict]:
    """The withheld figures an assessment quotes. `withheld` holds the figures we couldn't
    read reliably: {"value", "kind"}, kind "money" (in millions) or "ratio" (0.78 = 78%)."""
    if not text:
        return []
    amounts = _amounts(text)
    percents = [float(m.group("num")) for m in _PERCENT.finditer(text)]
    hits = []
    for w in withheld:
        v = w.get("value")
        if not isinstance(v, (int, float)):
            continue
        if w.get("kind") == "ratio":
            if any(abs(p - v * 100) <= 0.5 for p in percents):
                hits.append(w)
        elif any(abs(a - abs(v)) <= (0.05 if decimal else 0.5) for a, decimal in amounts):
            hits.append(w)
    return hits
