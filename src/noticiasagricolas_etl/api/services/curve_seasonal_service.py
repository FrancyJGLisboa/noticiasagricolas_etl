"""Forward curve seasonal analysis — is today's curve shape typical for this time of year?

For one futures indicator, computes the historical distribution of the
relative slope per month (front→back, %/month) over a calendar-week window
centered on the target date's day-of-year, across all past years. Compares
today's slope against that distribution and returns a z-score plus a
plain-Portuguese interpretation.

Why a ±2-week window across all years instead of strict same-calendar-month:
6 years of history × strict month bucket ≈ 6 observations per bucket — too
thin for a defensible z-score. Widening to ±N-day window across all past
years gives ~150 obs while still capturing the seasonal context. The window
width is parameterized; default 14 (±14 days = ~29 days of seasonal context
per year × ~6 years).

Baseline is *exclusive of the target date* — we never include the value being
evaluated in its own reference distribution.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ...analytics.diagnostic import Bucket
from .. import database as db

logger = logging.getLogger(__name__)


# Z-score → label/copy. Symmetric thresholds at ±1σ and ±2σ.
_REGIME = Bucket(
    thresholds=(-2.0, -1.0, 1.0, 2.0),
    labels=("muito_abaixo", "abaixo", "tipico", "acima", "muito_acima"),
)

_INTERP: dict[str, str] = {
    "muito_abaixo": (
        "curva MUITO MAIS BACKWARDATED que o típico de {month_pt} — slope "
        "{slope:+.2f}%/m vs média histórica {mean:+.2f}%/m (z={z:+.1f}). "
        "Sinal de oferta apertada de curto prazo fora do padrão sazonal."
    ),
    "abaixo": (
        "curva mais backwardated que o típico de {month_pt} — slope "
        "{slope:+.2f}%/m vs média histórica {mean:+.2f}%/m (z={z:+.1f})."
    ),
    "tipico": (
        "curva dentro do típico de {month_pt} — slope {slope:+.2f}%/m, "
        "média histórica {mean:+.2f}%/m (z={z:+.1f}). Sem sinal sazonal forte."
    ),
    "acima": (
        "curva mais carregada (contango) que o típico de {month_pt} — slope "
        "{slope:+.2f}%/m vs média histórica {mean:+.2f}%/m (z={z:+.1f})."
    ),
    "muito_acima": (
        "curva MUITO MAIS contango que o típico de {month_pt} — slope "
        "{slope:+.2f}%/m vs média histórica {mean:+.2f}%/m (z={z:+.1f}). "
        "Carry implícito acima do normal sazonal — incentivo para estocar."
    ),
}

_MONTH_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def _slopes_history(futures_indicator: str) -> pd.DataFrame:
    """Compute (date, slope_pct_per_month) over all available history.

    For each date with ≥2 forward contracts, picks front and back-most forward
    contracts, computes (back - front) / front / months_span * 100. Front is
    the smallest contract whose YYYY-MM is ≥ the date's YYYY-MM (active);
    back is the largest such contract. Dates with <2 forward contracts are
    skipped — slope is undefined.
    """
    sql = """
        SELECT date, contract, value
        FROM prices
        WHERE indicator = ?
          AND price_basis = 'futures'
          AND measure = 'price'
          AND contract IS NOT NULL
          AND value IS NOT NULL
          AND value > 0
        ORDER BY date, contract
    """
    rows = db.query(sql, [futures_indicator])
    if not rows:
        return pd.DataFrame(columns=["date", "slope_pct_per_month"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    slopes: list[dict] = []
    for dt, group in df.groupby("date"):
        date_ym = f"{dt.year}-{dt.month:02d}"
        forward = group[group["contract"] >= date_ym].copy()
        if len(forward) < 2:
            continue
        forward = forward.sort_values("contract")
        front = forward.iloc[0]
        back = forward.iloc[-1]

        # Months between contracts
        front_period = pd.Period(str(front["contract"]), freq="M")
        back_period = pd.Period(str(back["contract"]), freq="M")
        months_span = (back_period - front_period).n
        if months_span < 1:
            continue

        front_v = float(front["value"])
        if front_v <= 0:
            continue
        slope = (float(back["value"]) - front_v) / front_v / months_span * 100.0
        slopes.append({"date": dt, "slope_pct_per_month": slope})

    return pd.DataFrame(slopes)


def _seasonal_window(
    slopes: pd.DataFrame,
    target_date: pd.Timestamp,
    window_days: int,
) -> pd.DataFrame:
    """Pull all past dates whose day-of-year is within ±window_days of target's,
    *excluding* the target date itself. Cross-year-boundary aware.
    """
    if slopes.empty:
        return slopes

    target_doy = int(target_date.dayofyear)
    doys = slopes["date"].dt.dayofyear

    # Cross-year-boundary distance: shortest path on a 365-day circle
    diff = (doys - target_doy).abs()
    diff = diff.where(diff <= 182, 365 - diff)

    in_window = diff <= window_days
    not_target = slopes["date"] != target_date
    return slopes[in_window & not_target].copy()


def get_curve_seasonal(
    futures_indicator: str,
    target_date: str | None = None,
    window_days: int = 14,
    min_obs: int = 20,
) -> dict[str, Any]:
    """Compare today's forward-curve slope to the historical seasonal distribution.

    Args:
        futures_indicator: e.g. 'soja-bolsa-de-chicago-cme-group'.
        target_date: ISO 'YYYY-MM-DD'; None = latest available date with ≥2
            forward contracts.
        window_days: ±days around target's day-of-year to define the seasonal
            window. Default 14 (~29-day window per year × ~6 years ≈ 150 obs).
        min_obs: minimum observations in the seasonal window to compute a
            z-score. Below this, return a {'error': 'insufficient seasonal history'}.

    Returns:
        Dict with target_date, current_slope_pct_per_month, regime label,
        seasonal_baseline (mean, std, n_obs, p25, p50, p75), z_score, and a
        plain-Portuguese interpretation string. Or {'error': ...} on missing
        data conditions.
    """
    slopes = _slopes_history(futures_indicator)
    if slopes.empty:
        return {"error": f"no slope history for {futures_indicator}"}

    slopes = slopes.sort_values("date").reset_index(drop=True)

    if target_date is not None:
        td = pd.Timestamp(target_date)
        sub = slopes[slopes["date"] <= td]
        if sub.empty:
            return {"error": f"no slope data on or before {target_date}"}
        target_row = sub.iloc[-1]
    else:
        target_row = slopes.iloc[-1]

    target_d = target_row["date"]
    target_slope = float(target_row["slope_pct_per_month"])

    seasonal = _seasonal_window(slopes, target_d, window_days)
    n_obs = int(len(seasonal))

    if n_obs < min_obs:
        return {
            "futures_indicator": futures_indicator,
            "target_date": target_d.strftime("%Y-%m-%d"),
            "current_slope_pct_per_month": round(target_slope, 4),
            "error": (
                f"insufficient seasonal history: only {n_obs} obs in ±{window_days}d "
                f"window (need ≥{min_obs}). Backfill more history or widen window."
            ),
        }

    values = seasonal["slope_pct_per_month"]
    mean = float(values.mean())
    std = float(values.std(ddof=1))

    if std == 0 or np.isnan(std):
        return {
            "futures_indicator": futures_indicator,
            "target_date": target_d.strftime("%Y-%m-%d"),
            "current_slope_pct_per_month": round(target_slope, 4),
            "error": "zero variance in seasonal window — no z-score computable",
        }

    z = (target_slope - mean) / std
    regime = _REGIME.classify(z)

    interp = _INTERP[regime].format(
        month_pt=_MONTH_PT[target_d.month],
        slope=target_slope, mean=mean, z=z,
    )

    return {
        "futures_indicator": futures_indicator,
        "target_date": target_d.strftime("%Y-%m-%d"),
        "current_slope_pct_per_month": round(target_slope, 4),
        "regime": regime,
        "z_score": round(z, 3),
        "window_days": window_days,
        "seasonal_baseline": {
            "n_obs": n_obs,
            "mean": round(mean, 4),
            "std": round(std, 4),
            "p25": round(float(values.quantile(0.25)), 4),
            "p50_median": round(float(values.quantile(0.50)), 4),
            "p75": round(float(values.quantile(0.75)), 4),
            "min": round(float(values.min()), 4),
            "max": round(float(values.max()), 4),
        },
        "interpretation": interp,
    }
