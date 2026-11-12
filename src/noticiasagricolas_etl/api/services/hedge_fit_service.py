"""Contract-consistent hedge effectiveness calculations."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ...analytics.basis_signals import (
    DAILY_MAX_GAP_DAYS,
    WEEKLY_MAX_GAP_DAYS,
    classified_changes,
    is_cbot,
    weekly_observations,
)
from ...analytics.diagnostic import Bucket
from .. import database as db

_QUALITY = Bucket(
    thresholds=(0.3, 0.5, 0.7),
    labels=("POBRE", "MARGINAL", "BOM", "EXCELENTE"),
)

_INTERP: dict[str, str] = {
    "EXCELENTE": "A regressão explica {r2:.0%} da variação física. O beta estimado é {beta:.3f}.",
    "BOM": "A regressão explica {r2:.0%} da variação física. Ainda existe risco de basis.",
    "MARGINAL": "A regressão explica {r2:.0%} da variação física. O risco de basis é relevante.",
    "POBRE": "A regressão explica somente {r2:.0%} da variação física nesta praça.",
}


def _ols(x: pd.Series, y: pd.Series) -> dict[str, Any] | None:
    """Fit y = alpha + beta*x and return serializable metrics."""
    clean = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(clean) < 20:
        return None

    x_values = clean["x"].to_numpy(dtype=float)
    y_values = clean["y"].to_numpy(dtype=float)
    var_x = float(np.var(x_values, ddof=1))
    if var_x == 0 or np.isnan(var_x):
        return None

    beta = float(np.cov(x_values, y_values, ddof=1)[0, 1] / var_x)
    alpha = float(np.mean(y_values) - beta * np.mean(x_values))
    residual = y_values - (alpha + beta * x_values)
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((y_values - np.mean(y_values)) ** 2))
    variance_y = float(np.var(y_values, ddof=1))
    if ss_tot <= 0 or variance_y <= 0 or np.isnan(variance_y):
        return None
    r_squared = 1 - ss_res / ss_tot
    variance_residual = float(np.var(residual, ddof=1))
    variance_reduction = 100 * (1 - variance_residual / variance_y)
    correlation = float(np.corrcoef(x_values, y_values)[0, 1])
    quality = _QUALITY.classify(r_squared)
    return {
        "n_obs": len(clean),
        "beta": round(beta, 4),
        "alpha": round(alpha, 4),
        "r_squared": round(r_squared, 4),
        "correlation": round(correlation, 4),
        "variance_reduction_pct": round(variance_reduction, 2),
        "quality": quality,
        "interpretation": _INTERP[quality].format(r2=r_squared, beta=beta),
    }


def fit_hedge_frame(
    frame: pd.DataFrame,
    *,
    commodity: str,
    location: str,
    futures_indicator: str,
    window_years: int = 5,
    frequency: str = "weekly",
) -> dict[str, Any]:
    """Fit a hedge model from an in-memory aligned basis frame."""
    if frequency not in {"daily", "weekly"}:
        return {"error": f"frequency must be 'daily' or 'weekly'; got {frequency!r}"}

    required = {
        "date",
        "physical_price_brl",
        "futures_price_brl",
        "futures_contract",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        return {"error": f"missing required columns: {', '.join(missing)}"}

    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.dropna(subset=["physical_price_brl", "futures_price_brl"])
    work = work.sort_values("date").drop_duplicates("date", keep="last")
    if work.empty:
        return {"error": "no aligned physical+futures data"}

    cutoff = work["date"].max() - pd.DateOffset(years=window_years)
    work = work[work["date"] >= cutoff].reset_index(drop=True)
    cbot = is_cbot(futures_indicator)
    if cbot:
        if "ptax" not in work.columns:
            return {"error": "CBOT hedge fit requires PTAX"}
        work = work.dropna(subset=["ptax"])
        work = work[work["ptax"] != 0].copy()
        work["physical_primary"] = work["physical_price_brl"] / work["ptax"]
        work["futures_primary"] = work["futures_price_brl"] / work["ptax"]
        signal_currency = "USD"
    else:
        work["physical_primary"] = work["physical_price_brl"]
        work["futures_primary"] = work["futures_price_brl"]
        signal_currency = "BRL"

    max_gap_days = DAILY_MAX_GAP_DAYS
    if frequency == "weekly":
        work = weekly_observations(work)
        max_gap_days = WEEKLY_MAX_GAP_DAYS

    transitions, counts = classified_changes(
        work,
        value_col="physical_primary",
        max_gap_days=max_gap_days,
    )
    valid = transitions["valid_change"].to_numpy(dtype=bool)
    primary_physical = work["physical_primary"].astype(float).diff().where(valid)
    primary_futures = work["futures_primary"].astype(float).diff().where(valid)
    primary_fit = _ols(primary_futures, primary_physical)

    base = {
        "commodity": commodity,
        "location": location,
        "futures_indicator": futures_indicator,
        "frequency": frequency,
        "window_years": window_years,
        "signal_currency": signal_currency,
        "max_gap_days": max_gap_days,
        **counts,
    }
    if primary_fit is None:
        n_valid = int(
            pd.DataFrame({"x": primary_futures, "y": primary_physical})
            .dropna()
            .shape[0]
        )
        return {**base, "error": f"only {n_valid} valid return obs after filtering"}

    result = {**base, **primary_fit}
    if cbot:
        physical_brl = work["physical_price_brl"].astype(float).diff().where(valid)
        futures_brl = work["futures_price_brl"].astype(float).diff().where(valid)
        result["brl_fit"] = _ols(futures_brl, physical_brl)
    return result


def get_hedge_fit(
    commodity: str,
    location: str,
    futures_indicator: str,
    window_years: int = 5,
    frequency: str = "weekly",
) -> dict[str, Any]:
    """Load aligned prices and fit a roll-aware, gap-aware hedge model."""
    sql = """
        SELECT date, physical_price_brl, futures_price_brl,
               futures_contract, ptax
        FROM basis
        WHERE commodity = ?
          AND location = ?
          AND futures_indicator = ?
          AND physical_price_brl IS NOT NULL
          AND futures_price_brl IS NOT NULL
        ORDER BY date
    """
    rows = db.query(sql, [commodity, location, futures_indicator])
    return fit_hedge_frame(
        pd.DataFrame(rows),
        commodity=commodity,
        location=location,
        futures_indicator=futures_indicator,
        window_years=window_years,
        frequency=frequency,
    )
