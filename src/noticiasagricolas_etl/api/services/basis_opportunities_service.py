"""Rank current basis conditions with seasonal, anomaly, and hedge context."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ...analytics.basis_signals import (
    DAILY_MAX_GAP_DAYS,
    MIN_SEASONAL_OBS,
    business_days_between,
    current_change_and_anomaly,
    percentile_metrics,
    signal_column,
    trailing_window,
)
from .. import database as db
from .hedge_fit_service import fit_hedge_frame

STALE_AFTER_BUSINESS_DAYS = 10


def _optional_text(value: Any) -> str | None:
    """Convert a nullable pandas value to JSON-safe text."""
    if value is None or pd.isna(value):
        return None
    return str(value)


def _interpret(row: dict[str, Any], target_month: int) -> str:
    seasonal = row["percentile_season"]
    if seasonal is not None:
        return (
            f"Basis no percentil {seasonal:.0f} para o mês {target_month:02d} "
            f"nos últimos {row['window_years']} anos."
        )
    return (
        f"Basis no percentil {row['percentile_all']:.0f} para todo o histórico "
        f"dos últimos {row['window_years']} anos. A amostra sazonal é insuficiente."
    )


def get_basis_opportunities(
    commodity: str,
    futures_indicator: str | None = None,
    target_date: str | None = None,
    window_years: int = 5,
    stale_after_business_days: int = STALE_AFTER_BUSINESS_DAYS,
    anomaly_window: int = 60,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """Rank non-stale basis rows for one commodity."""
    params: list[object] = [commodity]
    futures_clause = ""
    if futures_indicator:
        futures_clause = "AND futures_indicator = ?"
        params.append(futures_indicator)
    date_clause = ""
    if target_date:
        date_clause = "AND date <= ?"
        params.append(target_date)

    sql = f"""
        SELECT date, location, state, physical_indicator,
               physical_price_brl, futures_indicator, futures_contract,
               futures_price_brl, ptax, basis_brl, basis_usd, basis_pct,
               basis_centavos_sc, basis_cents_bu
        FROM basis
        WHERE commodity = ?
          {futures_clause}
          {date_clause}
        ORDER BY location, futures_indicator, date
    """
    rows = db.query(sql, params)
    if not rows:
        return {
            "commodity": commodity,
            "futures_indicator": futures_indicator,
            "error": "no basis data",
            "data": [],
            "excluded": [],
        }

    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    anchor_date = pd.Timestamp(target_date) if target_date else frame["date"].max()
    frame = frame[frame["date"] <= anchor_date]

    active: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for (location, future), group in frame.groupby(
        ["location", "futures_indicator"], sort=True, dropna=False
    ):
        group = group.sort_values("date").drop_duplicates("date", keep="last")
        value_col, value_unit = signal_column(str(future))
        signal_rows = group.dropna(subset=[value_col])
        if signal_rows.empty:
            excluded.append(
                {
                    "location": str(location),
                    "futures_indicator": str(future),
                    "reason": f"no values in primary signal column {value_col}",
                }
            )
            continue

        latest = signal_rows.iloc[-1]
        latest_date = pd.Timestamp(latest["date"])
        days_since_last = business_days_between(latest_date, anchor_date)
        window = trailing_window(
            signal_rows,
            target_date=latest_date,
            window_years=window_years,
        )
        n_obs_window = int(window[value_col].notna().sum())
        if days_since_last > stale_after_business_days:
            excluded.append(
                {
                    "location": str(location),
                    "state": _optional_text(latest.get("state")),
                    "futures_indicator": str(future),
                    "last_date": latest_date.strftime("%Y-%m-%d"),
                    "days_since_last": days_since_last,
                    "n_obs_window": n_obs_window,
                    "reason": (
                        f"stale: {days_since_last} business days since last observation; "
                        f"maximum is {stale_after_business_days}"
                    ),
                }
            )
            continue

        # Keep BRL percentiles for continuity and acceptance checks. For CBOT,
        # expose the FX-separated signal percentiles as additional fields.
        percentiles = percentile_metrics(
            signal_rows,
            value_col="basis_brl",
            target_date=latest_date,
            window_years=window_years,
            min_seasonal_obs=MIN_SEASONAL_OBS,
        )
        signal_percentiles = percentile_metrics(
            signal_rows,
            value_col=value_col,
            target_date=latest_date,
            window_years=window_years,
            min_seasonal_obs=MIN_SEASONAL_OBS,
        )
        changes = current_change_and_anomaly(
            window,
            value_col=value_col,
            max_gap_days=DAILY_MAX_GAP_DAYS,
            anomaly_window=anomaly_window,
            z_threshold=z_threshold,
        )
        hedge = fit_hedge_frame(
            group[group["date"] <= latest_date],
            commodity=commodity,
            location=str(location),
            futures_indicator=str(future),
            window_years=window_years,
            frequency="weekly",
        )

        result: dict[str, Any] = {
            "commodity": commodity,
            "location": str(location),
            "state": _optional_text(latest.get("state")),
            "physical_indicator": _optional_text(latest.get("physical_indicator")),
            "futures_indicator": str(future),
            "futures_contract": _optional_text(latest.get("futures_contract")),
            "last_date": latest_date.strftime("%Y-%m-%d"),
            "days_since_last": days_since_last,
            "n_obs_window": n_obs_window,
            "window_years": window_years,
            "basis_column": value_col,
            "basis_unit": value_unit,
            "current_basis": round(float(latest[value_col]), 4),
            "current_basis_brl": round(float(latest["basis_brl"]), 4),
            "percentile_column": "basis_brl",
            **percentiles,
            "signal_percentile_all": signal_percentiles["percentile_all"],
            "signal_percentile_season": signal_percentiles["percentile_season"],
            **changes,
            "hedge": hedge,
        }
        result["interpretation"] = _interpret(result, latest_date.month)
        active.append(result)

    active.sort(
        key=lambda item: (
            item["percentile_season"] is not None,
            item["percentile_season"]
            if item["percentile_season"] is not None
            else item["percentile_all"],
        ),
        reverse=True,
    )
    for rank, item in enumerate(active, start=1):
        item["rank"] = rank

    return {
        "commodity": commodity,
        "futures_indicator": futures_indicator,
        "target_date": anchor_date.strftime("%Y-%m-%d"),
        "window_years": window_years,
        "stale_after_business_days": stale_after_business_days,
        "ranking_method": "percentile_season descending, then percentile_all descending",
        "quote_count_available": False,
        "quote_count_reason": "the basis schema stores the daily average, not its input quote count",
        "count": len(active),
        "excluded_count": len(excluded),
        "data": active,
        "excluded": excluded,
    }
