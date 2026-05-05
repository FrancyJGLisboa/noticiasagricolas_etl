"""Basis percentile vs N-year rolling history per (commodity, location).

Answers: 'is today's basis cheap or expensive vs typical?' as a 0-100 number.
The chart's HOJE marker shows the value graphically; this service returns the
exact percentile + interpretation an AI agent can quote in text.
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd

from .. import database as db


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
    valid_cols = {"basis_brl", "basis_usd", "basis_pct", "basis_centavos_sc", "basis_cents_bu"}
    if column not in valid_cols:
        raise ValueError(f"column must be one of {valid_cols}; got {column!r}")

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
            "commodity": commodity, "location": location,
            "futures_indicator": futures_indicator,
            "error": "no data",
        }

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # Pick target date
    if target_date:
        td = pd.Timestamp(target_date)
        sub = df[df["date"] <= td]
        if sub.empty:
            return {
                "commodity": commodity, "location": location,
                "error": f"no data on or before {target_date}",
            }
        target_row = sub.iloc[-1]
    else:
        target_row = df.iloc[-1]

    target_date_str = target_row["date"].strftime("%Y-%m-%d")
    target_value = float(target_row["value"])
    target_fut = str(target_row.get("futures_indicator", futures_indicator))

    # Window: past N years from target date
    cutoff = target_row["date"] - pd.DateOffset(years=window_years)
    window = df[(df["date"] >= cutoff) & (df["date"] <= target_row["date"])]["value"]

    if window.empty:
        return {
            "commodity": commodity, "location": location,
            "error": "empty window",
        }

    pct = float((window <= target_value).mean() * 100.0)

    # Interpretation in plain Portuguese
    if pct >= 90:
        interp = (
            f"basis EXTREMAMENTE CARO — está em P{pct:.0f}, acima de {pct:.0f}% "
            f"da história {window_years}y. Sinal forte para venda física."
        )
    elif pct >= 75:
        interp = (
            f"basis CARO — P{pct:.0f}, decil superior. Considere fechar venda."
        )
    elif pct >= 25:
        interp = f"basis NORMAL — P{pct:.0f}, dentro da faixa típica."
    elif pct >= 10:
        interp = (
            f"basis BARATO — P{pct:.0f}, decil inferior. Considere segurar."
        )
    else:
        interp = (
            f"basis EXTREMAMENTE BARATO — P{pct:.0f}, abaixo de {100-pct:.0f}% "
            f"da história. Sinal forte para segurar/recomprar."
        )

    return {
        "commodity": commodity,
        "location": location,
        "futures_indicator": target_fut,
        "column": column,
        "target_date": target_date_str,
        "value": target_value,
        "percentile": round(pct, 2),
        "window_years": window_years,
        "n_obs": int(window.count()),
        "mean": round(float(window.mean()), 4),
        "p25": round(float(window.quantile(0.25)), 4),
        "p50": round(float(window.quantile(0.50)), 4),
        "p75": round(float(window.quantile(0.75)), 4),
        "min": round(float(window.min()), 4),
        "max": round(float(window.max()), 4),
        "interpretation": interp,
    }
