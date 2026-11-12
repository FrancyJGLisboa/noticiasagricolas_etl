#!/usr/bin/env python3
"""Independently check basis percentiles, hedge fits, anomalies, and coverage.

Run:
    python3 scripts/validate_basis_analytics.py <csv-folder>

The script reads the flat CSV outputs. It does not call the API services.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

CBOT = "soja-bolsa-de-chicago-cme-group"
B3 = "soja-b3-pregao-regular"


def fit(frame: pd.DataFrame) -> tuple[float, float, int] | None:
    """Return beta, R-squared, and observation count."""
    clean = frame.dropna()
    if len(clean) < 2 or float(clean["f"].var(ddof=1)) == 0:
        return None
    beta = float(clean[["f", "p"]].cov().iloc[0, 1] / clean["f"].var(ddof=1))
    correlation = float(clean["f"].corr(clean["p"]))
    return round(beta, 3), round(correlation**2, 3), len(clean)


def weekly_fit(
    frame: pd.DataFrame,
    *,
    use_usd: bool,
) -> tuple[tuple[float, float, int] | None, dict[str, int]]:
    """Apply the service rule to actual weekly observation dates."""
    work = frame.sort_values("date").copy()
    work["observation_date"] = work["date"]
    weekly = (
        work.set_index("date")
        .resample("W-SUN")
        .last()
        .dropna(subset=["physical_price_brl", "futures_price_brl"])
    )
    if use_usd:
        weekly["p_level"] = weekly["physical_price_brl"] / weekly["ptax"]
        weekly["f_level"] = weekly["futures_price_brl"] / weekly["ptax"]
    else:
        weekly["p_level"] = weekly["physical_price_brl"]
        weekly["f_level"] = weekly["futures_price_brl"]

    roll = weekly["futures_contract"].ne(weekly["futures_contract"].shift())
    has_previous = weekly["observation_date"].shift().notna()
    roll = roll & has_previous
    gap_days = (weekly["observation_date"] - weekly["observation_date"].shift()).dt.days
    gap = has_previous & ~roll & (gap_days > 7)
    valid = has_previous & ~roll & ~gap & gap_days.between(1, 7)
    differences = pd.DataFrame(
        {
            "p": weekly["p_level"].diff().where(valid),
            "f": weekly["f_level"].diff().where(valid),
        }
    )
    return fit(differences), {
        "n_dropped_roll": int(roll.sum()),
        "n_dropped_gap": int(gap.sum()),
    }


def percentile_report(data: pd.DataFrame) -> None:
    print("== Percentile: trailing five years and same calendar month")
    for location in ["Sorriso/MT", "Rio Verde/GO", "Porto Paranaguá/PR"]:
        rows = data[
            (data["location"] == location) & (data["futures_indicator"] == CBOT)
        ]
        if rows.empty:
            print(f"{location:22s} no data")
            continue
        rows = rows.sort_values("date")
        target = rows.iloc[-1]
        window = rows[rows["date"] >= target["date"] - pd.DateOffset(years=5)]
        value = float(target["basis_brl"])
        same_month = window[window["date"].dt.month == target["date"].month]
        percentile_all = float((window["basis_brl"] <= value).mean() * 100)
        percentile_season = float((same_month["basis_brl"] <= value).mean() * 100)
        print(
            f"{location:22s} {target['date'].date()} "
            f"all={percentile_all:.1f} season={percentile_season:.1f} "
            f"n_season={len(same_month)}"
        )


def hedge_report(data: pd.DataFrame) -> None:
    print("== Weekly hedge fit after contract-roll and actual-gap exclusions")
    for location in ["Sorriso/MT", "Rio Verde/GO", "Porto Paranaguá/PR"]:
        for future in [CBOT, B3]:
            rows = data[
                (data["location"] == location) & (data["futures_indicator"] == future)
            ]
            if rows.empty:
                continue
            cutoff = rows["date"].max() - pd.DateOffset(years=5)
            rows = rows[rows["date"] >= cutoff]
            metric, counts = weekly_fit(rows, use_usd=future == CBOT)
            print(f"{location:22s} {future:38s} fit={metric} drops={counts}")


def anomaly_report(data: pd.DataFrame) -> None:
    print("== Top daily basis movements contaminated by rolls or gaps")
    for location in ["Sorriso/MT", "Rio Verde/GO"]:
        for future in [CBOT, B3]:
            rows = data[
                (data["location"] == location) & (data["futures_indicator"] == future)
            ]
            if rows.empty:
                continue
            rows = rows.sort_values("date").set_index("date")
            value_column = "basis_cents_bu" if future == CBOT else "basis_brl"
            change = rows[value_column].diff()
            zscore = (change - change.rolling(60).mean()) / change.rolling(60).std()
            roll = rows["futures_contract"].ne(rows["futures_contract"].shift())
            gap = rows.index.to_series().diff().dt.days > 5
            top = zscore.abs().nlargest(30).index
            print(
                f"{location:14s} {future:38s} "
                f"roll={int(roll.loc[top].sum())} gap={int(gap.loc[top].sum())}"
            )


def coverage_report(data: pd.DataFrame) -> None:
    print("== Soy CBOT coverage")
    coverage = (
        data[data["futures_indicator"] == CBOT]
        .groupby("location")["date"]
        .agg(["min", "max", "count"])
    )
    anchor = data["date"].max()
    cutoff = anchor - pd.offsets.BDay(10)
    stale = coverage["max"] < cutoff
    print(
        f"anchor={anchor.date()} locations={len(coverage)} "
        f"stale_after_10_weekdays={int(stale.sum())} fewer_than_500={int((coverage['count'] < 500).sum())}"
    )
    if stale.any():
        print("stale_locations=" + ", ".join(coverage.index[stale].tolist()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_folder", type=Path)
    args = parser.parse_args()
    path = args.csv_folder / "basis-soja.csv"
    if not path.is_file():
        parser.error(f"missing {path}")

    data = pd.read_csv(path, low_memory=False)
    data["date"] = pd.to_datetime(data["date"])
    print(f"source={path} rows={len(data)} max_date={data['date'].max().date()}")
    percentile_report(data)
    hedge_report(data)
    anomaly_report(data)
    coverage_report(data)


if __name__ == "__main__":
    main()
