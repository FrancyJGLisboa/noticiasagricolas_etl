"""Term structure of futures: contango / backwardation slope.

For a futures indicator on a date, returns the spread between the front
contract and each subsequent contract, plus a per-month slope and the
overall regime classification:
  - Contango (positive slope): future > spot, market wants storage
  - Backwardation (negative slope): future < spot, market wants disponível
"""

from datetime import date as _date
from typing import Any

import pandas as pd

from ...analytics.diagnostic import Bucket
from .. import database as db


# Slope (% per month) thresholds, ordered ascending.
# < -0.3   → backwardation forte
# < -0.05  → backwardation leve
# ≤  0.05  → flat
# ≤  0.3   → contango leve
# >  0.3   → contango forte
_REGIME = Bucket(
    thresholds=(-0.3, -0.05, 0.05, 0.3),
    labels=(
        "backwardation forte",
        "backwardation leve",
        "flat",
        "contango leve",
        "contango forte",
    ),
)


def get_term_structure(
    futures_indicator: str,
    target_date: str | None = None,
) -> dict[str, Any]:
    """For a single futures indicator on a date, return the curve and slope.

    Args:
        futures_indicator: e.g. 'soja-bolsa-de-chicago-cme-group',
            'milho-b3-prego-regular'.
        target_date: ISO 'YYYY-MM-DD'. None = latest available date for this
            indicator.

    Returns:
        Dict with target_date, contracts (list of {contract, value, months_out}),
        front_to_2nd_spread, front_to_back_slope_per_month, regime classification.
    """
    # Get settlement/price rows only — exclude derivatives (variacao_cents, variacao_pct)
    sql = """
        SELECT date, contract, value
        FROM prices
        WHERE indicator = ?
          AND price_basis = 'futures'
          AND measure = 'price'
          AND contract IS NOT NULL
          AND value IS NOT NULL
        ORDER BY date, contract
    """
    rows = db.query(sql, [futures_indicator])
    if not rows:
        return {"error": f"no futures data for {futures_indicator}"}

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # Pick target date
    if target_date:
        td = pd.Timestamp(target_date)
        sub = df[df["date"] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        snapshot_date = sub["date"].max()
    else:
        snapshot_date = df["date"].max()

    snapshot = df[df["date"] == snapshot_date].copy()
    snapshot["contract"] = snapshot["contract"].astype(str)
    # Sort by contract YYYY-MM
    snapshot = snapshot.sort_values("contract").reset_index(drop=True)

    if len(snapshot) < 2:
        return {
            "error": f"only {len(snapshot)} contract on {snapshot_date.date()} — need ≥2 for term structure",
            "target_date": snapshot_date.strftime("%Y-%m-%d"),
            "contracts": snapshot[["contract", "value"]].to_dict(orient="records"),
        }

    # Compute months_out from snapshot date (use last day of contract month as expiry proxy)
    snap_ym = snapshot_date.to_period("M")
    contracts: list[dict[str, Any]] = []
    for _, row in snapshot.iterrows():
        c = str(row["contract"])  # 'YYYY-MM'
        try:
            c_period = pd.Period(c, freq="M")
            months_out = (c_period - snap_ym).n
        except Exception:
            months_out = None
        contracts.append({
            "contract": c,
            "value": float(row["value"]),
            "months_out": months_out,
        })

    # Skip already-expired contracts in slope calc
    fwd = [c for c in contracts if c["months_out"] is not None and c["months_out"] >= 0]
    if len(fwd) < 2:
        return {
            "target_date": snapshot_date.strftime("%Y-%m-%d"),
            "futures_indicator": futures_indicator,
            "contracts": contracts,
            "error": "not enough forward contracts for slope",
        }

    front = fwd[0]
    back = fwd[-1]
    second = fwd[1] if len(fwd) > 1 else None

    front_to_back_total = back["value"] - front["value"]
    months_span = max(1, back["months_out"] - front["months_out"])
    slope_per_month = front_to_back_total / months_span

    front_to_2nd_spread = (second["value"] - front["value"]) if second else None

    # Regime classification (relative to front absolute price for scale-free interp)
    relative_slope_pct = slope_per_month / front["value"] * 100 if front["value"] else 0
    regime = _REGIME.classify(relative_slope_pct)

    interp_map = {
        "contango forte": (
            "futuros distantes em forte prêmio sobre o front-month. "
            "Mercado oferece carrego — incentivo para estocar e vender no futuro."
        ),
        "contango leve": (
            "futuros distantes ligeiramente acima do front. "
            "Carrego modesto, dentro do esperado de financial cost-of-carry."
        ),
        "flat": "curva aproximadamente plana — sem sinal direcional via term structure.",
        "backwardation leve": (
            "futuros distantes abaixo do front. "
            "Mercado preferindo disponível, oferta apertada de curto prazo."
        ),
        "backwardation forte": (
            "futuros distantes em forte desconto. "
            "Sinal forte de oferta justa — mercado paga prêmio para ter o produto JÁ."
        ),
    }

    return {
        "futures_indicator": futures_indicator,
        "target_date": snapshot_date.strftime("%Y-%m-%d"),
        "contracts": contracts,
        "front_contract": front["contract"],
        "front_value": front["value"],
        "back_contract": back["contract"],
        "back_value": back["value"],
        "front_to_2nd_spread": (
            round(front_to_2nd_spread, 4) if front_to_2nd_spread is not None else None
        ),
        "front_to_back_total": round(front_to_back_total, 4),
        "months_span": months_span,
        "slope_per_month": round(slope_per_month, 4),
        "relative_slope_pct_per_month": round(relative_slope_pct, 4),
        "regime": regime,
        "interpretation": interp_map[regime],
    }
