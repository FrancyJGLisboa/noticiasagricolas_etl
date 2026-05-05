"""Viz #2 — Multi-praça time series (last N years) + companion table.

One figure per pair. Each praça is a line; click legend to toggle. Range slider
on the X axis. Below the chart, a Plotly table shows the companion KPIs from
viz/companion.py for each praça.
"""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..basis_config import BasisPairConfig
from .common import PAIR_DISPLAY
from .companion import compute_stats

logger = logging.getLogger(__name__)


def _format_table_value(v: object) -> str:
    """Format a value for the companion table — float to 2 dp, NA otherwise."""
    if pd.isna(v):
        return "—"
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return f"{v}"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def build(df: pd.DataFrame, pair: BasisPairConfig, window_years: int = 5) -> go.Figure:
    """Build the multi-location chart with embedded companion table.

    df must have columns: date, location, state, value.
    """
    info = PAIR_DISPLAY[pair.label]

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.65, 0.35],
        specs=[[{"type": "scatter"}], [{"type": "table"}]],
        vertical_spacing=0.08,
        subplot_titles=(info.title, "Companion stats — basis hoje, médias, percentil"),
    )

    if df.empty:
        fig.update_layout(template="plotly_white", height=900)
        return fig

    today = df["date"].max()
    cutoff = today - pd.DateOffset(years=window_years)
    windowed = df[df["date"] >= cutoff].copy()

    # Order locations by total observations (most active first → top of legend)
    loc_order = (
        windowed.groupby("location")["value"]
        .count()
        .sort_values(ascending=False)
        .index.tolist()
    )

    for loc in loc_order:
        loc_df = windowed[windowed["location"] == loc]
        if loc_df.empty:
            continue
        state = loc_df["state"].dropna().iloc[0] if loc_df["state"].notna().any() else "??"
        fig.add_trace(
            go.Scatter(
                x=loc_df["date"],
                y=loc_df["value"],
                mode="lines",
                name=loc,
                meta={"state": state},
                hovertemplate=(
                    f"<b>{loc}</b><br>"
                    "Data: %{x|%Y-%m-%d}<br>"
                    f"Basis: %{{y:.2f}} {info.short_unit}<br>"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )

    # Companion table from full df (window 5y inside compute_stats)
    stats = compute_stats(df, window_years=window_years)
    if not stats.empty:
        header = ["Praça", "UF", "Hoje", "D-1", "Sem.", "Mês", "Méd 3y", "Méd 5y", "Min 5y", "Max 5y", "Pctl", "n obs"]
        cells = [
            stats["location"].tolist(),
            [s if s else "—" for s in stats["state"].tolist()],
            [_format_table_value(v) for v in stats["basis_today"]],
            [_format_table_value(v) for v in stats["basis_d1"]],
            [_format_table_value(v) for v in stats["basis_w1"]],
            [_format_table_value(v) for v in stats["basis_m1"]],
            [_format_table_value(v) for v in stats["mean_3y"]],
            [_format_table_value(v) for v in stats["mean_5y"]],
            [_format_table_value(v) for v in stats["min_5y"]],
            [_format_table_value(v) for v in stats["max_5y"]],
            [_format_table_value(v) for v in stats["pctile_today"]],
            stats["n_obs_5y"].tolist(),
        ]
        fig.add_trace(
            go.Table(
                header=dict(values=header, fill_color="#e8eaed", align="left", font=dict(size=11)),
                cells=dict(values=cells, align="left", font=dict(size=10), height=22),
            ),
            row=2, col=1,
        )

    fig.update_xaxes(rangeslider=dict(visible=True), row=1, col=1, title_text="Data")
    fig.update_yaxes(title_text=info.yaxis, row=1, col=1)
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=1.02),
        template="plotly_white",
        height=950,
        showlegend=True,
    )
    return fig
