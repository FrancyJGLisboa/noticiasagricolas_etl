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

from .. import database as db


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

    # Pick target row
    if target_date:
        td = pd.Timestamp(target_date)
        sub = df[df["date"] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        target_row = sub.iloc[-1]
        target_idx = sub.index[-1]
    else:
        target_row = df.iloc[-1]
        target_idx = df.index[-1]

    target_d = target_row["date"].strftime("%Y-%m-%d")
    target_vol = float(target_row["vol"])

    cutoff = target_row["date"] - pd.DateOffset(years=history_years)
    window = df[(df["date"] >= cutoff) & (df["date"] <= target_row["date"])]["vol"]
    if window.empty:
        return {"error": "empty history window"}

    p25, p50, p75 = (
        float(window.quantile(0.25)),
        float(window.quantile(0.50)),
        float(window.quantile(0.75)),
    )

    if target_vol <= p25:
        regime = "low"
    elif target_vol <= p50:
        regime = "med-low"
    elif target_vol <= p75:
        regime = "med-high"
    else:
        regime = "high"

    # Count days in current regime — walk back while same bucket
    def _classify(v: float) -> str:
        if v <= p25: return "low"
        if v <= p50: return "med-low"
        if v <= p75: return "med-high"
        return "high"

    days_in_regime = 0
    for idx in range(target_idx, -1, -1):
        if _classify(float(df.iloc[idx]["vol"])) == regime:
            days_in_regime += 1
        else:
            break

    pct = float((window <= target_vol).mean() * 100.0)

    interp_map = {
        "low": (
            f"vol BAIXA — P{pct:.0f}, regime calmo. "
            "Posições maiores aceitáveis; opções baratas (favorece comprar vol)."
        ),
        "med-low": f"vol MÉDIA-BAIXA — P{pct:.0f}, condições estáveis.",
        "med-high": f"vol MÉDIA-ALTA — P{pct:.0f}, atenção redobrada.",
        "high": (
            f"vol ALTA — P{pct:.0f}, regime estressado. "
            "Reduzir tamanho de posição; opções caras (favorece vender vol). "
            "Stop-losses largos para evitar saídas em ruído."
        ),
    }

    return {
        "indicator": indicator,
        "location": location,
        "target_date": target_d,
        "current_vol_annualized": round(target_vol, 4),
        "regime": regime,
        "days_in_regime": days_in_regime,
        "percentile": round(pct, 2),
        "window_days": window_days,
        "history_years": history_years,
        "quartile_boundaries": {
            "p25": round(p25, 4),
            "p50_median": round(p50, 4),
            "p75": round(p75, 4),
        },
        "interpretation": interp_map[regime],
    }
