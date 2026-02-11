#!/usr/bin/env python3
"""Generate interactive Plotly basis charts from materialized Parquet data."""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from noticiasagricolas_etl.basis_config import BASIS_PAIRS
from noticiasagricolas_etl.config import PARQUET_BASIS_DIR

CHARTS_DIR = PROJECT_ROOT / "data" / "charts"

# Label formatting per pair
PAIR_INFO = {
    "soja-b3": {"title": "Soja — Base vs B3 (R$/sc)", "yaxis": "Base (R$/sc)"},
    "soja-cbot": {"title": "Soja — Base vs CBOT (R$/sc)", "yaxis": "Base (R$/sc)"},
    "milho-b3": {"title": "Milho — Base vs B3 (R$/sc)", "yaxis": "Base (R$/sc)"},
    "milho-cbot": {"title": "Milho — Base vs CBOT (R$/sc)", "yaxis": "Base (R$/sc)"},
    "trigo-cbot": {"title": "Trigo — Base vs CBOT (R$/sc)", "yaxis": "Base (R$/sc)"},
    "algodao-nybot": {"title": "Algodão — Base vs NYBOT (R$/@)", "yaxis": "Base (R$/@)"},
    "cafe-b3": {"title": "Café — Base vs B3 (R$/sc)", "yaxis": "Base (R$/sc)"},
    "cafe-nybot": {"title": "Café — Base vs NYBOT (R$/sc)", "yaxis": "Base (R$/sc)"},
    "boi-gordo-b3": {"title": "Boi Gordo — Base vs B3 (R$/@)", "yaxis": "Base (R$/@)"},
}


def generate_chart(pair_config, df: pd.DataFrame, output_path: Path) -> None:
    """Generate an interactive Plotly chart for one basis pair."""
    label = pair_config.label
    info = PAIR_INFO.get(label, {"title": f"Base — {label}", "yaxis": "Base (R$)"})

    # Filter to this pair's futures indicator
    pair_df = df[df["futures_indicator"] == pair_config.futures_indicator].copy()
    if pair_df.empty:
        print(f"  {label}: no data, skipping chart")
        return

    pair_df["date"] = pd.to_datetime(pair_df["date"])
    pair_df = pair_df.sort_values(["location", "date"])

    # Get all states and locations
    states = sorted(pair_df["state"].dropna().unique())
    locations = sorted(pair_df["location"].unique())

    fig = go.Figure()

    # Add one trace per location
    for loc in locations:
        loc_df = pair_df[pair_df["location"] == loc]
        state = loc_df["state"].iloc[0] if not loc_df["state"].isna().all() else "??"

        fig.add_trace(go.Scatter(
            x=loc_df["date"],
            y=loc_df["basis_brl"],
            mode="lines",
            name=loc,
            visible=True,
            meta={"state": state},
            hovertemplate=(
                f"<b>{loc}</b><br>"
                "Data: %{x|%Y-%m-%d}<br>"
                "Base: R$ %{y:.2f}<br>"
                "<extra></extra>"
            ),
        ))

    # Build state filter dropdown buttons
    buttons = []

    # "All" button — show all traces
    buttons.append(dict(
        label="Todos",
        method="update",
        args=[{"visible": [True] * len(locations)}],
    ))

    # One button per state
    for state in states:
        state_locations = set(
            pair_df[pair_df["state"] == state]["location"].unique()
        )
        visibility = [loc in state_locations for loc in locations]
        buttons.append(dict(
            label=state,
            method="update",
            args=[{"visible": visibility}],
        ))

    fig.update_layout(
        title=dict(text=info["title"]),
        xaxis=dict(title="Data", rangeslider=dict(visible=True)),
        yaxis=dict(title=info["yaxis"]),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.4,
            xanchor="center",
            x=0.5,
        ),
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            x=0.0,
            xanchor="left",
            y=1.15,
            yanchor="top",
            buttons=buttons,
            showactive=True,
        )],
        template="plotly_white",
        height=700,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path), include_plotlyjs=True)
    n_locs = len(locations)
    n_rows = len(pair_df)
    print(f"  {label}: {n_rows:,} rows, {n_locs} locations -> {output_path.name}")


def main():
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    # Group pairs by commodity to load Parquet once per commodity
    commodity_pairs: dict[str, list] = {}
    for pair in BASIS_PAIRS:
        commodity_pairs.setdefault(pair.commodity, []).append(pair)

    for commodity, pairs in commodity_pairs.items():
        parquet_path = PARQUET_BASIS_DIR / f"commodity={commodity}" / "data.parquet"
        if not parquet_path.exists():
            print(f"Skipping {commodity} — no basis Parquet")
            continue

        df = pd.read_parquet(parquet_path)
        if df.empty:
            print(f"Skipping {commodity} — empty basis data")
            continue

        print(f"\n{commodity}: {len(df):,} basis rows")

        for pair in pairs:
            chart_path = CHARTS_DIR / f"basis-{pair.label}.html"
            generate_chart(pair, df, chart_path)


if __name__ == "__main__":
    main()
