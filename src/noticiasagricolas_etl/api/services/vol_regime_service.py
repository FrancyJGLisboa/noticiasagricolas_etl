"""Volatility regime detection — quartile-based classification.

For a price series, computes rolling 20-day stdev of log returns, then
classifies the current value into vol-regime quartiles (low / med-low /
med-high / high) computed over the full N-year history. Tells the
trader what vol environment they're in for position-sizing decisions.

Quartile-based, not HMM — simpler, no extra deps, and equally actionable
for sizing/hedging decisions.
"""

from typing import Any

import numpy as np
import pandas as pd

from ...analytics.diagnostic import Bucket, compute_window_stats
from .. import database as db


_INTERP: dict[str, str] = {
    "low": (
        "vol BAIXA — P{pct:.0f}, regime calmo. "
        "Posições maiores aceitáveis; opções baratas (favorece comprar vol)."
    ),
    "med-low": "vol MÉDIA-BAIXA — P{pct:.0f}, condições estáveis.",
    "med-high": "vol MÉDIA-ALTA — P{pct:.0f}, atenção redobrada.",
    "high": (
        "vol ALTA — P{pct:.0f}, regime estressado. "
        "Reduzir tamanho de posição; opções caras (favorece vender vol). "
        "Stop-losses largos para evitar saídas em ruído."
    ),
}


def get_vol_regime(
    indicator: str,
    location: str | None = None,
    target_date: str | None = None,
    window_days: int = 20,
    history_years: int = 5,
    measure: str = "price",
) -> dict[str, Any]:
    """Classify current rolling-window volatility into historical quartiles.

    Args:
        indicator: e.g. 'soja-mercado-fisico-sindicatos-e-cooperativas'.
        location: optional praça filter.
        target_date: ISO; None = latest.
        window_days: rolling window for stdev (default 20).
        history_years: window for quartile boundaries (default 5).
        measure: column filter (default 'price').

    Returns:
        Current vol estimate, percentile vs N-year history, regime label,
        days in current regime, recent regime transitions, interpretation.
    """
    sql = """
        SELECT date, value FROM prices
        WHERE indicator = ? AND measure = ? AND value IS NOT NULL
    """
    params: list[object] = [indicator, measure]
    if location:
        sql += " AND location = ?"
        params.append(location)
    sql += " ORDER BY date"
    rows = db.query(sql, params)
    df = pd.DataFrame(rows)
    if df.empty:
        return {"error": "no data"}

    df["date"] = pd.to_datetime(df["date"])
    # Daily mean across multi-row dates
    df = df.groupby("date", as_index=False)["value"].mean().sort_values("date").reset_index(drop=True)

    if len(df) < window_days + 30:
        return {"error": f"need ≥{window_days + 30} obs, have {len(df)}"}

    # Log returns and rolling stdev (annualized — multiply by sqrt(252))
    df["log_ret"] = np.log(df["value"] / df["value"].shift(1))
    df["vol"] = df["log_ret"].rolling(window=window_days, min_periods=window_days // 2).std() * np.sqrt(252)
    df = df.dropna(subset=["vol"]).reset_index(drop=True)

    if df.empty:
        return {"error": "no rolling vol values computable"}

    stats = compute_window_stats(
        df,
        value_col="vol",
        target_date=target_date,
        window_years=history_years,
    )
    if isinstance(stats, dict):
        return stats

    # Classify against the window's own p25/p50/p75 — regime is per-window-relative.
    quartile_bucket = Bucket(
        thresholds=(stats.p25, stats.p50, stats.p75),
        labels=("low", "med-low", "med-high", "high"),
    )
    regime = quartile_bucket.classify(stats.value)

    # Count days in current regime — walk back while same bucket.
    target_idx = int(df.index[df["date"] == pd.Timestamp(stats.target_date)][-1])
    days_in_regime = 0
    for idx in range(target_idx, -1, -1):
        if quartile_bucket.classify(float(df.iloc[idx]["vol"])) == regime:
            days_in_regime += 1
        else:
            break

    interp = _INTERP[regime].format(pct=stats.percentile)

    return {
        "indicator": indicator,
        "location": location,
        "target_date": stats.target_date,
        "current_vol_annualized": stats.value,
        "regime": regime,
        "days_in_regime": days_in_regime,
        "percentile": stats.percentile,
        "window_days": window_days,
        "history_years": history_years,
        "quartile_boundaries": {
            "p25": stats.p25,
            "p50_median": stats.p50,
            "p75": stats.p75,
        },
        "interpretation": interp,
    }
