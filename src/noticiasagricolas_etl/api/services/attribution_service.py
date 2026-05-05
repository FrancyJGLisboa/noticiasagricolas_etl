"""Price change attribution: decompose ΔP_local into FX vs CBOT vs basis.

For a praça with physical price quoted in BRL and a CBOT futures reference
in USD, the local-price change between two dates can be decomposed:

    ΔP_local ≈ Δbasis + bu_per_sc × (fut_1 × Δptax + ptax_1 × Δfut)

Where:
    - Δbasis  = change in local basis (idiosyncratic logistics/margin)
    - bu_per_sc × fut_1 × Δptax  = FX bucket (BRL devaluation effect)
    - bu_per_sc × ptax_1 × Δfut  = CBOT bucket (futures move effect)

This separates 'real local supply/demand' (basis) from 'macro shocks' (FX, CBOT).
"""

from typing import Any

import pandas as pd

from .. import database as db


# Bushels per saca (60 kg) for the grain pairs
BU_PER_SC = {
    "soja-bolsa-de-chicago-cme-group": 60.0 / 27.2155,
    "milho-bolsa-de-chicago-cme-group": 60.0 / 25.4012,
    "trigo-bolsa-de-chicago-cme-group": 60.0 / 27.2155,
}


def _load_series(commodity: str, location: str, futures_indicator: str) -> pd.DataFrame:
    """Load aligned (date, physical, futures_raw, ptax) rows from basis view."""
    sql = """
        SELECT date, physical_price_brl, futures_price_raw, ptax
        FROM basis
        WHERE commodity = ?
          AND location = ?
          AND futures_indicator = ?
          AND physical_price_brl IS NOT NULL
          AND futures_price_raw IS NOT NULL
          AND ptax IS NOT NULL
        ORDER BY date
    """
    rows = db.query(sql, [commodity, location, futures_indicator])
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def attribute_change(
    commodity: str,
    location: str,
    futures_indicator: str,
    date_from: str,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Decompose price change between two dates into FX / CBOT / basis buckets.

    Args:
        commodity: e.g. 'soja', 'milho'.
        location: e.g. 'Sorriso/MT'.
        futures_indicator: must be a CBOT pair with bu_per_sc defined.
        date_from: ISO 'YYYY-MM-DD' start (exclusive of return).
        date_to: ISO 'YYYY-MM-DD' end. None = latest available.

    Returns:
        Dict with start/end snapshots, total ΔP_local, three buckets
        (basis_contribution, fx_contribution, cbot_contribution),
        residual (cross-term), interpretation.
    """
    if futures_indicator not in BU_PER_SC:
        return {
            "error": f"futures_indicator {futures_indicator!r} not supported "
                     f"(need bu_per_sc). Supported: {list(BU_PER_SC.keys())}"
        }
    bu = BU_PER_SC[futures_indicator]

    df = _load_series(commodity, location, futures_indicator)
    if df.empty:
        return {"error": "no data for this combination"}

    start_d = pd.Timestamp(date_from)
    sub_start = df[df["date"] <= start_d]
    if sub_start.empty:
        return {"error": f"no data on or before {date_from}"}
    start_row = sub_start.iloc[-1]

    if date_to:
        end_d = pd.Timestamp(date_to)
        sub_end = df[df["date"] <= end_d]
        if sub_end.empty:
            return {"error": f"no data on or before {date_to}"}
        end_row = sub_end.iloc[-1]
    else:
        end_row = df.iloc[-1]

    if end_row["date"] <= start_row["date"]:
        return {"error": "end date must be after start date"}

    p1, p2 = float(start_row["physical_price_brl"]), float(end_row["physical_price_brl"])
    f1, f2 = float(start_row["futures_price_raw"]), float(end_row["futures_price_raw"])
    x1, x2 = float(start_row["ptax"]), float(end_row["ptax"])

    fut_brl_1 = f1 * bu * x1
    fut_brl_2 = f2 * bu * x2
    basis_1 = p1 - fut_brl_1
    basis_2 = p2 - fut_brl_2

    delta_p = p2 - p1
    delta_basis = basis_2 - basis_1
    delta_fut = f2 - f1
    delta_ptax = x2 - x1

    fx_contrib = bu * f1 * delta_ptax            # FX move at constant CBOT
    cbot_contrib = bu * x1 * delta_fut           # CBOT move at constant FX
    cross = bu * delta_fut * delta_ptax          # cross-term (small)
    # Sanity: total should equal delta_p
    reconstructed = delta_basis + fx_contrib + cbot_contrib + cross
    residual = delta_p - reconstructed  # numerical noise, should be ~0

    abs_total = abs(delta_p) if delta_p != 0 else 1e-9
    pct_basis = 100 * delta_basis / abs_total
    pct_fx = 100 * fx_contrib / abs_total
    pct_cbot = 100 * cbot_contrib / abs_total

    # Identify dominant driver
    drivers = {"basis": pct_basis, "FX": pct_fx, "CBOT": pct_cbot}
    dominant = max(drivers.items(), key=lambda kv: abs(kv[1]))
    direction = "alta" if delta_p > 0 else "queda"

    interp = (
        f"Preço local {direction} de {abs(delta_p):.2f} R$/sc no período. "
        f"Contribuição dominante: {dominant[0]} ({dominant[1]:+.0f}% do movimento). "
    )
    if abs(pct_basis) > 60:
        interp += "Movimento foi principalmente de basis local (oferta/demanda regional)."
    elif abs(pct_fx) > 60:
        interp += "Movimento foi principalmente cambial — fundamentos não mudaram muito."
    elif abs(pct_cbot) > 60:
        interp += "Movimento foi principalmente externo (CBOT)."
    else:
        interp += "Movimento misto — três fatores contribuindo."

    return {
        "commodity": commodity,
        "location": location,
        "futures_indicator": futures_indicator,
        "start_date": start_row["date"].strftime("%Y-%m-%d"),
        "end_date": end_row["date"].strftime("%Y-%m-%d"),
        "snapshot_start": {
            "physical_brl_per_sc": round(p1, 4),
            "futures_usd_per_bu": round(f1, 4),
            "ptax_brl_per_usd": round(x1, 4),
            "futures_brl_per_sc": round(fut_brl_1, 4),
            "basis_brl_per_sc": round(basis_1, 4),
        },
        "snapshot_end": {
            "physical_brl_per_sc": round(p2, 4),
            "futures_usd_per_bu": round(f2, 4),
            "ptax_brl_per_usd": round(x2, 4),
            "futures_brl_per_sc": round(fut_brl_2, 4),
            "basis_brl_per_sc": round(basis_2, 4),
        },
        "delta_total_brl_per_sc": round(delta_p, 4),
        "buckets_brl_per_sc": {
            "basis": round(delta_basis, 4),
            "fx": round(fx_contrib, 4),
            "cbot": round(cbot_contrib, 4),
            "cross_term": round(cross, 4),
            "residual": round(residual, 6),
        },
        "buckets_pct_of_move": {
            "basis": round(pct_basis, 2),
            "fx": round(pct_fx, 2),
            "cbot": round(pct_cbot, 2),
        },
        "dominant_driver": dominant[0],
        "interpretation": interp,
    }
