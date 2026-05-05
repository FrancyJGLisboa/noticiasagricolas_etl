"""Viz #3 — Companion KPI table per praça.

Computes per-location stats (today, d-1, w-1, m-1, mean 3y/5y, min/max 5y,
percentile today, n_obs 5y) and writes CSV. Reused by multi_location.py for
the embedded HTML table subplot.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..basis_config import BasisPairConfig
from ..config import CSV_DIR

logger = logging.getLogger(__name__)


STATS_COLUMNS = [
    "location",
    "state",
    "basis_today",
    "basis_d1",
    "basis_w1",
    "basis_m1",
    "mean_3y",
    "mean_5y",
    "min_5y",
    "max_5y",
    "pctile_today",
    "n_obs_5y",
]


def _nearest_value(loc_df: pd.DataFrame, target_date: pd.Timestamp) -> float:
    """Return the basis value at-or-before target_date; NaN if none."""
    sub = loc_df[loc_df["date"] <= target_date]
    if sub.empty:
        return np.nan
    return float(sub.iloc[-1]["value"])


def _percentile(values: pd.Series, x: float) -> float:
    """Return the percentile of x within values (0-100). NaN if values empty or x NaN."""
    clean = values.dropna()
    if clean.empty or pd.isna(x):
        return np.nan
    return float((clean <= x).mean() * 100.0)


def compute_stats(df: pd.DataFrame, window_years: int = 5) -> pd.DataFrame:
    """Compute per-praça summary stats over the last `window_years`.

    Input df must have columns: date, location, state, value.
    Returns DataFrame with STATS_COLUMNS, one row per location, sorted by n_obs_5y desc.
    """
    if df.empty:
        return pd.DataFrame(columns=STATS_COLUMNS)

    today = df["date"].max()
    cutoff_5y = today - pd.DateOffset(years=window_years)
    cutoff_3y = today - pd.DateOffset(years=3)
    d1 = today - pd.Timedelta(days=1)
    w1 = today - pd.Timedelta(days=7)
    m1 = today - pd.DateOffset(months=1)

    rows: list[dict] = []
    for loc, loc_df in df.groupby("location", sort=False):
        loc_df = loc_df.sort_values("date")
        state = loc_df["state"].dropna().iloc[0] if loc_df["state"].notna().any() else None

        window_5y = loc_df[loc_df["date"] >= cutoff_5y]["value"]
        window_3y = loc_df[loc_df["date"] >= cutoff_3y]["value"]

        basis_today = _nearest_value(loc_df, today)

        rows.append({
            "location": loc,
            "state": state,
            "basis_today": basis_today,
            "basis_d1": _nearest_value(loc_df, d1),
            "basis_w1": _nearest_value(loc_df, w1),
            "basis_m1": _nearest_value(loc_df, m1),
            "mean_3y": float(window_3y.mean()) if not window_3y.empty else np.nan,
            "mean_5y": float(window_5y.mean()) if not window_5y.empty else np.nan,
            "min_5y": float(window_5y.min()) if not window_5y.empty else np.nan,
            "max_5y": float(window_5y.max()) if not window_5y.empty else np.nan,
            "pctile_today": _percentile(window_5y, basis_today),
            "n_obs_5y": int(window_5y.notna().sum()),
        })

    out = pd.DataFrame(rows, columns=STATS_COLUMNS)
    out = out.sort_values("n_obs_5y", ascending=False).reset_index(drop=True)
    return out


def write_stats_csv(stats: pd.DataFrame, pair: BasisPairConfig) -> Path:
    """Write companion stats to data/csv/basis-stats-{label}.csv."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / f"basis-stats-{pair.label}.csv"
    stats.to_csv(path, index=False, float_format="%.2f")
    logger.info("Wrote companion stats: %s (%d rows)", path, len(stats))
    return path
