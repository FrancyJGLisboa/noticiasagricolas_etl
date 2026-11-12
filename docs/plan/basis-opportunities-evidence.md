# Basis opportunities evidence

Status: complete

Environment: macOS, Python 3.13.12, branch `feat/basis-opportunities`.

Verification time: 2026-11-12 13:19:49 America/Sao_Paulo.

## Engineering evidence

| Criterion | Method | Result | Limits |
|---|---|---|---|
| Roll-aware and gap-aware calculations | `uv run pytest -q tests/test_basis_analytics.py tests/test_api.py::TestAnalyticsExtras::test_basis_opportunities_route tests/test_api.py::TestAnalyticsExtras::test_basis_percentile tests/test_api.py::TestAnalyticsExtras::test_hedge_fit_insufficient_history` | Pass. 10 tests passed in 3.10 seconds. | Synthetic cases do not cover every commodity schema. |
| Full regression suite | Create a temporary home with `catalog.yaml`, then run `HOME="$test_home" .venv/bin/pytest -q`. | Pass. 433 tests passed in 24.51 seconds. | 60 pre-existing warnings remain. One warning is an unregistered `live` mark. The other warnings use deprecated pandas day-of-year attributes. |
| Static checks | `uvx ruff check` on the new and changed analytics files. | Pass. | The command did not lint the complete existing repository. |
| Patch hygiene | `git diff --check` | Pass. | This checks whitespace only. |
| Dependency audit | `uvx pip-audit --path .venv/lib/python3.13/site-packages --skip-editable --progress-spinner off` | Pass. No known vulnerabilities found. | The audit skipped the editable local package. The first project-resolution audit failed because the temporary Python environment aborted during `ensurepip`. |

The full suite needs a temporary `HOME` because `config.py` resolves `catalog.yaml` under `~/noticiasagricolas_etl`. The isolated worktree does not exist at that path.

## Product evidence

Source snapshot: `origin/data` commit `3846e73133126a91233a0eeed6705faa255c4f19`.

The validation command extracted `csv/basis-soja.csv` and `csv/basis-stats.csv` with `git archive`. It then ran:

```bash
uv run python scripts/validate_basis_analytics.py <snapshot>/csv
```

Independent CSV results:

| Check | Result |
|---|---|
| Sorriso CBOT all-history percentile | 57.2 |
| Sorriso CBOT same-November percentile | 24.7 with 93 observations |
| Rio Verde CBOT all-history and seasonal percentiles | 49.5 and 24.7 |
| Paranaguá CBOT all-history and seasonal percentiles | 58.8 and 39.8 |
| Soy CBOT locations | 47 |
| Stale after 10 weekdays | 12 |
| Locations with fewer than 500 observations | 10 |
| Sorriso CBOT weekly USD hedge | beta 0.508, R-squared 0.266, 200 valid changes |
| Largest Sorriso B3 movements contaminated before filtering | 10 roll movements and 7 post-gap movements among the largest 30 |

The real-data API integration converted the same CSV to the repository basis schema and called the route with FastAPI `TestClient`:

```text
GET /v1/analytics/basis-opportunities
  ?commodity=soja
  &futures_indicator=soja-bolsa-de-chicago-cme-group
  &target_date=2026-11-11
```

Result:

```text
HTTP 200
35 active rows
12 stale exclusions
Sorriso percentile_all = 57.24
Sorriso percentile_season = 24.73
Sorriso primary USD hedge beta = 0.5076
Sorriso primary USD hedge R-squared = 0.2656
0 anomalies on a current roll or post-gap transition
```

## Acceptance-number discrepancy

The supplied reference calculation uses weekly resample labels to test gaps. Those labels are seven days apart even when the actual source observations are farther apart. It also reports BRL for Rio Verde CBOT.

That reference method reproduces these supplied results from commit `3846e73`:

- Paranaguá B3: beta 0.604 and R-squared 0.370 after exclusions.
- Rio Verde CBOT in BRL: beta 0.469 and R-squared 0.380 after exclusions.
- Sorriso CBOT in USD: beta 0.510 and R-squared 0.272 after exclusions.

The specification also requires a maximum seven-day gap between actual weekly observations and USD for CBOT. The implemented method therefore returns:

- Paranaguá B3: beta 0.620 and R-squared 0.385 with 34 rolls and 11 gaps removed.
- Rio Verde CBOT in USD: beta 0.539 and R-squared 0.407 with 35 rolls and 17 gaps removed.
- Sorriso CBOT in USD: beta 0.508 and R-squared 0.266 with 35 rolls and 16 gaps removed.

All tested R-squared values remain below 0.45. The qualitative conclusion remains a marginal or poor hedge.

## Experience evidence

- The API returns a descriptive interpretation for every active row.
- Tests reject buy, sell, hold, purchase, sale, and hold-back instructions in the basis interpretation.
- Each stale row includes its last date, weekday age, window count, and exclusion reason.
- The response states that quote counts are unavailable because the basis schema stores only the daily average.

## Known limits

- The repository does not store the number or dispersion of physical quotes behind a daily average.
- Freshness counts Monday through Friday. It does not use a Brazilian holiday calendar.
- This change does not restore removed B3 soybean dates.
- The anomaly output covers the current endpoint observation. It does not emit a historical alert series.
- The tests do not include live HTTP scraping or a deployed API process.
