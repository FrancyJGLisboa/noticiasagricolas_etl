"""Commodity price ratio analysis (e.g., soja/milho for crop allocation).

The most useful in the BR ag context is soja:milho — the historical
ratio drives planting intent for the upcoming safra. Generic over any
two indicators with an inner join on date.
"""

from typing import Any

import pandas as pd

from ...analytics.diagnostic import PERCENTILE_3, compute_window_stats
from .. import database as db


def _interp(bucket: str, pct: float, num: str, den: str) -> str:
    head = num.split("-")[0]
    tail = den.split("-")[0]
    if bucket == "high":
        return (
            f"ratio ALTO — P{pct:.0f}. {head} caro vs {tail}. "
            f"Favorece plantio de {head} na próxima safra."
        )
    if bucket == "low":
        return (
            f"ratio BAIXO — P{pct:.0f}. {head} barato vs {tail}. "
            f"Favorece plantio de {tail} na próxima safra."
        )
    return f"ratio NORMAL — P{pct:.0f}, dentro da faixa típica."


def get_ratio(
    numerator_indicator: str,
    denominator_indicator: str,
    location: str | None = None,
    measure: str = "price",
    target_date: str | None = None,
    window_years: int = 5,
) -> dict[str, Any]:
    """Compute the time-series ratio of two indicator prices.

    When both indicators are quoted in the same unit (e.g., R$/sc60kg for soja
    and milho mercado-físico), the ratio is dimensionless and directly
    comparable. Otherwise the user should be aware that the ratio mixes units.

    Args:
        numerator_indicator: e.g. 'soja-mercado-fisico-sindicatos-e-cooperativas'.
        denominator_indicator: e.g. 'milho-mercado-fisico-sindicatos-e-cooperativas'.
        location: optional praça filter (must exist for both indicators).
        target_date: ISO date 'YYYY-MM-DD' for the "today" rating. None = latest.
        window_years: history window for percentile computation.

    Returns:
        Dict with current ratio, percentile, recent series sample,
        and historical descriptive stats.
    """

    def _load(ind: str) -> pd.DataFrame:
        params: list[object] = [ind, measure]
        loc_clause = ""
        if location:
            loc_clause = "AND location = ?"
            params.append(location)
        sql = f"""
            SELECT date, value
            FROM prices
            WHERE indicator = ? AND measure = ? {loc_clause}
              AND value IS NOT NULL
        """
        rows = db.query(sql, params)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        # Average across praças for that date if no location filter
        return df.groupby("date", as_index=False)["value"].mean()

    num_df = _load(numerator_indicator).rename(columns={"value": "num"})
    den_df = _load(denominator_indicator).rename(columns={"value": "den"})

    if num_df.empty or den_df.empty:
        return {"error": "no data for one or both indicators"}

    merged = num_df.merge(den_df, on="date", how="inner")
    merged = merged[merged["den"] != 0]
    if merged.empty:
        return {"error": "no overlapping non-zero dates"}
    merged["ratio"] = merged["num"] / merged["den"]
    merged = merged.sort_values("date").reset_index(drop=True)

    stats = compute_window_stats(
        merged,
        value_col="ratio",
        target_date=target_date,
        window_years=window_years,
    )
    if isinstance(stats, dict):
        return stats

    bucket = PERCENTILE_3.classify(stats.percentile)
    interp = _interp(bucket, stats.percentile, numerator_indicator, denominator_indicator)

    # Sample of last 30 daily values for trend visibility
    tail = merged.tail(30)[["date", "num", "den", "ratio"]].copy()
    tail["date"] = tail["date"].dt.strftime("%Y-%m-%d")

    base = stats.as_dict()
    base["current_ratio"] = base.pop("value")

    return {
        "numerator_indicator": numerator_indicator,
        "denominator_indicator": denominator_indicator,
        "location": location or "ALL (mean across praças)",
        **base,
        "window_years": window_years,
        "interpretation": interp,
        "recent_30d": tail.to_dict(orient="records"),
    }
