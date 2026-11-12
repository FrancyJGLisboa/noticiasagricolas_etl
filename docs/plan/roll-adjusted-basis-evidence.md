# Roll-adjusted basis evidence

Status: partial

Recorded: 2026-11-12 13:40:47 -03

Data input: `origin/data` commit `3846e73133126a91233a0eeed6705faa255c4f19`

## Engineering verification

| Criterion | Method | Result | Limits |
|---|---|---|---|
| One roll, two rolls, missing gap, no roll, and CBOT units | `pytest -q tests/test_roll_adjustment.py tests/test_basis_builder.py` | Pass, 59 tests | Synthetic fixtures do not cover every source format. |
| Full regression suite | `HOME=/tmp/roll-adjusted-test-home uv run python -m pytest -q` | Pass, 438 tests | 60 existing warnings remain. |
| Changed-file lint | `uvx ruff check` on changed Python files | Pass | The repository has unrelated pre-existing lint findings. |
| Patch whitespace | `git diff --check` | Pass | None. |
| Dependency audit | `uv run --with pip-audit pip-audit` | Pass, no known vulnerabilities | The local package is not published on PyPI. |
| Existing B3 contract selection | No diff in `basis/calculator.py`; full builder regression tests | Pass | This task does not revalidate exchange rules independently. |

## Data rebuild

The validation converted the seven raw CSV files from data commit `3846e73` to temporary Parquet.
It rebuilt all nine configured basis pairs with the branch code.

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

## Latest anchor

Every raw and adjusted unit matched on the latest row of every series.
The validator reported zero failures for all six files.

## Missing roll gaps

| File | Missing gaps | Rolls |
|---|---:|---:|
| basis-algodao.csv | 2 | 76 |
| basis-boi-gordo.csv | 0 | 379 |
| basis-cafe.csv | 106 | 414 |
| basis-milho.csv | 71 | 2,417 |
| basis-soja.csv | 297 | 3,343 |
| basis-trigo.csv | 6 | 301 |

## Named-series check

| Series | Raw roll median | Materialized adjusted roll median | Valid-gap roll median | Adjusted non-roll median |
|---|---:|---:|---:|---:|
| Rio Verde/GO corn vs B3 | 2.8300 | null | 0.6850 | 0.5400 |
| Sorriso/MT soy vs CBOT | 2.1151 | 1.9991 | 1.9991 | 1.4881 |

Rio Verde has one missing roll gap on 2026-09-24.
The source has no common quote date for contracts 2026-09 and 2026-11.
The requested missing-gap rule makes all earlier adjusted values null.
The 40 rolls with valid gaps have a local adjusted median of 0.6850.

Sorriso has no missing roll gaps.
The specified formula and same-day source gaps produce a median of 1.9991.
This is below the raw 2.1151 median but above the requested value near 1.5.

## Remaining decision

The implementation follows the requested formula and missing-gap rule.
The two named acceptance targets cannot both appear in the materialized series on data commit `3846e73`.
Changing this result requires a different missing-gap policy or a different adjustment formula.
