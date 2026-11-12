# Roll-adjusted basis plan

Status: partial

## Outcome

Append roll metadata and roll-adjusted basis columns to every materialized basis file.
Existing columns, values, rows, and contract choices must remain unchanged.

## Scope

- Detect each contract change inside a location and futures-reference series.
- Find the last common quote for the outgoing and incoming contracts.
- Limit the common-quote search to five source trading dates before the switch.
- Convert the futures gap to each supported basis unit.
- Anchor adjusted series on their latest observation and adjust earlier rows.
- Stop the backward adjustment at a roll with no valid gap.
- Append the new columns to Parquet and CSV output.
- Add a reproducible validation script and user documentation.

## Non-goals

- Do not change front-contract selection.
- Do not change B3 roll rules from commit `17a8778`.
- Do not fill, remove, reorder, or deduplicate basis dates.
- Do not change any existing basis value.
- Do not use adjusted levels for current-level percentiles.

## New columns

1. `roll`
2. `roll_gap_brl`
3. `roll_gap_cents_bu`
4. `roll_gap_missing`
5. `basis_brl_adj`
6. `basis_usd_adj`
7. `basis_centavos_sc_adj`
8. `basis_cents_bu_adj`

## Decisions

1. The first observation in a series is not a roll.
2. A source trading date is a distinct date with a quote for the futures reference.
3. A valid gap date is earlier than the location's contract-switch date.
4. Both contracts must have a non-null quote on the same valid gap date.
5. The BRL gap uses PTAX from the valid gap date when the pair needs PTAX.
6. CBOT `roll_gap_cents_bu` is the raw contract-price difference times 100.
7. Each adjusted unit subtracts later roll gaps expressed in that unit.
8. A missing roll gap makes every adjusted value before that roll null.
9. The roll row itself remains adjustable because its contract is already current.

## Risks and controls

| Risk | Control |
|---|---|
| Wrong gap sign creates a larger step | Test a roll to a dearer contract and verify continuity. |
| A calendar-day search miscounts holidays | Use the last five distinct futures source dates. |
| A missing PTAX creates a false zero gap | Mark the gap missing. |
| Multiple rolls apply the wrong cumulative shift | Test two rolls with different gaps. |
| A schema change alters existing CSV cells | Hash raw cell text for all original columns. |
| Existing B3 selection changes indirectly | Keep `select_front_month` unchanged and run its regression tests. |

## Acceptance criteria

- All old CSV cells match the data-commit input text for every original column.
- The latest adjusted basis equals the raw basis in every series.
- Roll-day adjusted changes approach non-roll changes in the named examples.
- Every output reports its count of missing roll gaps.
- Tests cover one roll, two rolls, a missing gap, and no roll.
- The full test suite, lint, diff check, and dependency audit pass.

## Verification commands

```bash
pytest -q tests/test_roll_adjustment.py tests/test_basis_builder.py
pytest -q
python scripts/validate_roll_adjusted_basis.py <old-csv-dir> <new-csv-dir>
ruff check src tests scripts/validate_roll_adjusted_basis.py
git diff --check
pip-audit
```

## Documentation rule

Adjusted levels are analytical series. They are not traded prices.
Current-level percentiles must continue to use unadjusted basis columns.
