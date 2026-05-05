"""Basis percentile vs N-year rolling history per (commodity, location).

Answers: 'is today's basis cheap or expensive vs typical?' as a 0-100 number.
The chart's HOJE marker shows the value graphically; this service returns the
exact percentile + interpretation an AI agent can quote in text.
"""

from typing import Any

import pandas as pd

from ...analytics.diagnostic import PERCENTILE_5, compute_window_stats
from .. import database as db


_VALID_COLUMNS = {"basis_brl", "basis_usd", "basis_pct", "basis_centavos_sc", "basis_cents_bu"}

# Domain-specific copy: bucket label → interpretation string.
# {pct} placeholder is filled with the integer percentile; {below} = 100 - pct;
# {window_years} = the history-window width.
_INTERP: dict[str, str] = {
    "extreme_high": (
        "basis EXTREMAMENTE CARO — está em P{pct:.0f}, acima de {pct:.0f}% "
        "da história {window_years}y. Sinal forte para venda física."
    ),
    "high": "basis CARO — P{pct:.0f}, decil superior. Considere fechar venda.",
    "normal": "basis NORMAL — P{pct:.0f}, dentro da faixa típica.",
    "low": "basis BARATO — P{pct:.0f}, decil inferior. Considere segurar.",
    "extreme_low": (
        "basis EXTREMAMENTE BARATO — P{pct:.0f}, abaixo de {below:.0f}% "
        "da história. Sinal forte para segurar/recomprar."
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

    return {
        "commodity": commodity,
        "location": location,
        "futures_indicator": target_fut,
        "column": column,
        "window_years": window_years,
        **stats.as_dict(),
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
