"""Viz #5 — z-score heatmap (praça × week).

Each cell is the weekly-median basis at that praça, normalized by the praça's
own mean and std over the window. Diverging RdBu_r palette: blue = under
historical norm, red = over. Praças ordered by n_obs (densest first).
"""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go

from ..basis_config import BasisPairConfig
from .common import PAIR_DISPLAY
from .shaper import weekly_zscore

logger = logging.getLogger(__name__)


def build(df: pd.DataFrame, pair: BasisPairConfig, window_years: int = 5) -> go.Figure:
    """Build the z-score heatmap for one pair."""
    info = PAIR_DISPLAY[pair.label]
    fig = go.Figure()

    if df.empty:
        fig.update_layout(title=f"{info.title} — sem dados", template="plotly_white")
        return fig

    weekly = weekly_zscore(df, window_years=window_years)
    if weekly.empty:
        fig.update_layout(title=f"{info.title} — janela vazia", template="plotly_white")
        return fig

    # Order locations by observation count (densest at top)
    loc_order = (
        weekly.groupby("location")["value"]
        .count()
        .sort_values(ascending=True)
        .index.tolist()
    )

    pivot = weekly.pivot(index="location", columns="week", values="zscore")
    pivot = pivot.reindex(loc_order)

    if pivot.empty or pivot.shape[1] == 0:
        fig.update_layout(title=f"{info.title} — sem dados", template="plotly_white")
        return fig

    # Custom hover with raw value as well
    raw_pivot = weekly.pivot(index="location", columns="week", values="value")
    raw_pivot = raw_pivot.reindex(loc_order)
    raw_pivot = raw_pivot.reindex(columns=pivot.columns)

    fig.add_trace(go.Heatmap(
        x=[d.strftime("%Y-%m-%d") for d in pivot.columns],
        y=pivot.index.tolist(),
        z=pivot.values,
        customdata=raw_pivot.values,
        colorscale="RdBu_r",
        zmid=0,
        zmin=-3,
        zmax=3,
        colorbar=dict(title="z-score"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Semana: %{x}<br>"
            "z-score: %{z:.2f}<br>"
            f"Basis: %{{customdata:.2f}} {info.short_unit}<extra></extra>"
        ),
    ))

    fig.update_layout(
        title=f"{info.title} — heatmap z-score (mediana semanal, janela {window_years}y)",
        xaxis=dict(title="Semana"),
        yaxis=dict(title="Praça", autorange="reversed"),
        template="plotly_white",
        height=max(550, 22 * len(loc_order) + 150),
        margin=dict(l=10, r=10, t=60, b=10),
    )
    return fig
