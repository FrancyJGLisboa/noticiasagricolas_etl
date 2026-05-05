"""Hedge effectiveness via OLS of physical change on futures change.

For a (commodity, praça, futures) triple:
  Δphysical_t = α + β × Δfutures_t + ε_t

  - β = optimal hedge ratio (how many units of futures to short per unit of physical)
  - R² = fraction of physical variance explained by futures (hedge effectiveness)
  - 1 - var(ε)/var(Δphysical) = % variance reduced by the hedge

Interpretation: R² > 0.6 = good hedge; R² < 0.3 = poor hedge (basis risk dominates).
"""

from typing import Any

import numpy as np
import pandas as pd

from .. import database as db


def get_hedge_fit(
    commodity: str,
    location: str,
    futures_indicator: str,
    window_years: int = 5,
    frequency: str = "weekly",
) -> dict[str, Any]:
    """OLS of Δphysical on Δfutures over the rolling window.

    Args:
        commodity: e.g. 'soja', 'milho'.
        location: e.g. 'Sorriso/MT'.
        futures_indicator: e.g. 'soja-bolsa-de-chicago-cme-group'.
        window_years: history window (default 5).
        frequency: 'daily' or 'weekly' (default weekly to reduce noise).

    Returns:
        Beta, R², variance reduction, interpretation, n_obs.
    """
    sql = """
        SELECT date, physical_price_brl, futures_price_brl
        FROM basis
        WHERE commodity = ?
          AND location = ?
          AND futures_indicator = ?
          AND physical_price_brl IS NOT NULL
          AND futures_price_brl IS NOT NULL
        ORDER BY date
    """
    rows = db.query(sql, [commodity, location, futures_indicator])
    df = pd.DataFrame(rows)
    if df.empty:
        return {"error": "no aligned physical+futures data"}

    df["date"] = pd.to_datetime(df["date"])

    # Restrict to window
    cutoff = df["date"].max() - pd.DateOffset(years=window_years)
    df = df[df["date"] >= cutoff].sort_values("date").reset_index(drop=True)
    if len(df) < 30:
        return {"error": f"insufficient data ({len(df)} obs in window)"}

    if frequency == "weekly":
        df = (
            df.set_index("date")[["physical_price_brl", "futures_price_brl"]]
            .resample("W").last().dropna()
            .reset_index()
        )
    elif frequency != "daily":
        return {"error": f"frequency must be 'daily' or 'weekly'; got {frequency!r}"}

    df["d_phys"] = df["physical_price_brl"].diff()
    df["d_fut"] = df["futures_price_brl"].diff()
    diffs = df.dropna(subset=["d_phys", "d_fut"])
    if len(diffs) < 20:
        return {"error": f"only {len(diffs)} return obs after differencing"}

    x = diffs["d_fut"].to_numpy()
    y = diffs["d_phys"].to_numpy()

    # OLS: y = α + β x
    var_x = float(np.var(x, ddof=1))
    if var_x == 0:
        return {"error": "futures returns have zero variance"}
    cov_xy = float(np.cov(x, y, ddof=1)[0, 1])
    beta = cov_xy / var_x
    alpha = float(np.mean(y) - beta * np.mean(x))

    pred = alpha + beta * x
    resid = y - pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    var_y = float(np.var(y, ddof=1))
    var_resid = float(np.var(resid, ddof=1))
    var_reduction_pct = 100 * (1 - var_resid / var_y) if var_y > 0 else float("nan")

    correl = float(np.corrcoef(x, y)[0, 1])

    if r2 >= 0.7:
        quality = "EXCELENTE"
        interp = (
            f"Hedge {quality} (R²={r2:.2f}). β={beta:.3f}: para cada R$1 de "
            f"variação no físico, hedgear com {beta:.2f} de futuro replica o move. "
            "Risco de basis pequeno — hedge funciona quase como contraposição perfeita."
        )
    elif r2 >= 0.5:
        quality = "BOM"
        interp = (
            f"Hedge {quality} (R²={r2:.2f}, β={beta:.3f}). "
            "Hedge razoável; ainda há basis risk significativo a considerar."
        )
    elif r2 >= 0.3:
        quality = "MARGINAL"
        interp = (
            f"Hedge {quality} (R²={r2:.2f}, β={beta:.3f}). "
            "Cobertura parcial — esperar volatilidade do basis afetando P&L."
        )
    else:
        quality = "POBRE"
        interp = (
            f"Hedge {quality} (R²={r2:.2f}, β={beta:.3f}). "
            "Esse contrato futuro NÃO hedgea bem essa praça. "
            "Considerar contrato alternativo (ex: B3 vs CBOT vs NYBOT) ou cross-hedge."
        )

    return {
        "commodity": commodity,
        "location": location,
        "futures_indicator": futures_indicator,
        "frequency": frequency,
        "window_years": window_years,
        "n_obs": int(len(diffs)),
        "beta": round(beta, 4),
        "alpha": round(alpha, 4),
        "r_squared": round(r2, 4),
        "correlation": round(correl, 4),
        "variance_reduction_pct": round(var_reduction_pct, 2),
        "quality": quality,
        "interpretation": interp,
    }
