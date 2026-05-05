"""Shared utilities for basis visualizations.

- PAIR_DISPLAY: per-pair display config (column to plot, axis label)
- SAFRA_START_MONTH: start month of the agricultural year per commodity
- PRACA_COORDS: lat/lon for known praças (used by deviation map)
- Helpers: load_pair_data, pick_value_column, safra_year, write_chart
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from ..basis_config import BasisPairConfig
from ..config import CHARTS_DIR, PARQUET_BASIS_DIR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PairDisplay:
    """Display config for a basis pair: which column to plot and how to label it."""

    column: str
    title: str
    yaxis: str
    short_unit: str  # e.g. "¢/bu", "R$/sc", "R$/@"


PAIR_DISPLAY: dict[str, PairDisplay] = {
    "soja-b3": PairDisplay(
        column="basis_brl",
        title="Soja — Basis vs B3",
        yaxis="Basis (R$/sc60kg)",
        short_unit="R$/sc",
    ),
    "soja-cbot": PairDisplay(
        column="basis_cents_bu",
        title="Soja — Basis vs CBOT",
        yaxis="Basis (¢/bu)",
        short_unit="¢/bu",
    ),
    "milho-b3": PairDisplay(
        column="basis_brl",
        title="Milho — Basis vs B3",
        yaxis="Basis (R$/sc60kg)",
        short_unit="R$/sc",
    ),
    "milho-cbot": PairDisplay(
        column="basis_cents_bu",
        title="Milho — Basis vs CBOT",
        yaxis="Basis (¢/bu)",
        short_unit="¢/bu",
    ),
    "trigo-cbot": PairDisplay(
        column="basis_cents_bu",
        title="Trigo — Basis vs CBOT",
        yaxis="Basis (¢/bu)",
        short_unit="¢/bu",
    ),
    "algodao-nybot": PairDisplay(
        column="basis_brl",
        title="Algodão — Basis vs NYBOT",
        yaxis="Basis (R$/@)",
        short_unit="R$/@",
    ),
    "cafe-b3": PairDisplay(
        column="basis_brl",
        title="Café — Basis vs B3",
        yaxis="Basis (R$/sc60kg)",
        short_unit="R$/sc",
    ),
    "cafe-nybot": PairDisplay(
        column="basis_brl",
        title="Café — Basis vs NYBOT",
        yaxis="Basis (R$/sc60kg)",
        short_unit="R$/sc",
    ),
    "boi-gordo-b3": PairDisplay(
        column="basis_brl",
        title="Boi Gordo — Basis vs B3",
        yaxis="Basis (R$/@)",
        short_unit="R$/@",
    ),
}


SAFRA_START_MONTH: dict[str, int] = {
    "soja": 9,        # set→ago (CONAB/ABIOVE)
    "milho": 2,       # fev→jan (cobre verão + safrinha)
    "trigo": 7,       # jul→jun (plantio jun-jul Sul)
    "algodao": 7,     # jul→jun (CONAB)
    "cafe": 7,        # jul→jun (safra brasileira)
    "boi-gordo": 1,   # ano calendário (sem safra)
}


PRACA_COORDS: dict[str, tuple[float, float]] = {
    "Alto Garças/MT": (-16.9408, -53.5269),
    "Amambai/MS": (-23.1031, -55.2253),
    "Assis/SP": (-22.6614, -50.4119),
    "Brasília/DF": (-15.7942, -47.8822),
    "Caarapó/MS": (-22.6347, -54.8217),
    "Cafelândia/PR": (-24.6175, -53.5644),
    "Campinas/SP": (-22.9099, -47.0626),
    "Campo Grande/MS": (-20.4486, -54.6295),
    "Campo Novo do Parecis/MT": (-13.6750, -57.8919),
    "Campos Gerais/MG": (-21.2336, -45.7589),
    "Cascavel/PR": (-24.9558, -53.4553),
    "Castro/PR": (-24.7903, -50.0119),
    "Chapadão do Sul/MS": (-18.7864, -52.6261),
    "Cândido Mota/SP": (-22.7475, -50.3878),
    "Dourados/MS": (-22.2231, -54.8056),
    "Eldorado/MS": (-23.7889, -54.2839),
    "Esp. Sto. do Pinhal/SP": (-22.1908, -46.7464),
    "Franca/SP": (-20.5386, -47.4006),
    "Guaxupé/MG": (-21.3056, -46.7097),
    "Indicador ESALQ/SP": (-22.7053, -47.6328),  # Piracicaba (USP/ESALQ)
    "Itapetininga/SP": (-23.5919, -48.0531),
    "Itiquira/MT": (-17.2061, -54.1456),
    "Jataí/GO": (-17.8814, -51.7256),
    "Londrina/PR": (-23.3045, -51.1696),
    "Luís Eduardo Magalhães/BA": (-12.0908, -45.8022),
    "Machado/MG": (-21.6736, -45.9229),
    "Maracaju/MS": (-21.6139, -55.1683),
    "Marechal Cândido Rondon/PR": (-24.5563, -54.0532),
    "Maringá/PR": (-23.4242, -51.9386),
    "Nonoai/RS": (-27.3611, -52.7800),
    "Não-Me-Toque/RS": (-28.4583, -52.8197),
    "Oeste da Bahia/BA": (-12.0908, -45.8022),  # LEM (centroide oeste BA)
    "Palma Sola/SC": (-26.3375, -53.2789),
    "Panambi/RS": (-28.2917, -53.5025),
    "Paranaguá/PR": (-25.5163, -48.5095),
    "Pato Branco/PR": (-26.2294, -52.6708),
    "Patrocínio/MG": (-18.9442, -46.9939),
    "Ponta Grossa/PR": (-25.0950, -50.1619),
    "Ponta Porã/MS": (-22.5364, -55.7256),
    "Porto Imbituba/SC": (-28.2378, -48.6647),
    "Porto Paranaguá/PR": (-25.5163, -48.5095),
    "Porto Rio Grande/RS": (-32.0349, -52.0986),
    "Porto Santos/SP": (-23.9619, -46.3322),
    "Porto São Francisco do Sul/SC": (-26.2436, -48.6356),
    "Poços de Caldas/MG": (-21.7878, -46.5614),
    "Primavera do Leste/MT": (-15.5586, -54.2961),
    "Rio Verde/GO": (-17.7969, -50.9264),
    "Rio do Sul/SC": (-27.2150, -49.6428),
    "Rondonópolis/MT": (-16.4706, -54.6358),
    "Sidrolândia/MS": (-20.9322, -54.9608),
    "Sonora/MS": (-17.5778, -54.7569),
    "Sorriso/MT": (-12.5447, -55.7211),
    "São Gabriel do Oeste/MS": (-19.3925, -54.5617),
    "Tangará da Serra/MT": (-14.6225, -57.4928),
    "Ubiratã/PR": (-24.5419, -52.9889),
    "Varginha/MG": (-21.5503, -45.4297),
}


def pick_value_column(pair: BasisPairConfig) -> str:
    """Return the basis column to plot for this pair."""
    info = PAIR_DISPLAY.get(pair.label)
    if info is None:
        logger.warning("No PAIR_DISPLAY entry for %s — defaulting to basis_brl", pair.label)
        return "basis_brl"
    return info.column


def load_pair_data(pair: BasisPairConfig) -> pd.DataFrame:
    """Load materialized basis Parquet filtered to this pair's futures indicator.

    Returns DataFrame with the chosen value column renamed to 'value' for uniform
    downstream handling. Empty DataFrame if no data exists.
    """
    parquet_path = PARQUET_BASIS_DIR / f"commodity={pair.commodity}" / "data.parquet"
    if not parquet_path.exists():
        return pd.DataFrame()

    df = pd.read_parquet(parquet_path)
    df = df[df["futures_indicator"] == pair.futures_indicator].copy()
    if df.empty:
        return df

    col = pick_value_column(pair)
    if col not in df.columns:
        logger.warning("Column %s missing for %s — skipping", col, pair.label)
        return pd.DataFrame()

    df["value"] = df[col]
    df = df[df["value"].notna()]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["location", "date"]).reset_index(drop=True)
    return df


def safra_year(date: pd.Timestamp, commodity: str) -> int:
    """Return the safra-year integer for a given date.

    The safra year is labelled by its starting calendar year. For soja
    (start=Sep), 2024-09-15 → 2024 and 2025-02-10 → 2024 (still in 2024/25
    safra). For boi (start=Jan), it equals the calendar year.
    """
    start_month = SAFRA_START_MONTH.get(commodity, 1)
    if date.month >= start_month:
        return date.year
    return date.year - 1


def write_chart(fig: go.Figure, output_path: Path, *, include_plotlyjs: bool = True) -> None:
    """Write a Plotly figure as self-contained HTML."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path), include_plotlyjs=include_plotlyjs)


def chart_path(prefix: str, label: str) -> Path:
    """Standardized chart output path: data/charts/{prefix}-{label}.html."""
    return CHARTS_DIR / f"{prefix}-{label}.html"
