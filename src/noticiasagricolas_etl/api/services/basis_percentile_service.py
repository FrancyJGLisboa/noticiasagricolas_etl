"""Basis percentile vs N-year rolling history per (commodity, location).

Answers: 'is today's basis cheap or expensive vs typical?' as a 0-100 number.
The chart's HOJE marker shows the value graphically; this service returns the
exact percentile + interpretation an AI agent can quote in text.
"""

from typing import Any

import pandas as pd

from ...analytics.basis_signals import MIN_SEASONAL_OBS, percentile_metrics
from ...analytics.diagnostic import PERCENTILE_5, compute_window_stats
from .. import database as db

_VALID_COLUMNS = {
    "basis_brl",
    "basis_usd",
    "basis_pct",
    "basis_centavos_sc",
    "basis_cents_bu",
}

# Domain-specific copy: bucket label → interpretation string.
# {pct} placeholder is filled with the integer percentile; {below} = 100 - pct;
# {window_years} = the history-window width.
_INTERP: dict[str, str] = {
    "extreme_high": (
        "Basis no percentil {pct:.0f}, acima da faixa histórica usual dos últimos "
        "{window_years} anos."
    ),
    "high": "Basis no percentil {pct:.0f}, dentro do decil superior histórico.",
    "normal": "Basis no percentil {pct:.0f}, dentro da faixa histórica central.",
    "low": "Basis no percentil {pct:.0f}, dentro do decil inferior histórico.",
    "extreme_low": (
        "Basis no percentil {pct:.0f}, abaixo da faixa histórica usual dos últimos "
        "{window_years} anos."
    ),
}


def get_basis_percentile(
    commodity: str,
    location: str,
    futures_indicator: str | None = None,
    target_date: str | None = None,
    window_years: int = 5,
    column: str = "basis_brl",
) -> dict[str, Any]:
    """Where does target_date's basis sit in the {window_years}y distribution
    for the given praça?

    Args:
        commodity: e.g. 'soja', 'milho'.
        location: e.g. 'Sorriso/MT'.
        futures_indicator: e.g. 'soja-bolsa-de-chicago-cme-group'. If None,
            picks the first match — caller should pass when ambiguous.
        target_date: ISO date 'YYYY-MM-DD'. None = latest available.
        window_years: history window (default 5).
        column: which basis column ('basis_brl', 'basis_cents_bu',
            'basis_centavos_sc', 'basis_pct'). Validated.

    Returns:
        Dict with target_date, value, percentile (0-100), mean, p25, p50, p75,
        min, max, n_obs, interpretation.
    """
    if column not in _VALID_COLUMNS:
        raise ValueError(f"column must be one of {_VALID_COLUMNS}; got {column!r}")

    params: list[object] = [commodity, location]
    fut_clause = ""
    if futures_indicator:
        fut_clause = "AND futures_indicator = ?"
        params.append(futures_indicator)

    sql = f"""
        SELECT date, futures_indicator, {column} AS value
        FROM basis
        WHERE commodity = ? AND location = ? {fut_clause}
          AND {column} IS NOT NULL
        ORDER BY date
    """
    rows = db.query(sql, params)
    if not rows:
        return {
            "commodity": commodity,
            "location": location,
            "futures_indicator": futures_indicator,
            "error": "no data",
        }

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # A percentile must not combine different futures references. When the
    # caller omits the reference, use the reference on the target observation.
    if not futures_indicator:
        requested = pd.Timestamp(target_date) if target_date else df["date"].max()
        candidates = df[df["date"] <= requested]
        if candidates.empty:
            return {
                "commodity": commodity,
                "location": location,
                "error": f"no data on or before {target_date}",
            }
        futures_indicator = str(candidates.iloc[-1]["futures_indicator"])
        df = df[df["futures_indicator"] == futures_indicator].copy()

    stats = compute_window_stats(df, target_date=target_date, window_years=window_years)
    if isinstance(stats, dict):
        return {"commodity": commodity, "location": location, **stats}

    target_fut = _futures_for_date(df, stats.target_date, futures_indicator)
    bucket = PERCENTILE_5.classify(stats.percentile)
    interp = _INTERP[bucket].format(
        pct=stats.percentile,
        below=100 - stats.percentile,
        window_years=window_years,
    )
    seasonal = percentile_metrics(
        df,
        value_col="value",
        target_date=pd.Timestamp(stats.target_date),
        window_years=window_years,
        min_seasonal_obs=MIN_SEASONAL_OBS,
    )

    return {
        "commodity": commodity,
        "location": location,
        "futures_indicator": target_fut,
        "column": column,
        "window_years": window_years,
        **stats.as_dict(),
        "percentile_all": stats.percentile,
        "percentile_season": seasonal["percentile_season"],
        "n_obs_season": seasonal["n_obs_season"],
        "seasonal_reason": seasonal["seasonal_reason"],
        "interpretation": interp,
    }


def _futures_for_date(df: pd.DataFrame, target_date: str, fallback: str | None) -> str:
    """Pull the futures_indicator on the target row (last row at-or-before)."""
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    sub = work[work["date"] <= pd.Timestamp(target_date)]
    if sub.empty:
        return str(fallback)
    return str(sub.iloc[-1].get("futures_indicator", fallback))
