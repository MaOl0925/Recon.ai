# Club finance pipeline

Recon's Finances view reads the league files in `data/financial/`. Every figure on them passes through this pipeline first.

| File | What it does |
| --- | --- |
| `build_sample_data.py` | Builds the sample league files (fictional clubs and figures), then publishes them. |
| `derived_figures.py` | Works out ratios, the distress score, risk level, wage ranking, European outlook and labels, and declares which account figures each one reads. |
| `figure_checks.py` | The rules a believable figure must pass (no year read as money, no lost minus sign, sums that add up, a balance sheet that balances). |
| `assessment_checks.py` | Keeps each written assessment in step with its figures: fingerprints, and spotting quoted figures we couldn't read reliably. |
| `publish_figures.py` | Withholds failing figures, works everything out again, accepts or takes down assessments, writes `data/financial/figures-review.json`. `--check` is the release gate. |
| `test_financial.py` | Tests for all of the above. |

```bash
python scripts/financial/build_sample_data.py            # rebuild the sample data and publish it
python scripts/financial/publish_figures.py              # after any change to a league file
python scripts/financial/publish_figures.py --check      # the release gate (CI runs this)
python -m unittest discover -s scripts/financial -p "test_*.py"
```

Assessments are written by the `club-narratives` agent (`.claude/agents/club-narratives.md`), which runs `publish_figures.py` when it's done.

## Sample data

Every club and figure in `data/financial/` is fictional. This repository is public, and made-up accounts for real clubs would read as claims about real companies. Three clubs carry a deliberate misread so the checks have something to withhold: Westmarsh City (2024 revenue), Fennick Rovers (2023 net assets) and SC Duinwijk (2024 net result).

Real figures can replace the sample files in the same format. `figures-review.json` records the misread values that were withheld; with real data, keep that file out of this public repository.

Standard library only (Python 3.10+), so the release gate runs on a bare CI runner.
