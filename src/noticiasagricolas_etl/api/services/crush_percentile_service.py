"""Soybean crush margin percentile vs N-year history.

Wraps crush_service.compute() and adds a percentile ranking + interpretation.
The crusher decision (esmagar vs exportar) is heavily driven by where
today's margin sits in the historical distribution: high decile = strong
incentive to crush, low decile = sit on grain.
"""

from typing import Any

import pandas as pd

from . import crush_service


def get_crush_percentile(
    target_date: str | None = None,
    window_years: int = 5,
    contract: str | None = None,
    soja_indicator: str = "soja-b3-pregao-regular",
    farelo_indicator: str = "farelo-de-soja-b3",
    oleo_indicator: str = "oleo-de-soja-b3",
) -> dict[str, Any]:
    """Compute today's crush margin and its percentile in the N-year history.

    Args:
        target_date: ISO 'YYYY-MM-DD'; None = latest available margin.
        window_years: rolling window for percentile (default 5).
        contract: optional contract filter (YYYY-MM); None = all contracts.
        soja_indicator/farelo_indicator/oleo_indicator: catalog slugs.

    Returns:
        Dict with target_date, margin, percentile, mean/min/max/p25/p50/p75,
        n_obs, interpretation.
    """
    full = crush_service.compute(
        contract=contract,
        soja_indicator=soja_indicator,
        farelo_indicator=farelo_indicator,
        oleo_indicator=oleo_indicator,
    )
    rows = full.get("data", [])
    if not rows:
        return {"error": "no crush margin data"}

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["crush_margin"].notna()].sort_values("date").reset_index(drop=True)

    if target_date:
        td = pd.Timestamp(target_date)
        sub = df[df["date"] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        target_row = sub.iloc[-1]
    else:
        target_row = df.iloc[-1]

    target_d = target_row["date"].strftime("%Y-%m-%d")
    target_margin = float(target_row["crush_margin"])

    cutoff = target_row["date"] - pd.DateOffset(years=window_years)
    window = df[(df["date"] >= cutoff) & (df["date"] <= target_row["date"])]["crush_margin"]
    if window.empty:
        return {"error": "empty window"}

    pct = float((window <= target_margin).mean() * 100.0)

    if pct >= 90:
        interp = (
            f"crush margin EXTREMAMENTE ALTA — P{pct:.0f}, decil superior. "
            "Forte incentivo para esmagar. Industriais devem maximizar processamento; "
            "produtores podem ter dificuldade de competir com indústria por grão físico."
        )
    elif pct >= 75:
        interp = (
            f"crush margin ALTA — P{pct:.0f}. Esmagamento atrativo. "
            "Esperar pressão compradora da indústria sobre grão."
        )
    elif pct >= 25:
        interp = f"crush margin NORMAL — P{pct:.0f}, dentro da faixa típica."
    elif pct >= 10:
        interp = (
            f"crush margin BAIXA — P{pct:.0f}, decil inferior. "
            "Esmagamento marginal — esperar redução de utilização industrial. "
            "Suporte ao preço do grão pelo lado do exportador, não do crusher."
        )
    else:
        interp = (
            f"crush margin EXTREMAMENTE BAIXA — P{pct:.0f}. "
            "Indústria opera no vermelho — esperar paradas/redução. "
            "Janela de oferta apertada de farelo/óleo doméstico."
        )

    return {
        "target_date": target_d,
        "current_margin": round(target_margin, 4),
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
        "indicators": full["indicators"],
    }
