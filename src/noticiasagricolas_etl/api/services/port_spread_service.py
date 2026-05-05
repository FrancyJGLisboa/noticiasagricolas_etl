"""Spread between port and interior physical prices.

Captures the implicit logistics premium + export demand. Tight spread =
porto barato relative to interior = exportador apertado, escoamento parado.
Wide spread = porto caro = janela de exportação aberta.

Port praças are hardcoded — they're the few that quote FOB/disponível port:
  Porto Paranaguá, Porto Santos, Porto Rio Grande, Paranaguá (bare).
"""

from typing import Any

import pandas as pd

from .. import database as db


PORT_LOCATIONS: set[str] = {
    "Porto Paranaguá/PR",
    "Porto Santos/SP",
    "Porto Rio Grande/RS",
    "Porto São Francisco do Sul/SC",
    "Porto Imbituba/SC",
    "Paranaguá/PR",  # bare-city alias of Porto Paranaguá
}


def _is_port(loc: str) -> bool:
    if loc in PORT_LOCATIONS:
        return True
    # Heuristic: starts with "Porto " catches future variants
    return loc.startswith("Porto ")


def get_port_spread(
    commodity: str,
    interior_location: str,
    futures_indicator: str | None = None,
    target_date: str | None = None,
    window_years: int = 5,
) -> dict[str, Any]:
    """Compute spread = port_avg - interior_price for a single commodity-praça.

    Args:
        commodity: 'soja' or 'milho' (the commodities with port quotes).
        interior_location: e.g. 'Sorriso/MT' (the praça to compare against ports).
        futures_indicator: optional — restricts to one pair's joined data.
        target_date: ISO; None = latest.
        window_years: history window for percentile (default 5).

    Returns:
        Spread time series + current value, percentile, mean/min/max,
        interpretation, identifying which port reference is used.
    """
    sql = """
        SELECT date, location, physical_price_brl
        FROM basis
        WHERE commodity = ?
          AND physical_price_brl IS NOT NULL
        ORDER BY date, location
    """
    params: list[object] = [commodity]
    if futures_indicator:
        sql = sql.replace(
            "physical_price_brl IS NOT NULL",
            "physical_price_brl IS NOT NULL AND futures_indicator = ?",
        )
        params.append(futures_indicator)

    rows = db.query(sql, params)
    if not rows:
        return {"error": f"no data for commodity {commodity!r}"}

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # Daily mean across port locations (handles 5+ port aliases)
    df["is_port"] = df["location"].apply(_is_port)
    port_df = df[df["is_port"]].groupby("date", as_index=False)["physical_price_brl"].mean()
    port_df = port_df.rename(columns={"physical_price_brl": "port_price"})
    if port_df.empty:
        return {"error": "no port quotes found in this dataset"}

    interior_df = df[df["location"] == interior_location][["date", "physical_price_brl"]]
    interior_df = interior_df.rename(columns={"physical_price_brl": "interior_price"})
    interior_df = interior_df.drop_duplicates("date").sort_values("date")
    if interior_df.empty:
        return {"error": f"no data for interior_location {interior_location!r}"}

    merged = interior_df.merge(port_df, on="date", how="inner")
    merged["spread"] = merged["port_price"] - merged["interior_price"]
    if merged.empty:
        return {"error": "no overlapping dates between port and interior"}

    # Pick target date
    if target_date:
        td = pd.Timestamp(target_date)
        sub = merged[merged["date"] <= td]
        if sub.empty:
            return {"error": f"no data on or before {target_date}"}
        target_row = sub.iloc[-1]
    else:
        target_row = merged.iloc[-1]

    target_d = target_row["date"].strftime("%Y-%m-%d")
    spread_today = float(target_row["spread"])

    cutoff = target_row["date"] - pd.DateOffset(years=window_years)
    window = merged[(merged["date"] >= cutoff) & (merged["date"] <= target_row["date"])]["spread"]
    if window.empty:
        return {"error": "empty window"}

    pct = float((window <= spread_today).mean() * 100.0)

    if pct >= 75:
        interp = (
            f"spread ALTO — P{pct:.0f}. Porto caro vs interior. "
            "Janela de exportação aberta, exportador disposto a pagar prêmio. "
            "Produtor interior captura mais do prêmio FOB."
        )
    elif pct <= 25:
        interp = (
            f"spread BAIXO — P{pct:.0f}. Porto barato vs interior. "
            "Escoamento desacelerado — produtor interior segura grão até porto recompor."
        )
    else:
        interp = f"spread NORMAL — P{pct:.0f}, faixa típica de logística + prêmio."

    return {
        "commodity": commodity,
        "interior_location": interior_location,
        "futures_indicator": futures_indicator,
        "target_date": target_d,
        "port_price_today": round(float(target_row["port_price"]), 4),
        "interior_price_today": round(float(target_row["interior_price"]), 4),
        "spread_today_brl_per_sc": round(spread_today, 4),
        "percentile": round(pct, 2),
        "window_years": window_years,
        "n_obs": int(window.count()),
        "mean": round(float(window.mean()), 4),
        "p25": round(float(window.quantile(0.25)), 4),
        "p75": round(float(window.quantile(0.75)), 4),
        "min": round(float(window.min()), 4),
        "max": round(float(window.max()), 4),
        "interpretation": interp,
    }
