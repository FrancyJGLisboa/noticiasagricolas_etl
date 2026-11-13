# Quote quality evidence

Status: COMPLETE for implementation and local verification.

## ETL

- `tests/test_quote_quality.py`: 11 focused tests pass.
- `tests/test_basis_builder.py`: the filtered build writes the daily quality artifact.
- Focused ETL result: 65 tests pass.
- Full ETL result: 452 tests pass and 2 unrelated metadata tests fail.
- Both failures use the hard-coded `/Users/francylisboacharuto/noticiasagricolas_etl/catalog.yaml`, which is absent from the data-branch worktree.

## Fixed 2026-11-11 snapshot

The generated artifact contains 64 rows:

| Commodity | Rows | Single | Consensus | Source dispersion | Mixed delivery |
|---|---:|---:|---:|---:|---:|
| Soja | 35 | 30 | 1 | 2 | 2 |
| Milho | 29 | 29 | 0 | 0 | 0 |

The Site route integration reports:

| Commodity | Visible routes | Mixed-delivery blocks | Ambiguous-direction blocks |
|---|---:|---:|---:|
| Soja | 503 | 67 | 9 |
| Milho | 385 | 0 | 0 |

The two source-dispersion routes inside the soy top 60 show these ranges:

- São Gabriel do Oeste/MS to Paranaguá/PR: 22 to 24 R$/sc.
- Maracaju/MS to Paranaguá/PR: 20 to 22 R$/sc.

## Site and independent checks

- Site unit tests: 26 pass.
- Site integration: PASS against the fixed snapshot.
- Semantic audit: PASS.
- Independent audit tests: 29 pass.
- Independent fixed-snapshot audit: `PASS_WITH_COMMERCIAL_LIMITS` with no numerical failures.
- Chrome local capture: 503 soy routes and 385 corn routes.
- Worker build and artifact validation: PASS.

The independent audit imports neither the ETL calculations nor the Site calculations.
It reconstructs physical quote groups from `soja.csv` and `milho.csv`.
It then compares every field in the generated `quote-quality.csv`.

## Remaining operational dependency

The data branch does not contain `quote-quality.csv` until the updated ETL runs and publishes its daily output.
The Site closes routes and keeps the location ranking available while the file is absent or incompatible.
