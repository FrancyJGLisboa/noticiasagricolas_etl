"""Viz #4 — Per-praça deviation map (scatter geo).

Plots each praça as a point on a map of South America, colored by
(basis_today − mean_5y), sized by n_obs_5y. Diverging color scale RdBu_r:
red = above 5y mean (over), blue = below (under).

Praças without lat/lon in PRACA_COORDS are logged and skipped (do not block
chart generation).
"""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go

from ..basis_config import BasisPairConfig
from .common import PAIR_DISPLAY, PRACA_COORDS
from .companion import compute_stats

logger = logging.getLogger(__name__)


def build(df: pd.DataFrame, pair: BasisPairConfig, window_years: int = 5) -> go.Figure:
    """Build the per-praça deviation map for one pair.

    df must have columns: date, location, state, value.
    """
    info = PAIR_DISPLAY[pair.label]
    fig = go.Figure()

    if df.empty:
        fig.update_layout(title=f"{info.title} — sem dados", template="plotly_white")
        return fig

    stats = compute_stats(df, window_years=window_years)
    if stats.empty:
        fig.update_layout(title=f"{info.title} — sem dados", template="plotly_white")
        return fig

    stats = stats.copy()
    stats["deviation"] = stats["basis_today"] - stats["mean_5y"]
    stats = stats[stats["deviation"].notna()]

    # Attach coords; warn about missing
    coords = stats["location"].map(PRACA_COORDS)
    missing = stats[coords.isna()]["location"].tolist()
    if missing:
        logger.warning(
            "Map %s — %d praça(s) sem coords, omitidas: %s",
            pair.label, len(missing), ", ".join(missing[:8]) + ("…" if len(missing) > 8 else ""),
        )

    plotted = stats[coords.notna()].copy()
    if plotted.empty:
        fig.update_layout(
            title=f"{info.title} — nenhuma praça mapeável",
            template="plotly_white",
        )
        return fig

    plotted["lat"] = plotted["location"].map(lambda x: PRACA_COORDS[x][0])
    plotted["lon"] = plotted["location"].map(lambda x: PRACA_COORDS[x][1])

    # Scale marker size by n_obs (proxy for curve density). Min size for readability.
    n_obs = plotted["n_obs_5y"].clip(lower=1)
    sizes = 8 + 22 * (n_obs / max(n_obs.max(), 1))

    abs_max = max(plotted["deviation"].abs().max(), 1e-6)

    fig.add_trace(go.Scattergeo(
        lon=plotted["lon"],
        lat=plotted["lat"],
        text=plotted["location"],
        customdata=plotted[["state", "basis_today", "mean_5y", "deviation", "pctile_today"]].values,
        mode="markers",
        marker=dict(
            size=sizes,
            color=plotted["deviation"],
            colorscale="RdBu_r",
            cmin=-abs_max,
            cmax=abs_max,
            cmid=0,
            colorbar=dict(title=f"Desvio<br>({info.short_unit})"),
            line=dict(width=0.5, color="rgba(0,0,0,0.4)"),
        ),
        hovertemplate=(
            "<b>%{text}</b> (%{customdata[0]})<br>"
            f"Hoje: %{{customdata[1]:.2f}} {info.short_unit}<br>"
            f"Média 5y: %{{customdata[2]:.2f}} {info.short_unit}<br>"
            f"Desvio: %{{customdata[3]:+.2f}} {info.short_unit}<br>"
            "Percentil: %{customdata[4]:.0f}%<extra></extra>"
        ),
        name="praças",
    ))

    # Top-3 over / under annotations
    top_over = plotted.nlargest(3, "deviation")[["location", "deviation"]]
    top_under = plotted.nsmallest(3, "deviation")[["location", "deviation"]]
    annot_lines = ["<b>Top 3 OVER (long basis):</b>"]
    annot_lines += [f"  {r.location}: {r.deviation:+.2f}" for r in top_over.itertuples()]
    annot_lines.append("")
    annot_lines.append("<b>Top 3 UNDER (short basis):</b>")
    annot_lines += [f"  {r.location}: {r.deviation:+.2f}" for r in top_under.itertuples()]

    today_str = df["date"].max().strftime("%Y-%m-%d")
    fig.update_layout(
        title=f"{info.title} — desvio vs. média {window_years}y (em {today_str})",
        geo=dict(
            scope="south america",
            showcountries=True,
            countrycolor="rgba(0,0,0,0.3)",
            showsubunits=True,
            subunitcolor="rgba(0,0,0,0.15)",
            showland=True,
            landcolor="rgb(243,243,243)",
            showocean=True,
            oceancolor="rgb(220,235,245)",
            projection=dict(type="mercator"),
            center=dict(lat=-15, lon=-52),
            lataxis_range=[-34, 5],
            lonaxis_range=[-75, -34],
        ),
        annotations=[dict(
            x=0.0, y=0.5, xref="paper", yref="paper",
            xanchor="left", yanchor="middle",
            text="<br>".join(annot_lines),
            showarrow=False,
            align="left",
            font=dict(size=10, family="monospace"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="rgba(0,0,0,0.3)",
            borderwidth=1,
        )],
        template="plotly_white",
        height=750,
        margin=dict(l=10, r=10, t=60, b=10),
    )
    return fig
