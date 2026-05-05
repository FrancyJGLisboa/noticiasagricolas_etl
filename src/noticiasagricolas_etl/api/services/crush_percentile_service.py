"""Soybean crush margin percentile vs N-year history.

Wraps crush_service.compute() and adds a percentile ranking + interpretation.
The crusher decision (esmagar vs exportar) is heavily driven by where
today's margin sits in the historical distribution: high decile = strong
incentive to crush, low decile = sit on grain.
"""

from typing import Any

import pandas as pd

from ...analytics.diagnostic import PERCENTILE_5, compute_window_stats
from . import crush_service


_INTERP: dict[str, str] = {
    "extreme_high": (
        "crush margin EXTREMAMENTE ALTA — P{pct:.0f}, decil superior. "
        "Forte incentivo para esmagar. Industriais devem maximizar processamento; "
        "produtores podem ter dificuldade de competir com indústria por grão físico."
    ),
    "high": (
        "crush margin ALTA — P{pct:.0f}. Esmagamento atrativo. "
        "Esperar pressão compradora da indústria sobre grão."
    ),
    "normal": "crush margin NORMAL — P{pct:.0f}, dentro da faixa típica.",
    "low": (
        "crush margin BAIXA — P{pct:.0f}, decil inferior. "
        "Esmagamento marginal — esperar redução de utilização industrial. "
        "Suporte ao preço do grão pelo lado do exportador, não do crusher."
    ),
    "extreme_low": (
        "crush margin EXTREMAMENTE BAIXA — P{pct:.0f}. "
        "Indústria opera no vermelho — esperar paradas/redução. "
        "Janela de oferta apertada de farelo/óleo doméstico."
    ),
}


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
        Dict with target_date, current_margin, percentile, mean/min/max/p25/p50/p75,
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
    stats = compute_window_stats(
        df,
        value_col="crush_margin",
        target_date=target_date,
        window_years=window_years,
    )
    if isinstance(stats, dict):
        return stats

    bucket = PERCENTILE_5.classify(stats.percentile)
    interp = _INTERP[bucket].format(pct=stats.percentile)

    base = stats.as_dict()
    # Preserve the historical "current_margin" key in the response shape.
    base["current_margin"] = base.pop("value")

    return {
        **base,
        "window_years": window_years,
        "interpretation": interp,
        "indicators": full["indicators"],
    }
