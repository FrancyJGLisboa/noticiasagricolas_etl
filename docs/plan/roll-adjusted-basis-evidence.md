# Roll-adjusted basis evidence

Status: complete

Recorded: 2026-11-12 14:33:47 -03

Data input: `origin/data` commit `3846e73133126a91233a0eeed6705faa255c4f19`

## Engineering verification

| Criterion | Method | Result | Limits |
|---|---|---|---|
| Roll and segment behavior | `pytest -q tests/test_roll_adjustment.py tests/test_basis_builder.py` | Pass, 60 tests | Synthetic fixtures do not cover every source format. |
| Full regression suite | `HOME=/tmp/roll-adjusted-test-home .venv/bin/python -m pytest -q` | Pass, 439 tests | 60 existing warnings remain. |
| Changed-file lint | `uvx ruff check` on changed Python files | Pass | The repository has unrelated pre-existing lint findings. |
| Patch whitespace | `git diff --check` | Pass | None. |
| Dependency audit | `uvx pip-audit --path .venv/lib/python3.13/site-packages` | Pass, no known vulnerabilities | The local package is not published on PyPI. |
| Existing B3 contract selection | No diff in `basis/calculator.py`; full builder regression tests | Pass | This task does not change or independently revalidate exchange rules. |

## Data rebuild

The validation converted seven raw CSV files from data commit `3846e73` to temporary Parquet.
It rebuilt all nine configured basis pairs.

| Pair | Rows |
|---|---:|
| algodao-nybot | 3,512 |
| boi-gordo-b3 | 7,699 |
| cafe-b3 | 7,842 |
| cafe-nybot | 10,460 |
| milho-b3 | 51,419 |
| milho-cbot | 50,790 |
| soja-b3 | 48,834 |
| soja-cbot | 55,035 |
| trigo-cbot | 14,128 |

## Existing-column hashes

The validator hashes exact CSV cell text for every original column and row.

| File | Rows | Match | SHA-256 |
|---|---:|---|---|
| basis-algodao.csv | 3,512 | true | `1386d51bb7878bb5bbaad09601758c6ee486285041338c9c36a81b58e54b9cd4` |
| basis-boi-gordo.csv | 7,699 | true | `0c2f15be04041ffdb7ff95b4f4fcaa74d1b3cf653eab794145efe2e1a12e1f9e` |
| basis-cafe.csv | 18,302 | true | `2454793db20b7bcb672f3ad3f7325f3cf4c9cebf0bd23ac7a44e6022bb34f58a` |
| basis-milho.csv | 102,209 | true | `95f9eea90ec0f11a558e7ced92d0cbc857b7b9fe91700ed115d98023cc3daa04` |
| basis-soja.csv | 103,869 | true | `f974984ba1baf95f915f24ca04f7eb507276cc185f021599c4f975abdea462f7` |
| basis-trigo.csv | 14,128 | true | `11a355d94b411f5d1ef2d260aa2e2fd66d39028963525ae5d60cf29f8b86c909` |

## Anchors and null coverage

Every raw and adjusted unit matched on the latest row of every series.
All six files reported zero latest-anchor failures.

The raw and adjusted null masks also matched for every unit.
A missing roll gap created no new null values.

## Missing roll gaps

| File | Missing | Rolls | Rate | B3 selector-removed days | Other reason |
|---|---:|---:|---:|---:|---:|
| basis-algodao.csv | 2 | 76 | 2.63% | 0 | 2 |
| basis-boi-gordo.csv | 0 | 379 | 0.00% | 0 | 0 |
| basis-cafe.csv | 106 | 414 | 25.60% | 104 | 2 |
| basis-milho.csv | 71 | 2,417 | 2.94% | 32 | 39 |
| basis-soja.csv | 297 | 3,343 | 8.88% | 166 | 131 |
| basis-trigo.csv | 6 | 301 | 1.99% | 0 | 6 |

The classifier examines each missing roll at row level.
It rebuilds the B3 front series with the unchanged contract policy.
A row enters `B3 selector-removed days` when at least one raw futures date lies between the adjacent basis observations but is absent from the selected front series.
All other missing gaps enter `Other reason`.

For coffee, 104 of 106 missing gaps follow B3 selector-removed dates.
The remaining two are NYBOT gaps.
For soybeans, 166 of 297 follow B3 selector-removed dates.
The other 131 comprise 92 B3 gaps without such a removed surrounding date and 39 CBOT gaps.

## Calendar-day matched changes

The comparison uses `basis_brl_adj` changes.
It matches roll and non-roll observations by exact elapsed calendar days.
The non-roll median uses weights that reproduce the roll observations' calendar-day mix.

| File | Futures reference | Roll median | Matched non-roll median | Matched rolls / all rolls |
|---|---|---:|---:|---:|
| basis-algodao.csv | algodao-bolsa-de-nova-iorque-nybot | 3.1336 | 3.1837 | 74 / 76 |
| basis-boi-gordo.csv | boi-gordo-b3-prego-regular | 2.2000 | 1.5000 | 379 / 379 |
| basis-cafe.csv | cafe-arabica-4-5-b3-prego-regular | 15.1509 | 20.2886 | 113 / 197 |
| basis-cafe.csv | cafe-bolsa-de-nova-iorque-nybot | 11.5500 | 11.6200 | 215 / 217 |
| basis-milho.csv | milho-b3-prego-regular | 0.7100 | 0.6200 | 1,307 / 1,320 |
| basis-milho.csv | milho-bolsa-de-chicago-cme-group | 0.6594 | 0.7243 | 1,084 / 1,097 |
| basis-soja.csv | soja-b3-pregao-regular | 1.4177 | 1.2761 | 1,414 / 1,626 |
| basis-soja.csv | soja-bolsa-de-chicago-cme-group | 1.3129 | 1.1765 | 1,694 / 1,717 |
| basis-trigo.csv | trigo-bolsa-de-chicago-cme-group | 1.5785 | 1.0660 | 294 / 301 |

## Declared limits

- The reason classifier identifies dates removed by the unchanged B3 selector. It does not claim that every such date had a physical quote for every location.
- `Other reason` combines B3 source-overlap failures and non-B3 source-overlap failures.
- Rare calendar-day spans without a non-roll counterpart are excluded from the matched median and reported as unmatched.
- The validator does not widen the five-source-day gap window and does not fill or remove observations.
