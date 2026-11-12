# Basis opportunities analytics

`GET /v1/analytics/basis-opportunities` ranks basis conditions for one commodity. It returns active rows and stale exclusions.

## Signal rules

- `percentile_all` compares the current basis with the trailing history window.
- `percentile_season` compares it with observations from the same calendar month.
- Seasonal results need at least 30 observations.
- Percentiles use `basis_brl` for historical continuity.
- CBOT changes and anomaly scores use `basis_cents_bu`. Other references use `basis_brl`.
- CBOT rows also expose FX-separated signal percentiles.
- Daily changes require the same futures contract and a maximum gap of 5 calendar days.
- `change_5d` spans observations in the last 5 calendar days. It is null if that span contains an invalid transition.
- Weekly hedge changes require the same futures contract and a maximum gap of 7 calendar days.
- CBOT hedge fits use USD prices. The service reports a separate BRL fit.
- The endpoint excludes a row after more than 10 weekdays without data.

The endpoint uses weekdays for freshness. It does not use a Brazilian holiday calendar.

## Data caveats

### Daily quote averaging

The basis build averages multiple physical quotes for one normalized location and date. For example, Sorriso can contain both `Disponível` and `Balcão` quotes with a large spread. The stored basis row contains the average and does not preserve the input quote count. The endpoint does not expose `n_quotes` because the current schema cannot support that value.

### B3 soybean coverage

The B3 rollback correction removed dates where the selected current contract quote was absent. This affects about 180 days per location in the validated data. A later data repair can restore a date only when an authoritative contract quote exists. Prefer the CBOT reference for soybean analysis until the B3 series is repaired and validated.

### Holiday and source gaps

Long gaps can create one-day steps that do not represent one trading session. The analytics reject daily changes over 5 calendar days. They reject weekly changes over 7 calendar days between actual observations.

## Interpretation limit

The response describes the observed distribution and hedge fit. It does not recommend a trade. A trade recommendation needs a historical test with transaction, freight, storage, and financing costs.
