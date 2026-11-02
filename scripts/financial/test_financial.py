"""
Tests for the club finance pipeline.

    python -m unittest discover -s scripts/financial -p "test_*.py"

Each test builds the sample league files into a temporary folder, so the real files in
data/financial/ are never touched. Standard library only.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assessment_checks as ac  # noqa: E402
import build_sample_data  # noqa: E402
import derived_figures as derived  # noqa: E402
import figure_checks as fc  # noqa: E402
import publish_figures as pf  # noqa: E402


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


class SampleData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        quiet(build_sample_data.build, self.dir)
        quiet(pf.publish, self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def league(self, slug):
        return json.loads((self.dir / f"{slug}.json").read_text(encoding="utf-8"))

    def save(self, slug, data):
        pf.write_json(self.dir / f"{slug}.json", data)

    def club(self, data, slug):
        return next(c for c in data["clubs"] if c["club_slug"] == slug)

    def review(self):
        return json.loads((self.dir / pf.REVIEW_NAME).read_text(encoding="utf-8"))


class FigureChecks(SampleData):
    def test_each_planted_misread_is_withheld_by_its_rule(self):
        found = {(f["club_slug"], f["year"], f["field"], f["rule"]) for f in self.review()["figures"]}
        self.assertEqual(found, {
            ("westmarsh-city", 2024, "revenue_total_m", "year_as_money"),
            ("fennick-rovers", 2023, "net_assets_m", "balance_sheet"),
            ("sc-duinwijk", 2024, "net_profit_loss_m", "lost_minus_sign"),
        })

    def test_withheld_figures_are_null_in_the_headline_and_history(self):
        westmarsh = self.club(self.league("championship"), "westmarsh-city")
        self.assertIsNone(westmarsh["revenue_total_m"])
        self.assertIsNone(next(r for r in westmarsh["history"] if r["year"] == 2024)["revenue_total_m"])

    def test_everything_worked_out_from_a_withheld_figure_is_withheld_too(self):
        westmarsh = self.club(self.league("championship"), "westmarsh-city")
        listed = {e["field"] for e in westmarsh["excluded_figures"]}
        for field in ("costs_wages_ratio", "owner_dependency", "revenue_vs_peers", "financial_distress_score", "risk_level"):
            self.assertIn(field, listed)
            self.assertIsNone(westmarsh[field])

    def test_clean_clubs_pass_every_rule(self):
        for slug in ("championship", "eredivisie"):
            for club in self.league(slug)["clubs"]:
                self.assertEqual(fc.check_club(club), [], club["club_slug"])

    def test_each_rule_catches_its_misread(self):
        base = self.club(self.league("championship"), "brackwater-albion")
        cases = {
            "negative_size": ("cash_and_equivalents_m", lambda v: -v),
            "year_as_money": ("costs_wages_m", lambda v: 2023.0),
            "wages_exceed_costs": ("costs_wages_m", lambda v: v * 3),
            "revenue_jump": ("revenue_total_m", lambda v: v * 10),
            "operating_sum": ("operating_profit_loss_m", lambda v: v + 5),
            "balance_sheet": ("net_assets_m", lambda v: v + 9),
        }
        for rule, (field, change) in cases.items():
            club = copy.deepcopy(base)
            row = next(r for r in club["history"] if r["year"] == 2022)
            row[field] = change(row[field])
            self.assertIn(rule, {f.rule for f in fc.check_club(club)}, rule)


class DerivedFigures(SampleData):
    def test_every_declared_input_changes_its_figure(self):
        """DERIVED_FROM must list real inputs: blanking one changes the figure."""
        for slug, club_slug in (("championship", "kingsmere-united"), ("eredivisie", "fc-zandmeer")):
            league = self.league(slug)
            derived.apply_league(league)
            before = self.club(league, club_slug)
            for field, inputs in derived.DERIVED_FROM.items():
                if field.startswith("european_outlook.") and not before.get("european_outlook"):
                    continue
                for name in inputs:
                    changed = copy.deepcopy(league)
                    club = self.club(changed, club_slug)
                    max(club["history"], key=lambda r: r["year"])[name] = None
                    derived.apply_league(changed)
                    get = (lambda c, f: c["european_outlook"][f.split(".")[1]]) if "." in field else (lambda c, f: c[f])
                    self.assertNotEqual(get(before, field), get(club, field), f"{field} <- {name}")

    def test_wage_summary_reads_naturally(self):
        self.assertEqual(derived.wage_position_summary(1, 1),
                         "First in the table with the largest wage bill: exactly where its spending would put it.")
        self.assertIn("three places better", derived.wage_position_summary(2, 5))


class Assessments(SampleData):
    def test_sample_assessments_are_stamped(self):
        for slug in ("championship", "eredivisie"):
            for club in self.league(slug)["clubs"]:
                if club.get("narrative"):
                    self.assertTrue(ac.is_stamped_for_current_figures(club), club["club_slug"])

    def test_quoting_a_withheld_figure_takes_the_assessment_down(self):
        data = self.league("championship")
        club = self.club(data, "westmarsh-city")
        club["narrative"] = "Revenue of £2,024.0m is the largest in the league."
        self.save("championship", data)
        quiet(pf.publish, self.dir)
        club = self.club(self.league("championship"), "westmarsh-city")
        self.assertIsNone(club["narrative"])
        self.assertIn({"field": "narrative", "source": "calculated"}, club["excluded_figures"])
        down = self.review()["assessments"]
        self.assertEqual([d["club_slug"] for d in down], ["westmarsh-city"])
        self.assertIn("couldn't read reliably", down[0]["reason"])
        self.assertEqual(quiet(pf.check, self.dir), 0)

    def test_changed_figures_take_down_until_rewritten(self):
        data = self.league("championship")
        club = self.club(data, "brackwater-albion")
        club["narrative"] = "A well-run club with a strong balance sheet."
        self.save("championship", data)
        quiet(pf.publish, self.dir)  # accepted and stamped

        data = self.league("championship")
        club = self.club(data, "brackwater-albion")
        old_text = club["narrative"]
        club["league_position"] = 7  # the figures change underneath the text
        self.save("championship", data)
        quiet(pf.publish, self.dir)
        self.assertIsNone(self.club(self.league("championship"), "brackwater-albion")["narrative"])

        data = self.league("championship")  # putting the old text back keeps it down
        self.club(data, "brackwater-albion")["narrative"] = old_text
        self.save("championship", data)
        quiet(pf.publish, self.dir)
        self.assertIsNone(self.club(self.league("championship"), "brackwater-albion")["narrative"])

        data = self.league("championship")  # a rewrite goes back up
        self.club(data, "brackwater-albion")["narrative"] = "Seventh now, but the balance sheet is unchanged."
        self.save("championship", data)
        quiet(pf.publish, self.dir)
        club = self.club(self.league("championship"), "brackwater-albion")
        self.assertIsNotNone(club["narrative"])
        self.assertTrue(ac.is_stamped_for_current_figures(club))
        self.assertEqual(self.review()["assessments"], [])

    def test_years_and_positions_are_not_read_as_amounts(self):
        withheld = [{"value": 2024.0, "kind": "money"}, {"value": 7.0, "kind": "money"}]
        self.assertEqual(ac.quoted_figures("In 2024 the club finished 7th.", withheld), [])
        self.assertEqual(len(ac.quoted_figures("Revenue was £7m.", withheld)), 1)


class ReleaseGate(SampleData):
    def test_passes_after_publish(self):
        self.assertEqual(quiet(pf.check, self.dir), 0)

    def assert_gate_fails(self, slug, edit):
        data = self.league(slug)
        edit(data)
        self.save(slug, data)
        self.assertEqual(quiet(pf.check, self.dir), 1)

    def test_fails_when_a_withheld_figure_is_put_back(self):
        def edit(data):
            row = next(r for r in self.club(data, "westmarsh-city")["history"] if r["year"] == 2024)
            row["revenue_total_m"] = 2024.0
        self.assert_gate_fails("championship", edit)

    def test_fails_when_an_assessment_is_edited_without_publishing(self):
        self.assert_gate_fails("eredivisie", lambda d: self.club(d, "fc-zandmeer").update(narrative="Edited by hand."))

    def test_fails_when_a_worked_out_figure_is_edited(self):
        self.assert_gate_fails("eredivisie", lambda d: self.club(d, "sv-kanaalstad").update(risk_level="Critical"))


class Build(unittest.TestCase):
    def test_building_twice_gives_identical_files(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for d in (a, b):
                quiet(build_sample_data.build, Path(d))
                quiet(pf.publish, Path(d))
            for name in ("championship.json", "eredivisie.json", pf.REVIEW_NAME):
                self.assertEqual((Path(a) / name).read_text(encoding="utf-8"), (Path(b) / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
