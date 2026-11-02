"""
Check every club finance figure in data/financial/, withhold any that fails, work out the
ratios again, and keep each written assessment in step with the figures it describes.

    python scripts/financial/publish_figures.py           # check, withhold, stamp, write
    python scripts/financial/publish_figures.py --check   # release gate: exit 1 if anything fails

Run it after anything that changes a league file: build_sample_data.py runs it itself,
and the club-narratives agent runs it after writing assessments. The CI workflow runs
--check, so a league file that skipped this step can't be merged.

What "withheld" means:
  - the figure is set to null, and the app says we couldn't read it reliably from the
    club's accounts rather than showing a wrong number
  - every ratio, score and label worked out from it is worked out again without it,
    using derived_figures.py, and listed alongside it in the club's `excluded_figures`
  - figures-review.json records the value that was withheld and why, so someone can
    check it against the original accounts

What happens to assessments (see assessment_checks.py):
  - one that quotes a withheld figure is taken down
  - one whose figures have changed since it was accepted is taken down
  - a taken-down assessment shows as "narrative": null, with {"field": "narrative",
    "source": "calculated"} in `excluded_figures` and its reason under `assessments` in
    figures-review.json; new text goes back up on the next run, the old text stays down
  - everything else is accepted and stamped (`narrative_figures`, `_narrative_hash`).
    Never set those two by hand.

Recon.ai's repository is public, so figures-review.json is public too. That is fine for
the sample data this ships with; real figures would need the review list kept elsewhere.

Standard library only, so the release gate runs on a bare CI runner.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assessment_checks as ac  # noqa: E402
import derived_figures as derived  # noqa: E402
import figure_checks as fc  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "financial"
REVIEW_NAME = "figures-review.json"
SYMBOLS = {"GBP": "£", "EUR": "€"}

FigureKey = tuple[str, str, int, str]  # league, club_slug, year, field
ClubKey = tuple[str, str]  # league, club_slug


def rel(path: Path) -> str:
    """A path as it is shown in messages: relative to the repository when it is inside it."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def league_files(directory: Path) -> list[Path]:
    """Every league file: a JSON file with a `clubs` list (the review list has none)."""
    out = []
    for path in sorted(directory.glob("*.json")):
        if path.name == REVIEW_NAME:
            continue
        data = read_json(path)
        if isinstance(data, dict) and isinstance(data.get("clubs"), list):
            out.append(path)
    return out


def load_review(path: Path) -> tuple[dict[FigureKey, dict], dict[ClubKey, dict]]:
    if not path.exists():
        return {}, {}
    data = read_json(path)
    figures = {(e["league"], e["club_slug"], e["year"], e["field"]): e for e in data.get("figures", [])}
    downs = {(e["league"], e["club_slug"]): e for e in data.get("assessments", [])}
    return figures, downs


def money(value: float, currency: str) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{SYMBOLS.get(currency, '')}{abs(value):,.1f}m"


def expected_excluded(club: dict, records: list[dict]) -> list[dict]:
    """The club's `excluded_figures` (without any narrative entry): every withheld figure
    from the accounts, and everything worked out from a withheld figure in the latest year."""
    out = [
        {"year": r["year"], "field": r["field"], "label": derived.LABELS[r["field"]], "source": "accounts"}
        for r in sorted(records, key=lambda r: (r["year"], r["field"]))
    ]
    latest = club["filing_year"]
    latest_withheld = {r["field"] for r in records if r["year"] == latest}
    for field, inputs in derived.DERIVED_FROM.items():
        if field.startswith("european_outlook.") and not club.get("european_outlook"):
            continue
        if latest_withheld & set(inputs):
            out.append({"year": latest, "field": field, "source": "calculated"})
    for label, inputs in derived.LABEL_INPUTS.items():
        if latest_withheld & set(inputs):
            out.append({"year": latest, "field": f"label:{label}", "source": "calculated"})
    return out


_NARRATIVE_ENTRY = {"field": "narrative", "source": "calculated"}


def _withhold(club: dict, league_slug: str, earlier: dict[FigureKey, dict]) -> list[dict]:
    """Null every failing figure in the club's history. Returns the club's review records:
    earlier ones still in force, plus new findings."""
    rows = {r["year"]: r for r in club["history"]}
    records = []
    for (lg, slug, year, field), rec in earlier.items():
        if lg != league_slug or slug != club["club_slug"] or year not in rows:
            continue
        current = rows[year].get(field)
        if current is None or current == rec["value"]:
            rows[year][field] = None  # still the misread value (or already withheld)
            records.append(rec)
        # A different value means the figure was read again; the rules decide below.
    for finding in fc.check_club(club):
        rows[finding.year][finding.field] = None
        records.append({
            "league": league_slug, "club": club["club_name"], "club_slug": club["club_slug"],
            "year": finding.year, "field": finding.field, "label": finding.label,
            "value": finding.value, "rule": finding.rule, "reason": finding.reason,
        })
    return records


def _assessment(club: dict, league: dict, records: list[dict], earlier: dict | None) -> dict | None:
    """Accept and stamp the club's assessment, or take it down. Returns the review entry
    when it is down."""
    text = club.get("narrative")
    entry_base = {"league": league["league"], "club": club["club_name"], "club_slug": club["club_slug"]}
    if not text:
        return earlier  # nothing written yet, or still down waiting for a rewrite
    h = ac.text_hash(text)
    reason = None
    if earlier and earlier.get("text_hash") == h:
        reason = earlier["reason"]  # the text that came down was put back
    else:
        withheld = [{"value": r["value"], "kind": "money", "record": r} for r in records]
        quoted = ac.quoted_figures(text, withheld)
        if quoted:
            parts = [f"{money(q['value'], league['currency'])} ({q['record']['label']}, {q['record']['year']})" for q in quoted]
            reason = "Quotes " + ", ".join(parts) + ", which we couldn't read reliably from the club's accounts"
        elif (club.get("_narrative_hash") == h and club.get("narrative_figures")
              and club["narrative_figures"] != ac.figures_fingerprint(club)):
            reason = "The figures it was written from have changed since it was accepted"
    if reason:
        club["narrative"] = None
        club["narrative_figures"] = None
        club["_narrative_hash"] = None
        return {**entry_base, "reason": reason, "text_hash": h, "text": text}
    ac.stamp(club)
    return None


def publish(data_dir: Path = DATA_DIR) -> int:
    review_path = data_dir / REVIEW_NAME
    earlier_figures, earlier_downs = load_review(review_path)
    all_records: list[dict] = []
    all_downs: list[dict] = []
    summary = []

    for path in league_files(data_dir):
        league = read_json(path)
        slug = league["league"]
        records_by_club = {c["club_slug"]: _withhold(c, slug, earlier_figures) for c in league["clubs"]}
        derived.apply_league(league)
        downs = 0
        for club in league["clubs"]:
            records = records_by_club[club["club_slug"]]
            club["excluded_figures"] = expected_excluded(club, records)
            down = _assessment(club, league, records, earlier_downs.get((slug, club["club_slug"])))
            if down:
                club["excluded_figures"].append(dict(_NARRATIVE_ENTRY))
                all_downs.append(down)
                downs += 1
            all_records.extend(records)
        write_json(path, league)
        withheld = sum(len(r) for r in records_by_club.values())
        summary.append(f"  {path.name}: {len(league['clubs'])} clubs, {withheld} figure(s) withheld, {downs} assessment(s) down")

    write_json(review_path, {
        "about": "Figures withheld because they failed a check, and assessments taken down. "
                 "Written by scripts/financial/publish_figures.py; don't edit by hand.",
        "figures": sorted(all_records, key=lambda r: (r["league"], r["club_slug"], r["year"], r["field"])),
        "assessments": sorted(all_downs, key=lambda r: (r["league"], r["club_slug"])),
    })
    print("Published club finance figures:")
    print("\n".join(summary))
    if all_downs:
        print(f"{len(all_downs)} assessment(s) need rewriting; see {rel(review_path)}")
    return 0


def check(data_dir: Path = DATA_DIR) -> int:
    """The release gate: change nothing, fail if anything on the site would be wrong."""
    figures, downs = load_review(data_dir / REVIEW_NAME)
    problems: list[str] = []
    files = league_files(data_dir)
    for path in files:
        league = read_json(path)
        slug = league["league"]
        recalculated = copy.deepcopy(league)
        derived.apply_league(recalculated)
        for club, again in zip(league["clubs"], recalculated["clubs"]):
            name = f"{path.name} · {club['club_name']}"
            records = [r for (lg, s, _, _), r in figures.items() if lg == slug and s == club["club_slug"]]
            for f in fc.check_club(club):
                problems.append(f"{name}: {f.label} {f.year} fails '{f.rule}' ({f.reason}) and is still showing")
            rows = {r["year"]: r for r in club["history"]}
            for r in records:
                if rows.get(r["year"], {}).get(r["field"]) is not None:
                    problems.append(f"{name}: {r['label']} {r['year']} was withheld but has a value again")
            if json.dumps(club, sort_keys=True) != json.dumps(again, sort_keys=True):
                problems.append(f"{name}: worked-out figures don't match the accounts figures")
            listed = [e for e in club.get("excluded_figures", []) if e.get("field") != "narrative"]
            if listed != expected_excluded(club, records):
                problems.append(f"{name}: excluded_figures doesn't match the withheld figures")
            text = club.get("narrative")
            if text:
                if not ac.is_stamped_for_current_figures(club):
                    problems.append(f"{name}: the assessment hasn't been accepted for the figures now in the file")
                if ac.quoted_figures(text, [{"value": r["value"], "kind": "money"} for r in records]):
                    problems.append(f"{name}: the assessment quotes a withheld figure")
            elif (slug, club["club_slug"]) in downs and _NARRATIVE_ENTRY not in club.get("excluded_figures", []):
                problems.append(f"{name}: a taken-down assessment isn't marked in excluded_figures")

    if problems:
        print(f"Club finance figures: {len(problems)} problem(s). Run scripts/financial/publish_figures.py, then check again.")
        for p in problems[:200]:
            print(f"  - {p}")
        return 1
    print(f"Club finance figures: {len(files)} league file(s) pass.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="release gate: change nothing, exit 1 on any problem")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    return check(args.data_dir) if args.check else publish(args.data_dir)


if __name__ == "__main__":
    sys.exit(main())
