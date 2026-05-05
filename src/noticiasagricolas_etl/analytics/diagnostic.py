"""Window-stats computation and bucket classification.

Five percentile services (basis, crush, port_spread, ratio, vol_regime) shared
this skeleton:

  1. Load a date-indexed series.
  2. Pick the row at-or-before target_date (default: latest).
  3. Take the trailing N-year window ending on that date.
  4. Compute percentile = pct of window values <= target value.
  5. Return descriptive stats (mean, p25, p50, p75, min, max, n_obs).
  6. Map the percentile to a bucket label (e.g. "extreme_low" .. "extreme_high").
  7. Pull a domain-specific Portuguese interpretation string from a per-service
     mapping.

Steps 1-6 live here. Step 7 stays in each service because the prose is
domain-specific (basis-cara vs crush-margin-alta vs porto-caro). What was
duplicated and is now centralized: the window math, the percentile formula,
the rounded-stats dict, and the bucket-threshold tables.

Bucket also serves three non-percentile services (anomaly's z-score severity,
hedge_fit's R² quality, term_structure's slope regime) — same shape, different
input scale.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Bucket:
    """Maps a numeric score to one of N labels via ordered upper-bound thresholds.

    `thresholds` are upper bounds (inclusive) of each bucket except the last,
    which catches everything above the last threshold. `len(labels)` must equal
    `len(thresholds) + 1`.

    Example — 5-bucket symmetric percentile classifier:

        b = Bucket(
            thresholds=(10, 25, 75, 90),
            labels=("extreme_low", "low", "normal", "high", "extreme_high"),
        )
        b.classify(5)   # "extreme_low"
        b.classify(50)  # "normal"
        b.classify(95)  # "extreme_high"

    For two-tailed scores like z-scores, callers pass `abs(z)` and use a
    monotone-increasing severity bucket.
    """

    thresholds: tuple[float, ...]
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.thresholds) + 1:
            raise ValueError(
                f"labels must have {len(self.thresholds) + 1} entries "
                f"(one more than thresholds); got {len(self.labels)}"
            )

    def classify(self, value: float) -> str:
        for thresh, label in zip(self.thresholds, self.labels, strict=False):
            if value <= thresh:
                return label
        return self.labels[-1]


# Standard 5-bucket percentile classifier used by basis_percentile, crush_percentile.
PERCENTILE_5 = Bucket(
    thresholds=(10.0, 25.0, 75.0, 90.0),
    labels=("extreme_low", "low", "normal", "high", "extreme_high"),
)

# 3-bucket percentile classifier used by port_spread, ratio.
PERCENTILE_3 = Bucket(
    thresholds=(25.0, 75.0),
    labels=("low", "normal", "high"),
)


@dataclass(frozen=True)
class WindowStats:
    """Descriptive stats for a target observation against its trailing N-year window.

    All numeric fields are pre-rounded for direct serialization in service
    response dicts. Use `as_dict()` to splat into a service result.
    """

    target_date: str
    value: float
    percentile: float
    n_obs: int
    mean: float
    p25: float
    p50: float
    p75: float
    min: float
    max: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_window_stats(
    df: pd.DataFrame,
    *,
    date_col: str = "date",
    value_col: str = "value",
    target_date: str | None,
    window_years: int,
) -> WindowStats | dict[str, str]:
    """Pick row at-or-before target_date, take trailing N-year window, compute stats.

    Args:
        df: DataFrame with date and value columns. Date column may be string
            or pandas-timestamp; will be coerced. NaN values are dropped.
        date_col: Name of the date column (default 'date').
        value_col: Name of the value column (default 'value').
        target_date: ISO 'YYYY-MM-DD'. None = use the latest observation.
        window_years: Width of the trailing window ending on target_date.

    Returns:
        `WindowStats` on success, or `{"error": ...}` dict on missing-data
        conditions (no rows, no rows on/before target, empty window). Returning
        the error dict (rather than raising) matches the conventions of the
        callers, which surface it as part of their response payload.
    """
    if df.empty:
        return {"error": "no data"}

    work = df[[date_col, value_col]].copy()
    work[date_col] = pd.to_datetime(work[date_col])
    work = work.dropna(subset=[value_col]).sort_values(date_col).reset_index(drop=True)
    if work.empty:
        return {"error": "no data"}

    if target_date:
        td = pd.Timestamp(target_date)
        sub = work[work[date_col] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        target_row = sub.iloc[-1]
    else:
        target_row = work.iloc[-1]

    target_d: str = target_row[date_col].strftime("%Y-%m-%d")
    target_v = float(target_row[value_col])

    cutoff = target_row[date_col] - pd.DateOffset(years=window_years)
    window = work[
        (work[date_col] >= cutoff) & (work[date_col] <= target_row[date_col])
    ][value_col]
    if window.empty:
        return {"error": "empty window"}

    pct = float((window <= target_v).mean() * 100.0)

    return WindowStats(
        target_date=target_d,
        value=round(target_v, 4),
        percentile=round(pct, 2),
        n_obs=int(window.count()),
        mean=round(float(window.mean()), 4),
        p25=round(float(window.quantile(0.25)), 4),
        p50=round(float(window.quantile(0.50)), 4),
        p75=round(float(window.quantile(0.75)), 4),
        min=round(float(window.min()), 4),
        max=round(float(window.max()), 4),
    )
