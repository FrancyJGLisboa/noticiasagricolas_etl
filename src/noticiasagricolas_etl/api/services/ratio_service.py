"""Commodity price ratio analysis (e.g., soja/milho for crop allocation).

The most useful in the BR ag context is soja:milho — the historical
ratio drives planting intent for the upcoming safra. Generic over any
two indicators with an inner join on date.
"""

from typing import Any

import pandas as pd

from .. import database as db


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

    if target_date:
        td = pd.Timestamp(target_date)
        sub = merged[merged["date"] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        target_row = sub.iloc[-1]
    else:
        target_row = merged.iloc[-1]

    target_d = target_row["date"].strftime("%Y-%m-%d")
    target_ratio = float(target_row["ratio"])

    cutoff = target_row["date"] - pd.DateOffset(years=window_years)
    window = merged[(merged["date"] >= cutoff) & (merged["date"] <= target_row["date"])]["ratio"]
    if window.empty:
        return {"error": "empty window"}

    pct = float((window <= target_ratio).mean() * 100.0)

    # Soja/Milho-specific interpretation hints (works for any 2 grain ratio)
    if pct >= 75:
        interp = (
            f"ratio ALTO — P{pct:.0f}. {numerator_indicator.split('-')[0]} "
            f"caro vs {denominator_indicator.split('-')[0]}. "
            f"Favorece plantio de {numerator_indicator.split('-')[0]} na próxima safra."
        )
    elif pct <= 25:
        interp = (
            f"ratio BAIXO — P{pct:.0f}. {numerator_indicator.split('-')[0]} "
            f"barato vs {denominator_indicator.split('-')[0]}. "
            f"Favorece plantio de {denominator_indicator.split('-')[0]} na próxima safra."
        )
    else:
        interp = f"ratio NORMAL — P{pct:.0f}, dentro da faixa típica."

    # Sample of last 30 daily values for trend visibility
    tail = merged.tail(30)[["date", "num", "den", "ratio"]].copy()
    tail["date"] = tail["date"].dt.strftime("%Y-%m-%d")

    return {
        "numerator_indicator": numerator_indicator,
        "denominator_indicator": denominator_indicator,
        "location": location or "ALL (mean across praças)",
        "target_date": target_d,
        "current_ratio": round(target_ratio, 4),
        "percentile": round(pct, 2),
        "window_years": window_years,
        "mean": round(float(window.mean()), 4),
        "p25": round(float(window.quantile(0.25)), 4),
        "p50": round(float(window.quantile(0.50)), 4),
        "p75": round(float(window.quantile(0.75)), 4),
        "min": round(float(window.min()), 4),
        "max": round(float(window.max()), 4),
        "n_obs": int(window.count()),
        "interpretation": interp,
        "recent_30d": tail.to_dict(orient="records"),
    }
