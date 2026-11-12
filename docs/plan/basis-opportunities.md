# Basis opportunities implementation plan

Status: complete

## Outcome

Add one API endpoint that ranks current basis conditions by location and futures reference. The endpoint must separate market signals from contract rolls, data gaps, and foreign exchange.

## Scope

- Add `GET /v1/analytics/basis-opportunities`.
- Add reusable roll-aware and gap-aware basis signal calculations.
- Add seasonal and all-history percentiles to the existing basis percentile service.
- Make the hedge-fit service exclude contract rolls and excessive gaps.
- Use USD price changes for CBOT hedge fits and `basis_cents_bu` for CBOT basis signals.
- Add coverage, freshness, exclusion details, tests, validation, and data caveat documentation.
- Replace trade instructions in the basis interpretation text with descriptions.

## Non-goals

- Do not repair or rebuild source CSV or Parquet data.
- Do not infer `n_quotes`. The current basis schema stores only the daily average.
- Do not add buy, sell, or hold recommendations.
- Do not publish, push, or merge the branch.

## Decisions

1. The endpoint uses the latest date in the filtered dataset as its default target date.
2. `days_since_last` counts weekdays and does not use a Brazilian holiday calendar.
3. A row is stale when `days_since_last` is greater than 10.
4. Seasonal history uses the same calendar month in the trailing window.
5. A seasonal percentile needs at least 30 observations.
6. Daily changes require the same contract and a gap of at most 5 calendar days.
7. Weekly changes require the same contract and a gap of at most 7 calendar days between actual observation dates.
8. A contract change takes precedence over a gap when classifying a rejected difference.
9. CBOT basis changes and anomaly scores use `basis_cents_bu`. Historical acceptance percentiles remain in `basis_brl` and the endpoint also exposes FX-separated percentiles.
10. CBOT hedge fits use physical and futures prices divided by PTAX. The response also reports a separate BRL fit.
11. The ranking sorts the seasonal percentile from high to low. Rows without a seasonal percentile follow, sorted by the all-history percentile.
12. The endpoint returns an anomaly only when the target observation has a valid daily change.

## Risks and controls

| Risk | Control |
|---|---|
| Contract changes create false basis moves | Reject differences across contracts and report the rejected count. |
| Holidays or missing data create false moves | Reject daily gaps over 5 days and weekly gaps over 7 days. |
| CBOT analytics mix basis and BRL/USD movement | Use cents per bushel for basis signals and USD prices for the primary hedge fit. |
| Old locations distort the ranking | Exclude rows older than 10 weekdays and list each exclusion. |
| Seasonal samples are too small | Return null with a reason when the sample has fewer than 30 observations. |
| Daily quote averaging hides source dispersion | Document the limitation. Do not expose a fabricated quote count. |

## Acceptance criteria

- The endpoint includes current basis, two percentiles, change, anomaly, hedge quality, coverage, and freshness.
- The endpoint lists stale exclusions.
- No anomaly is flagged on a contract-roll date or after a gap over 5 calendar days.
- Hedge fit reports roll and gap rejection counts.
- CBOT results identify their USD or cents-per-bushel signal units.
- Basis interpretation text contains no buy, sell, or hold instruction.
- API integration tests cover the complete route.
- The supplied validation script runs against an extracted `origin/data` snapshot.
- The evidence log records exact commands, results, discrepancies, and limits.

## Verification commands

```bash
pytest -q tests/test_basis_analytics.py tests/test_api.py
pytest -q
python3 scripts/validate_basis_analytics.py <csv-folder>
```

## Open questions

- The supplied acceptance date is 2026-11-11. Local CSV mirrors may be older. Validation must use commit `3846e73` from `origin/data`.
- Business-day freshness excludes weekends only because the repository has no exchange holiday calendar.
