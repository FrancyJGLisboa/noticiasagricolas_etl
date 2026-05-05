"""Pure-DataFrame reshapes that feed the basis visualizations.

Until this module existed, each viz built its own reshape inline:

  - seasonality computed a year × day-of-year pivot, then per-DOY quantile
    envelopes (min, P25, P50, P75, max) with 7-day rolling smoothing.
  - heatmap computed weekly medians per location, then z-scored each cell
    against the location's own (mean, std).
  - multi_location, deviation_map, and seasonality each clipped the input
    to the trailing N years independently.

All three reshapes are pure DataFrame transforms (no plotting). Pulling them
here makes them unit-testable in isolation: assert exact pivot values, exact
z-scores, exact window edges — no need to introspect Plotly figure innards.

The viz modules then become thin: load → reshape → render.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def windowed(
    df: pd.DataFrame,
    *,
    window_years: int,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Filter `df` to the trailing `window_years` ending on `today`.

    `today` defaults to the maximum date in `df`. Returns a copy with rows
    whose `date >= today - window_years`. Empty input → empty output.
    """
    if df.empty:
        return df.copy()
    if today is not None:
        today = pd.Timestamp(today)
        cutoff = today - pd.DateOffset(years=window_years)
        return df[(df["date"] >= cutoff) & (df["date"] <= today)].copy()
    today = df["date"].max()
    cutoff = today - pd.DateOffset(years=window_years)
    return df[df["date"] >= cutoff].copy()


def doy_envelope(
    df: pd.DataFrame,
    *,
    window_years: int,
    today: pd.Timestamp | None = None,
    smooth_window: int = 7,
) -> pd.DataFrame:
    """Per-day-of-year quantile envelope across past years.

    Pivots the trailing-`window_years` data into a (DOY × year) grid, computes
    per-DOY min/P25/P50/P75/max across past years (current year excluded),
    then 7-day-rolling smooths each band.

    Returns a DataFrame indexed by DOY 1..366 with columns
    `min, p25, p50, p75, max`. NaN where a DOY had no past-year observations.

    Empty input → empty DataFrame.
    """
    if df.empty:
        return pd.DataFrame(columns=["min", "p25", "p50", "p75", "max"])

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    today = pd.Timestamp(today) if today is not None else work["date"].max()

    cutoff = today - pd.DateOffset(years=window_years)
    work = work[(work["date"] >= cutoff) & work["value"].notna()]
    if work.empty:
        return pd.DataFrame(columns=["min", "p25", "p50", "p75", "max"])

    work["year"] = work["date"].dt.year
    work["doy"] = work["date"].dt.dayofyear

    daily = work.groupby(["year", "doy"], as_index=False)["value"].mean()
    current_year = int(today.year)
    past = daily[daily["year"] < current_year]
    if past.empty:
        return pd.DataFrame(columns=["min", "p25", "p50", "p75", "max"])

    pivot = past.pivot(index="doy", columns="year", values="value").reindex(range(1, 367))

    bands = pd.DataFrame({
        "min": pivot.min(axis=1),
        "p25": pivot.quantile(0.25, axis=1),
        "p50": pivot.median(axis=1),
        "p75": pivot.quantile(0.75, axis=1),
        "max": pivot.max(axis=1),
    })

    # Centered rolling smooth — handles the Plotly-friendly visual smoothing.
    return bands.rolling(window=smooth_window, center=True, min_periods=3).mean()


def weekly_zscore(
    df: pd.DataFrame,
    *,
    window_years: int,
    today: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Per-(location, week) z-score against each location's own (mean, std).

    Resamples to weekly median per location over the trailing `window_years`,
    then computes `(value - location_mean) / location_std`. Returns a long-form
    DataFrame with columns `location, week, value, zscore` (NaN zscore where
    the location's std is zero — which would otherwise divide-by-zero).

    Empty input → empty DataFrame.
    """
    if df.empty:
        return pd.DataFrame(columns=["location", "week", "value", "zscore"])

    work = windowed(df, window_years=window_years, today=today)
    if work.empty:
        return pd.DataFrame(columns=["location", "week", "value", "zscore"])

    work = work.copy()
    work["week"] = work["date"].dt.to_period("W").apply(lambda p: p.start_time)
    weekly = work.groupby(["location", "week"], as_index=False)["value"].median()

    stats = weekly.groupby("location")["value"].agg(["mean", "std"]).reset_index()
    weekly = weekly.merge(stats, on="location", how="left")
    weekly["zscore"] = np.where(
        (weekly["std"].notna()) & (weekly["std"] > 0),
        (weekly["value"] - weekly["mean"]) / weekly["std"],
        np.nan,
    )
    return weekly[["location", "week", "value", "zscore"]]
