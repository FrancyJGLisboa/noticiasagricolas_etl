"""Validate appended roll-adjusted columns against previous basis CSV files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

from noticiasagricolas_etl.basis.calculator import select_front_month
from noticiasagricolas_etl.basis_config import BASIS_PAIRS

NEW_COLUMNS = [
    "roll",
    "roll_gap_brl",
    "roll_gap_cents_bu",
    "roll_gap_missing",
    "basis_brl_adj",
    "basis_usd_adj",
    "basis_centavos_sc_adj",
    "basis_cents_bu_adj",
]

LATEST_PAIRS = [
    ("basis_brl", "basis_brl_adj"),
    ("basis_usd", "basis_usd_adj"),
    ("basis_centavos_sc", "basis_centavos_sc_adj"),
    ("basis_cents_bu", "basis_cents_bu_adj"),
]


def _cell_hash(path: Path, selected_columns: list[str]) -> tuple[str, int]:
    """Hash exact CSV cell text for selected columns in source row order."""
    digest = hashlib.sha256()
    row_count = 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        positions = [header.index(column) for column in selected_columns]
        for value in selected_columns:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        for row in reader:
            row_count += 1
            for position in positions:
                encoded = row[position].encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
    return digest.hexdigest(), row_count


def _header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _values_equal(raw: object, adjusted: object) -> bool:
    if pd.isna(raw) and pd.isna(adjusted):
        return True
    if pd.isna(raw) or pd.isna(adjusted):
        return False
    return math.isclose(float(raw), float(adjusted), rel_tol=1e-12, abs_tol=1e-12)


def _latest_failures(frame: pd.DataFrame) -> int:
    ordered = frame.assign(date=pd.to_datetime(frame["date"])).sort_values("date")
    latest = ordered.groupby(
        ["location", "futures_indicator"],
        dropna=False,
        sort=False,
    ).tail(1)
    failures = 0
    for raw_column, adjusted_column in LATEST_PAIRS:
        failures += sum(
            not _values_equal(raw, adjusted)
            for raw, adjusted in zip(
                latest[raw_column],
                latest[adjusted_column],
                strict=True,
            )
        )
    return failures


def _adjusted_null_mask_failures(frame: pd.DataFrame) -> int:
    return sum(
        int((frame[raw_column].notna() != frame[adjusted_column].notna()).sum())
        for raw_column, adjusted_column in LATEST_PAIRS
    )


def _weighted_median(values: pd.Series, weights: pd.Series) -> float:
    if values.empty:
        return float("nan")
    order = np.argsort(values.to_numpy(dtype=float), kind="stable")
    sorted_values = values.to_numpy(dtype=float)[order]
    sorted_weights = weights.to_numpy(dtype=float)[order]
    cutoff = sorted_weights.sum() / 2.0
    position = int(np.searchsorted(np.cumsum(sorted_weights), cutoff, side="left"))
    return float(sorted_values[position])


def _matched_change_metrics(
    frame: pd.DataFrame,
    futures_indicator: str,
) -> dict[str, object]:
    """Compare roll changes with non-roll changes matched by calendar-day span."""
    series = frame[frame["futures_indicator"] == futures_indicator].copy()
    series["date"] = pd.to_datetime(series["date"])
    series = series.sort_values(["location", "date"], kind="stable")
    groups = series.groupby("location", dropna=False, sort=False)
    series["previous_date"] = groups["date"].shift()
    series["calendar_days"] = (series["date"] - series["previous_date"]).dt.days
    series["adjusted_change"] = groups["basis_brl_adj"].diff().abs()
    series = series.dropna(subset=["calendar_days", "adjusted_change"])
    series = series[series["calendar_days"] > 0].copy()

    roll = series[series["roll"]].copy()
    non_roll = series[~series["roll"]].copy()
    roll_counts = roll.groupby("calendar_days").size()
    non_roll_counts = non_roll.groupby("calendar_days").size()
    matched_days = roll_counts.index.intersection(non_roll_counts.index)
    matched_roll = roll[roll["calendar_days"].isin(matched_days)]
    matched_non_roll = non_roll[non_roll["calendar_days"].isin(matched_days)].copy()
    weights_by_day = {
        day: float(roll_counts.loc[day]) / float(non_roll_counts.loc[day])
        for day in matched_days
    }
    matched_non_roll["match_weight"] = matched_non_roll["calendar_days"].map(
        weights_by_day
    )
    gap_mix = ",".join(
        f"{int(day)}d:{int(roll_counts.loc[day])}"
        for day in sorted(roll_counts.index)
    )

    return {
        "roll_median": (
            float(matched_roll["adjusted_change"].median())
            if not matched_roll.empty
            else float("nan")
        ),
        "matched_non_roll_median": _weighted_median(
            matched_non_roll["adjusted_change"],
            matched_non_roll["match_weight"],
        ),
        "roll_n": len(roll),
        "matched_roll_n": len(matched_roll),
        "unmatched_roll_n": len(roll) - len(matched_roll),
        "gap_mix": gap_mix,
    }


def _classify_missing_rolls(
    basis_path: Path,
    frame: pd.DataFrame,
    raw_csv_dir: Path,
) -> dict[str, int]:
    """Classify missing gaps by evidence of B3 selector-removed source dates."""
    commodity = basis_path.stem.removeprefix("basis-")
    raw_path = raw_csv_dir / f"{commodity}.csv"
    if not raw_path.exists():
        raise FileNotFoundError(f"missing raw source file: {raw_path}")

    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values(
        ["location", "futures_indicator", "date"],
        kind="stable",
    )
    groups = work.groupby(
        ["location", "futures_indicator"],
        dropna=False,
        sort=False,
    )
    work["previous_date"] = groups["date"].shift()
    missing = work[work["roll"] & work["roll_gap_missing"]].copy()
    raw = pd.read_csv(raw_path, low_memory=False)
    raw["date"] = pd.to_datetime(raw["date"])

    removed_by_b3_fix = 0
    for indicator, rows in missing.groupby("futures_indicator", sort=False):
        config = next(
            (pair for pair in BASIS_PAIRS if pair.futures_indicator == indicator),
            None,
        )
        if config is None or config.contract_roll_policy == "nearest_available":
            continue
        futures = raw[
            (raw["indicator"] == indicator)
            & (raw["measure"] == "price")
            & raw["contract"].notna()
            & raw["value"].notna()
        ][["date", "contract", "value"]].rename(
            columns={"value": "futures_price_raw"}
        )
        front = select_front_month(
            futures,
            contract_roll_policy=config.contract_roll_policy,
        )
        raw_dates = set(pd.to_datetime(futures["date"].unique()))
        selected_dates = set(pd.to_datetime(front["date"].unique()))
        for row in rows.itertuples(index=False):
            has_removed_surrounding_date = any(
                row.previous_date < source_date < row.date
                and source_date not in selected_dates
                for source_date in raw_dates
            )
            removed_by_b3_fix += int(has_removed_surrounding_date)

    total = len(missing)
    return {
        "missing": total,
        "b3_removed_days": removed_by_b3_fix,
        "other_reason": total - removed_by_b3_fix,
    }


def validate(old_dir: Path, new_dir: Path) -> int:
    failures = 0
    print("EXISTING_COLUMN_HASHES")
    validated_files: list[tuple[Path, pd.DataFrame]] = []
    for old_path in sorted(old_dir.glob("basis-*.csv")):
        old_columns = _header(old_path)
        if "futures_contract" not in old_columns or "basis_brl" not in old_columns:
            continue
        new_path = new_dir / old_path.name
        if not new_path.exists():
            print(f"{old_path.name} missing_new_file")
            failures += 1
            continue
        new_columns = _header(new_path)
        missing_columns = [column for column in NEW_COLUMNS if column not in new_columns]
        if missing_columns:
            print(f"{old_path.name} missing_columns={','.join(missing_columns)}")
            failures += 1
            continue
        if new_columns[: len(old_columns)] != old_columns:
            print(f"{old_path.name} original_column_order_changed")
            failures += 1
            continue

        old_hash, old_rows = _cell_hash(old_path, old_columns)
        new_hash, new_rows = _cell_hash(new_path, old_columns)
        match = old_hash == new_hash and old_rows == new_rows
        print(
            f"{old_path.name} match={str(match).lower()} rows={new_rows} "
            f"old={old_hash} new={new_hash}"
        )
        failures += int(not match)
        validated_files.append((new_path, pd.read_csv(new_path, low_memory=False)))

    print("LATEST_ANCHOR")
    for path, frame in validated_files:
        latest_failures = _latest_failures(frame)
        print(f"{path.name} failures={latest_failures}")
        failures += int(latest_failures > 0)

    print("ADJUSTED_NULL_MASK")
    for path, frame in validated_files:
        null_mask_failures = _adjusted_null_mask_failures(frame)
        print(f"{path.name} failures={null_mask_failures}")
        failures += int(null_mask_failures > 0)

    print("MISSING_ROLL_GAPS")
    for path, frame in validated_files:
        missing = int((frame["roll"] & frame["roll_gap_missing"]).sum())
        rolls = int(frame["roll"].sum())
        rate = missing / rolls * 100.0 if rolls else 0.0
        print(f"{path.name} missing={missing} rolls={rolls} rate={rate:.2f}%")

    print("MISSING_ROLL_GAP_CLASSIFICATION")
    for path, frame in validated_files:
        classification = _classify_missing_rolls(path, frame, old_dir)
        print(
            f"{path.name} missing={classification['missing']} "
            f"b3_removed_days={classification['b3_removed_days']} "
            f"other_reason={classification['other_reason']}"
        )

    print("CALENDAR_DAY_MATCHED_MEDIAN_ABS_CHANGE_BRL")
    for path, frame in validated_files:
        for indicator in sorted(frame["futures_indicator"].dropna().unique()):
            metrics = _matched_change_metrics(frame, str(indicator))
            print(
                f"{path.name} {indicator} "
                f"roll={metrics['roll_median']:.4f} "
                f"matched_non_roll={metrics['matched_non_roll_median']:.4f} "
                f"roll_n={metrics['roll_n']} "
                f"matched_roll_n={metrics['matched_roll_n']} "
                f"unmatched_roll_n={metrics['unmatched_roll_n']} "
                f"roll_gap_days={metrics['gap_mix']}"
            )

    print(f"RESULT failures={failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("old_csv_dir", type=Path)
    parser.add_argument("new_csv_dir", type=Path)
    args = parser.parse_args()
    return validate(args.old_csv_dir, args.new_csv_dir)


if __name__ == "__main__":
    raise SystemExit(main())
