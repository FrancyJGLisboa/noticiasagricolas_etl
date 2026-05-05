"""Tests for the basis visualization module (viz/).

Validates structure of returned figures and companion CSV — does not check
pixels. Synthetic fixture covers two pairs (soja-cbot, milho-b3) across 3
locations and 2 safras, enough to exercise all five viz.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pyarrow.parquet as pq
import pytest

from noticiasagricolas_etl.basis_builder import BASIS_SCHEMA
from noticiasagricolas_etl.basis_config import BASIS_PAIRS
from noticiasagricolas_etl.viz import (
    common,
    companion,
    deviation_map,
    heatmap,
    multi_location,
    seasonality,
)
from noticiasagricolas_etl.viz.companion import STATS_COLUMNS
import pyarrow as pa


SOJA_CBOT = next(p for p in BASIS_PAIRS if p.label == "soja-cbot")
MILHO_B3 = next(p for p in BASIS_PAIRS if p.label == "milho-b3")


def _synthetic_basis_rows(
    futures_indicator: str,
    locations: list[tuple[str, str]],
    start: date,
    days: int,
) -> list[dict]:
    """Generate synthetic basis rows. Values follow a sinusoid + per-location offset."""
    rows: list[dict] = []
    rng = np.random.default_rng(42)
    for loc, state in locations:
        offset = rng.uniform(-50, 50)
        for i in range(days):
            d = start + timedelta(days=i)
            seasonal = 30.0 * np.sin(2 * np.pi * i / 365.0)
            noise = rng.normal(0, 5)
            basis_brl = offset + seasonal + noise
            rows.append({
                "date": pd.to_datetime(d),
                "location": loc,
                "state": state,
                "physical_indicator": "test-physical",
                "physical_price_brl": 100.0 + basis_brl,
                "futures_indicator": futures_indicator,
                "futures_contract": f"{d.year}-07",
                "futures_price_raw": 10.0,
                "futures_price_brl": 100.0,
                "ptax": 5.0,
                "basis_brl": basis_brl,
                "basis_usd": basis_brl / 5.0,
                "basis_pct": basis_brl,
                "basis_centavos_sc": basis_brl * 100.0,
                # cents/bu only for soja-cbot
                "basis_cents_bu": basis_brl / 5.0 / 2.2046 * 100.0
                    if futures_indicator == SOJA_CBOT.futures_indicator else np.nan,
            })
    return rows


def _write_basis_parquet(basis_dir, commodity: str, rows: list[dict]) -> None:
    path = basis_dir / f"commodity={commodity}"
    path.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    for field in BASIS_SCHEMA:
        if field.name not in df.columns:
            df[field.name] = np.nan
    df = df[[f.name for f in BASIS_SCHEMA]]
    table = pa.Table.from_pandas(df, schema=BASIS_SCHEMA, preserve_index=False)
    pq.write_table(table, path / "data.parquet")


@pytest.fixture
def synthetic_basis(tmp_path, monkeypatch):
    """Materialize synthetic basis Parquet at tmp PARQUET_BASIS_DIR / CSV_DIR / CHARTS_DIR."""
    basis_dir = tmp_path / "parquet_basis"
    csv_dir = tmp_path / "csv"
    charts_dir = tmp_path / "charts"
    basis_dir.mkdir()
    csv_dir.mkdir()
    charts_dir.mkdir()

    monkeypatch.setattr("noticiasagricolas_etl.config.PARQUET_BASIS_DIR", basis_dir)
    monkeypatch.setattr("noticiasagricolas_etl.config.CSV_DIR", csv_dir)
    monkeypatch.setattr("noticiasagricolas_etl.config.CHARTS_DIR", charts_dir)
    monkeypatch.setattr("noticiasagricolas_etl.viz.common.PARQUET_BASIS_DIR", basis_dir)
    monkeypatch.setattr("noticiasagricolas_etl.viz.common.CHARTS_DIR", charts_dir)
    monkeypatch.setattr("noticiasagricolas_etl.viz.companion.CSV_DIR", csv_dir)

    soja_locs = [("Sorriso/MT", "MT"), ("Rio Verde/GO", "GO"), ("Paranaguá/PR", "PR")]
    milho_locs = [("Sorriso/MT", "MT"), ("Não-Me-Toque/RS", "RS")]

    soja_rows = _synthetic_basis_rows(
        SOJA_CBOT.futures_indicator, soja_locs, date(2022, 1, 1), days=900,
    )
    milho_rows = _synthetic_basis_rows(
        MILHO_B3.futures_indicator, milho_locs, date(2022, 1, 1), days=900,
    )
    _write_basis_parquet(basis_dir, "soja", soja_rows)
    _write_basis_parquet(basis_dir, "milho", milho_rows)

    return {
        "basis_dir": basis_dir,
        "csv_dir": csv_dir,
        "charts_dir": charts_dir,
    }


# ── common.py ────────────────────────────────────────────────────────────────

def test_pair_display_covers_all_pairs():
    for p in BASIS_PAIRS:
        assert p.label in common.PAIR_DISPLAY, f"missing PAIR_DISPLAY for {p.label}"


def test_safra_year_soja():
    # Soja safra starts Sep — Aug 2024 should still be 2023 safra
    assert common.safra_year(pd.Timestamp("2024-08-31"), "soja") == 2023
    assert common.safra_year(pd.Timestamp("2024-09-01"), "soja") == 2024
    assert common.safra_year(pd.Timestamp("2025-02-15"), "soja") == 2024


def test_safra_year_boi_is_calendar():
    assert common.safra_year(pd.Timestamp("2024-01-15"), "boi-gordo") == 2024
    assert common.safra_year(pd.Timestamp("2024-12-31"), "boi-gordo") == 2024


def test_pick_value_column_uses_cents_bu_for_cbot():
    assert common.pick_value_column(SOJA_CBOT) == "basis_cents_bu"


def test_pick_value_column_uses_brl_for_b3():
    assert common.pick_value_column(MILHO_B3) == "basis_brl"


def test_load_pair_data_returns_value_column(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    assert not df.empty
    assert "value" in df.columns
    assert df["value"].notna().all()


# ── companion.py ─────────────────────────────────────────────────────────────

def test_compute_stats_columns(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    stats = companion.compute_stats(df, window_years=5)
    assert list(stats.columns) == STATS_COLUMNS
    assert len(stats) == 3  # 3 locations
    assert stats["n_obs_5y"].min() > 0


def test_compute_stats_percentile_in_range(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    stats = companion.compute_stats(df)
    pct = stats["pctile_today"].dropna()
    assert ((pct >= 0) & (pct <= 100)).all()


def test_write_stats_csv(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    stats = companion.compute_stats(df)
    path = companion.write_stats_csv(stats, SOJA_CBOT)
    assert path.exists()
    reread = pd.read_csv(path)
    assert list(reread.columns) == STATS_COLUMNS


# ── seasonality.py ───────────────────────────────────────────────────────────

def test_seasonality_returns_figure(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    fig = seasonality.build(df, SOJA_CBOT)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0
    # Should have a dropdown
    assert fig.layout.updatemenus
    # X-axis should have month labels (12 ticks)
    assert len(fig.layout.xaxis.tickvals) == 12


def test_seasonality_empty_df():
    fig = seasonality.build(pd.DataFrame(columns=["date", "location", "state", "value"]), SOJA_CBOT)
    assert isinstance(fig, go.Figure)


def test_seasonality_build_combined(synthetic_basis):
    df_soja = common.load_pair_data(SOJA_CBOT)
    df_milho = common.load_pair_data(MILHO_B3)
    fig = seasonality.build_combined([(SOJA_CBOT, df_soja), (MILHO_B3, df_milho)])
    assert isinstance(fig, go.Figure)
    # Three cascading updatemenus: commodity, vs, praça
    assert len(fig.layout.updatemenus) == 3
    commodity_btns = fig.layout.updatemenus[0].buttons
    vs_btns = fig.layout.updatemenus[1].buttons
    praca_btns = fig.layout.updatemenus[2].buttons
    # 2 commodities (soja, milho)
    assert len(commodity_btns) == 2
    assert {b.label for b in commodity_btns} == {"Soja", "Milho"}
    # vs dropdown shows initial commodity's futures (CBOT for soja)
    assert {b.label for b in vs_btns} == {"CBOT"}
    # Initial praça dropdown for soja-cbot has 3 entries
    assert len(praca_btns) == 3
    # Commodity button must relayout both vs and praça dropdowns
    sample = commodity_btns[0]
    relayout = sample.args[1]
    assert "updatemenus[1].buttons" in relayout
    assert "updatemenus[2].buttons" in relayout


# ── multi_location.py ────────────────────────────────────────────────────────

def test_multi_location_returns_figure(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    fig = multi_location.build(df, SOJA_CBOT, window_years=5)
    assert isinstance(fig, go.Figure)
    # Has scatter traces for praças and one Table trace
    types = [type(t).__name__ for t in fig.data]
    assert "Scatter" in types
    assert "Table" in types


# ── deviation_map.py ─────────────────────────────────────────────────────────

def test_deviation_map_returns_figure(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    fig = deviation_map.build(df, SOJA_CBOT, window_years=5)
    assert isinstance(fig, go.Figure)
    # Scattergeo trace expected
    types = [type(t).__name__ for t in fig.data]
    assert "Scattergeo" in types
    # All synthetic praças have coords in PRACA_COORDS
    geo_trace = next(t for t in fig.data if type(t).__name__ == "Scattergeo")
    assert len(geo_trace.lat) == 3


def test_deviation_map_handles_unknown_locations(synthetic_basis, caplog):
    df = common.load_pair_data(SOJA_CBOT).copy()
    # Replace one location with an unknown name
    df.loc[df["location"] == "Sorriso/MT", "location"] = "PracaInexistente/XX"
    with caplog.at_level("WARNING"):
        fig = deviation_map.build(df, SOJA_CBOT)
    assert isinstance(fig, go.Figure)
    assert any("sem coords" in m for m in caplog.messages)


# ── heatmap.py ───────────────────────────────────────────────────────────────

def test_heatmap_returns_figure(synthetic_basis):
    df = common.load_pair_data(SOJA_CBOT)
    fig = heatmap.build(df, SOJA_CBOT, window_years=5)
    assert isinstance(fig, go.Figure)
    types = [type(t).__name__ for t in fig.data]
    assert "Heatmap" in types
    hm = fig.data[0]
    # 3 locations × N weeks
    assert len(hm.y) == 3


# ── orchestrator.py ──────────────────────────────────────────────────────────

def test_orchestrator_combined_writes_files(synthetic_basis):
    from noticiasagricolas_etl.viz import orchestrator

    summary = orchestrator.generate(
        commodities=["soja"], viz="all", window_years=5, mode="combined",
    )
    # Combined: keys are viz names, values are paths or None
    assert set(summary.keys()) == set(orchestrator.VIZ_NAMES)
    # seasonality is a single combined HTML
    assert summary["seasonality"] is not None
    assert summary["seasonality"].exists()
    assert summary["seasonality"].name == "seasonality.html"
    # companion is a single combined CSV
    assert summary["companion"].name == "basis-stats.csv"


def test_orchestrator_per_pair_writes_files(synthetic_basis):
    from noticiasagricolas_etl.viz import orchestrator

    summary = orchestrator.generate(
        commodities=["soja"], viz="all", window_years=5, mode="per-pair",
    )
    assert "soja-cbot" in summary
    paths = summary["soja-cbot"]
    assert set(paths.keys()) == set(orchestrator.VIZ_NAMES)
    for name, path in paths.items():
        assert path is not None, f"viz {name} produced no path"
        assert path.exists(), f"viz {name} file missing: {path}"


def test_orchestrator_invalid_viz_raises():
    from noticiasagricolas_etl.viz import orchestrator

    with pytest.raises(ValueError):
        orchestrator.generate(viz="bogus")
