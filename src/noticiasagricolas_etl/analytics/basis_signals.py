"""Roll-aware and gap-aware calculations for basis analytics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DAILY_MAX_GAP_DAYS = 5
WEEKLY_MAX_GAP_DAYS = 7
MIN_SEASONAL_OBS = 30


def is_cbot(futures_indicator: str) -> bool:
    """Return true when an indicator identifies a CBOT or Chicago contract."""
    value = futures_indicator.lower()
    return "chicago" in value or "cbot" in value


def signal_column(futures_indicator: str) -> tuple[str, str]:
    """Return the primary basis column and unit for a futures reference."""
    if is_cbot(futures_indicator):
        return "basis_cents_bu", "USD cents/bu"
    return "basis_brl", "BRL/sc"


def business_days_between(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Count weekdays from start to end, excluding the start date."""
    if end <= start:
        return 0
    return int(np.busday_count(start.date(), end.date()))


def trailing_window(
    frame: pd.DataFrame,
    *,
    target_date: pd.Timestamp,
    window_years: int,
) -> pd.DataFrame:
    """Return observations inside the trailing year window."""
    cutoff = target_date - pd.DateOffset(years=window_years)
    return frame[(frame["date"] >= cutoff) & (frame["date"] <= target_date)].copy()


def percentile(value: float, values: pd.Series) -> float:
    """Return the inclusive empirical percentile of value."""
    valid = values.dropna().astype(float)
    if valid.empty:
        return float("nan")
    return float((valid <= value).mean() * 100.0)


def percentile_metrics(
    frame: pd.DataFrame,
    *,
    value_col: str,
    target_date: pd.Timestamp,
    window_years: int,
    min_seasonal_obs: int = MIN_SEASONAL_OBS,
) -> dict[str, Any]:
    """Compute all-history and same-calendar-month percentiles."""
    window = trailing_window(frame, target_date=target_date, window_years=window_years)
    window = window.dropna(subset=[value_col]).sort_values("date")
    if window.empty:
        return {
            "percentile_all": None,
            "percentile_season": None,
            "n_obs_window": 0,
            "n_obs_season": 0,
            "seasonal_reason": "no observations in the history window",
        }

    target_rows = window[window["date"] <= target_date]
    target_value = float(target_rows.iloc[-1][value_col])
    season = window[window["date"].dt.month == target_date.month]
    seasonal_reason = None
    seasonal_percentile = None
    if len(season) < min_seasonal_obs:
        seasonal_reason = (
            f"insufficient same-month history: {len(season)} observations; "
            f"minimum is {min_seasonal_obs}"
        )
    else:
        seasonal_percentile = round(percentile(target_value, season[value_col]), 2)

    return {
        "percentile_all": round(percentile(target_value, window[value_col]), 2),
        "percentile_season": seasonal_percentile,
        "n_obs_window": len(window),
        "n_obs_season": len(season),
        "seasonal_reason": seasonal_reason,
    }


def classified_changes(
    frame: pd.DataFrame,
    *,
    value_col: str,
    max_gap_days: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Classify consecutive changes and reject contract rolls and long gaps."""
    cols = ["date", "futures_contract", value_col]
    work = frame[cols].dropna(subset=["date", value_col]).copy()
    work["date"] = pd.to_datetime(work["date"])
    work = (
        work.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )

    work["previous_date"] = work["date"].shift()
    work["previous_contract"] = work["futures_contract"].shift()
    work["gap_days"] = (work["date"] - work["previous_date"]).dt.days
    has_previous = work["previous_date"].notna()
    same_contract = (
        work["futures_contract"].notna()
        & work["previous_contract"].notna()
        & work["futures_contract"].eq(work["previous_contract"])
    )
    work["dropped_roll"] = has_previous & ~same_contract
    work["dropped_gap"] = (
        has_previous & same_contract & (work["gap_days"] > max_gap_days)
    )
    work["valid_change"] = (
        has_previous
        & same_contract
        & work["gap_days"].between(1, max_gap_days, inclusive="both")
    )
    work["change"] = work[value_col].astype(float).diff().where(work["valid_change"])

    counts = {
        "n_dropped_roll": int(work["dropped_roll"].sum()),
        "n_dropped_gap": int(work["dropped_gap"].sum()),
    }
    return work, counts


def current_change_and_anomaly(
    frame: pd.DataFrame,
    *,
    value_col: str,
    max_gap_days: int = DAILY_MAX_GAP_DAYS,
    anomaly_window: int = 60,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """Return the current valid change and its rolling anomaly score."""
    changes, counts = classified_changes(
        frame,
        value_col=value_col,
        max_gap_days=max_gap_days,
    )
    result: dict[str, Any] = {
        **counts,
        "change_5d": None,
        "change_5d_reason": None,
        "anomaly_zscore": None,
        "is_anomaly": False,
        "anomaly_n_obs": 0,
        "anomaly_reason": None,
    }
    if changes.empty:
        result["change_5d_reason"] = "no basis observations"
        result["anomaly_reason"] = "no basis observations"
        return result

    current = changes.iloc[-1]
    five_day_start = current["date"] - pd.Timedelta(days=5)
    recent = changes[changes["date"] >= five_day_start]
    recent_transitions = recent.iloc[1:]
    if len(recent) < 2:
        result["change_5d_reason"] = (
            "fewer than two observations in the last 5 calendar days"
        )
    elif not bool(recent_transitions["valid_change"].all()):
        result["change_5d_reason"] = (
            "the 5-day window contains a contract roll or data gap"
        )
    else:
        result["change_5d"] = round(
            float(recent.iloc[-1][value_col]) - float(recent.iloc[0][value_col]),
            4,
        )

    if bool(current["dropped_roll"]):
        result["anomaly_reason"] = "current change crosses a futures contract roll"
        return result
    if bool(current["dropped_gap"]):
        result["anomaly_reason"] = (
            f"current change crosses a data gap over {max_gap_days} calendar days"
        )
        return result
    if not bool(current["valid_change"]):
        result["anomaly_reason"] = "no valid prior observation for the current change"
        return result

    current_change = float(current["change"])
    valid = changes.loc[changes["valid_change"], "change"].dropna().tail(anomaly_window)
    result["anomaly_n_obs"] = len(valid)
    if len(valid) < 10:
        result["anomaly_reason"] = (
            f"insufficient valid changes for anomaly score: {len(valid)}; minimum is 10"
        )
        return result

    std = float(valid.std(ddof=1))
    if std == 0 or np.isnan(std):
        result["anomaly_reason"] = "valid basis changes have zero variance"
        return result

    zscore = (current_change - float(valid.mean())) / std
    result["anomaly_zscore"] = round(float(zscore), 4)
    result["is_anomaly"] = bool(abs(zscore) >= z_threshold)
    return result


def weekly_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the last actual observation in each Sunday-ending week."""
    work = frame.copy().sort_values("date")
    work["date"] = pd.to_datetime(work["date"])
    work["observation_date"] = work["date"]
    return (
        work.set_index("date")
        .resample("W-SUN")
        .last()
        .dropna(subset=["observation_date"])
        .reset_index(drop=True)
        .rename(columns={"observation_date": "date"})
    )
