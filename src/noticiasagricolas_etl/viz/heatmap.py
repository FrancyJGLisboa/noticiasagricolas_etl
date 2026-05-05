"""Viz #5 — z-score heatmap (praça × week).

Each cell is the weekly-median basis at that praça, normalized by the praça's
own mean and std over the window. Diverging RdBu_r palette: blue = under
historical norm, red = over. Praças ordered by n_obs (densest first).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..basis_config import BasisPairConfig
from .common import PAIR_DISPLAY

logger = logging.getLogger(__name__)


def _weekly_median(df: pd.DataFrame) -> pd.DataFrame:
    """Resample to weekly median per location. Returns long-format df."""
    df = df.copy()
    df["week"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    weekly = (
        df.groupby(["location", "week"], as_index=False)["value"]
        .median()
    )
    return weekly


def build(df: pd.DataFrame, pair: BasisPairConfig, window_years: int = 5) -> go.Figure:
    """Build the z-score heatmap for one pair."""
    info = PAIR_DISPLAY[pair.label]
    fig = go.Figure()

    if df.empty:
        fig.update_layout(title=f"{info.title} — sem dados", template="plotly_white")
        return fig

    today = df["date"].max()
    cutoff = today - pd.DateOffset(years=window_years)
    windowed = df[df["date"] >= cutoff].copy()
    if windowed.empty:
        fig.update_layout(title=f"{info.title} — janela vazia", template="plotly_white")
        return fig

    weekly = _weekly_median(windowed)

    # Compute per-location mean/std for z-score
    stats = weekly.groupby("location")["value"].agg(["mean", "std", "count"]).reset_index()
    weekly = weekly.merge(stats, on="location", how="left")
    weekly["zscore"] = np.where(
        (weekly["std"].notna()) & (weekly["std"] > 0),
        (weekly["value"] - weekly["mean"]) / weekly["std"],
        np.nan,
    )

    # Order locations by observation count (densest at top)
    loc_order = stats.sort_values("count", ascending=True)["location"].tolist()

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
