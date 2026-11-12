"""Validate appended roll-adjusted columns against previous basis CSV files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

import pandas as pd

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


def _median_changes(
    frame: pd.DataFrame,
    *,
    location: str,
    futures_indicator: str,
) -> tuple[float, float, float, float]:
    series = frame[
        (frame["location"] == location)
        & (frame["futures_indicator"] == futures_indicator)
    ].copy()
    series["date"] = pd.to_datetime(series["date"])
    series = series.sort_values("date")
    series["raw_change"] = series["basis_brl"].diff().abs()
    series["adjusted_change"] = series["basis_brl_adj"].diff().abs()
    series["valid_gap_adjusted_change"] = (
        series["basis_brl"].diff() + series["roll_gap_brl"]
    ).abs()
    raw_roll = float(series.loc[series["roll"], "raw_change"].median())
    adjusted_roll = float(series.loc[series["roll"], "adjusted_change"].median())
    valid_gap_adjusted_roll = float(
        series.loc[
            series["roll"] & ~series["roll_gap_missing"],
            "valid_gap_adjusted_change",
        ].median()
    )
    adjusted_non_roll = float(
        series.loc[~series["roll"], "adjusted_change"].median()
    )
    return raw_roll, adjusted_roll, valid_gap_adjusted_roll, adjusted_non_roll


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

    print("MISSING_ROLL_GAPS")
    for path, frame in validated_files:
        missing = int((frame["roll"] & frame["roll_gap_missing"]).sum())
        rolls = int(frame["roll"].sum())
        print(f"{path.name} missing={missing} rolls={rolls}")

    print("NAMED_SERIES_MEDIAN_ABS_DAILY_CHANGE_BRL")
    named_series = [
        (
            "basis-milho.csv",
            "Rio Verde/GO",
            "milho-b3-prego-regular",
        ),
        (
            "basis-soja.csv",
            "Sorriso/MT",
            "soja-bolsa-de-chicago-cme-group",
        ),
    ]
    frames = {path.name: frame for path, frame in validated_files}
    for file_name, location, indicator in named_series:
        frame = frames.get(file_name)
        if frame is None:
            print(f"{file_name} {location} missing_file")
            failures += 1
            continue
        (
            raw_roll,
            adjusted_roll,
            valid_gap_adjusted_roll,
            adjusted_non_roll,
        ) = _median_changes(
            frame,
            location=location,
            futures_indicator=indicator,
        )
        print(
            f"{file_name} {location} {indicator} "
            f"raw_roll={raw_roll:.4f} adjusted_roll={adjusted_roll:.4f} "
            f"valid_gap_adjusted_roll={valid_gap_adjusted_roll:.4f} "
            f"adjusted_non_roll={adjusted_non_roll:.4f}"
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
