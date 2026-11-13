# Quote quality daily snapshot

## Outcome

The daily basis build writes `data/csv/quote-quality.csv`.
The file preserves the current physical quote range behind each published mean.
The Radar uses the file to exclude mixed delivery terms and direction-ambiguous routes.

## Scope

- Reuse the physical indicators and location normalization used by the basis build.
- Export only the latest date required by each rebuilt futures reference.
- Preserve unrebuilt commodities during a filtered daily run.
- Classify rows as `single`, `consensus`, `source_dispersion`, or `mixed_delivery`.
- Treat delivery as mixed only when source labels prove both spot and dated delivery quotes.
- Fail closed in the Radar when the file, schema, date, location, or mean is incompatible.
- Keep the historical location ranking unchanged.

## Non-goals

- Do not change physical price aggregation or existing basis columns.
- Do not infer freight, executable volume, grade, taxes, or delivery terms absent from source labels.
- Do not publish the Site or update access controls.

## CSV contract

One row identifies `(commodity, date, location)`.

| Column | Meaning |
|---|---|
| `commodity` | Basis commodity slug. |
| `date` | ISO date used by the current basis snapshot. |
| `location` | Canonical basis location. |
| `n_quotes` | Count of source quote rows in the published mean. |
| `price_min_brl` | Minimum source quote after unit conversion. |
| `price_max_brl` | Maximum source quote after unit conversion. |
| `price_mean_brl` | Mean that must reconcile with `physical_price_brl`. |
| `price_range_brl` | `price_max_brl - price_min_brl`. |
| `classification` | One of the four declared quality classes. |
| `quote_types` | Sorted source-label types joined with `|`. |
| `physical_indicators` | Sorted source indicator slugs joined with `|`. |
| `source_labels` | Sorted raw source labels joined with `|`. |

## Route rules

1. Exclude a route when either leg is `mixed_delivery`.
2. Compute the signed range as `sell_min - buy_max` through `sell_max - buy_min`.
3. Exclude the route when the minimum is zero or negative.
4. Keep the route when the full range is positive.
5. Show the range when either leg has source dispersion.

## Acceptance criteria

- Fixed 2026-11-11 data excludes 67 soy routes for mixed delivery.
- The same data excludes 9 additional soy routes for ambiguous direction.
- The remaining soy route count is 503.
- Corn retains 385 routes when its quality rows require no exclusion.
- The two exposed top-60 ranges are 22 to 24 and 20 to 22 R$/sc.
- Unit tests cover all four classes, both-leg dispersion, zero crossing, missing files, and invalid schemas.
- ETL, Site, integration, independent audit, and local browser checks record reproducible evidence.

## Risks

- A label without an explicit term remains `unspecified` and cannot prove mixed delivery.
- A filtered run can preserve a stale row for another commodity. The Site date check rejects that row.
- A missing quality row excludes routes that depend on that location.
