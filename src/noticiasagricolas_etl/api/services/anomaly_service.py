"""Anomaly detection: today's value vs trailing rolling-window distribution.

Computes a z-score of the current observation against the rolling N-day
mean and std of the same series. |z| > 3 = anomaly.

Two layers:
  - Data quality: flags potential typos/errors in scraped values
  - Market signal: flags genuine large moves worth investigating
"""

from typing import Any

import numpy as np
import pandas as pd

from ...analytics.diagnostic import Bucket
from .. import database as db


_SEVERITY = Bucket(
    thresholds=(2.0, 3.0, 4.0),
    labels=("normal", "mild", "moderate", "severe"),
)


def _load_series(
    indicator: str,
    location: str | None,
    measure: str = "price",
) -> pd.DataFrame:
    """Load a single time series from the prices view."""
    sql = "SELECT date, value FROM prices WHERE indicator = ? AND measure = ? AND value IS NOT NULL"
    params: list[object] = [indicator, measure]
    if location:
        sql += " AND location = ?"
        params.append(location)
    sql += " ORDER BY date"
    rows = db.query(sql, params)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    # Average across rows for the same date (handles multi-column scrapes)
    df = df.groupby("date", as_index=False)["value"].mean()
    return df


def detect_anomaly(
    indicator: str,
    location: str | None = None,
    target_date: str | None = None,
    window_days: int = 60,
    z_threshold: float = 3.0,
    measure: str = "price",
) -> dict[str, Any]:
    """Detect if target_date's value is an outlier vs the trailing window_days.

    Args:
        indicator: e.g. 'soja-mercado-fisico-sindicatos-e-cooperativas'.
        location: optional praça filter.
        target_date: ISO; None = latest.
        window_days: trailing window for mean/std (default 60).
        z_threshold: |z| above which we flag as anomaly (default 3.0).

    Returns:
        Dict with target_value, z_score, mean/std/min/max of window,
        is_anomaly bool, severity ('normal'/'mild'/'severe'), interpretation.
    """
    df = _load_series(indicator, location, measure)
    if df.empty:
        return {"error": "no data"}

    if target_date:
        td = pd.Timestamp(target_date)
        sub = df[df["date"] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        target_idx = sub.index[-1]
    else:
        target_idx = df.index[-1]

    target_row = df.loc[target_idx]
    target_d = target_row["date"].strftime("%Y-%m-%d")
    target_v = float(target_row["value"])

    # Trailing window — strictly before target_date so we don't include itself
    cutoff = target_row["date"] - pd.Timedelta(days=window_days)
    window = df[(df["date"] >= cutoff) & (df["date"] < target_row["date"])]["value"]

    if len(window) < 10:
        return {
            "target_date": target_d,
            "value": target_v,
            "error": f"insufficient history ({len(window)} obs in last {window_days}d)",
        }

    mean = float(window.mean())
    std = float(window.std())
    if std == 0 or np.isnan(std):
        return {
            "target_date": target_d,
            "value": target_v,
            "error": "zero variance in window — series flat",
        }

    z = (target_v - mean) / std
    is_anomaly = abs(z) >= z_threshold

    severity = _SEVERITY.classify(abs(z))

    direction = "acima" if z > 0 else "abaixo"

    if is_anomaly:
        interp = (
            f"⚠ ANOMALIA {severity.upper()} — valor R$ {target_v:.2f} está "
            f"{abs(z):.1f}σ {direction} da média trailing {window_days}d "
            f"(R$ {mean:.2f} ± {std:.2f}). "
            "Verificar se é erro de cotação ou evento real de mercado."
        )
    else:
        interp = (
            f"NORMAL — z-score {z:+.2f} dentro de ±{z_threshold:.1f}σ. "
            f"Valor R$ {target_v:.2f} consistente com a janela "
            f"({mean:.2f} ± {std:.2f})."
        )

    return {
        "indicator": indicator,
        "location": location,
        "target_date": target_d,
        "value": round(target_v, 4),
        "z_score": round(z, 4),
        "is_anomaly": bool(is_anomaly),
        "severity": severity,
        "z_threshold": z_threshold,
        "window_days": window_days,
        "n_obs_window": int(len(window)),
        "window_mean": round(mean, 4),
        "window_std": round(std, 4),
        "window_min": round(float(window.min()), 4),
        "window_max": round(float(window.max()), 4),
        "interpretation": interp,
    }
