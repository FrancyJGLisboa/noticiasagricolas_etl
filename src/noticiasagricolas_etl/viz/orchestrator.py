"""Orchestrate generation of the 5 basis visualizations.

Iterates over BASIS_PAIRS (optionally filtered by commodity/viz), loads each
pair's materialized data once, and writes outputs to data/charts/ and
data/csv/.

Two output modes:
- "combined" (default): one HTML per viz type with cascading pair → praça dropdowns
- "per-pair": one HTML per (pair, viz) combination — backward-compat
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..basis_config import BASIS_PAIRS, BasisPairConfig
from ..config import CHARTS_DIR
from . import deviation_map, heatmap, multi_location, seasonality
from .common import chart_path, load_pair_data, write_chart
from .companion import compute_stats, write_stats_csv

logger = logging.getLogger(__name__)


VIZ_NAMES: tuple[str, ...] = ("seasonality", "multi", "companion", "map", "heatmap")


def _generate_for_pair(
    pair: BasisPairConfig,
    selected: set[str],
    window_years: int,
) -> dict[str, Path | None]:
    """Generate all selected viz for one pair. Returns paths produced (None if skipped)."""
    df = load_pair_data(pair)
    out: dict[str, Path | None] = {}

    if df.empty:
        logger.info("Skipping %s — no materialized basis data", pair.label)
        return {v: None for v in selected}

    if "seasonality" in selected:
        fig = seasonality.build(df, pair)
        path = chart_path("seasonality", pair.label)
        write_chart(fig, path)
        out["seasonality"] = path
        logger.info("Wrote %s", path.name)

    if "multi" in selected:
        fig = multi_location.build(df, pair, window_years=window_years)
        path = chart_path("multi-location", pair.label)
        write_chart(fig, path)
        out["multi"] = path
        logger.info("Wrote %s", path.name)

    if "companion" in selected:
        stats = compute_stats(df, window_years=window_years)
        path = write_stats_csv(stats, pair)
        out["companion"] = path

    if "map" in selected:
        fig = deviation_map.build(df, pair, window_years=window_years)
        path = chart_path("deviation-map", pair.label)
        write_chart(fig, path)
        out["map"] = path
        logger.info("Wrote %s", path.name)

    if "heatmap" in selected:
        fig = heatmap.build(df, pair, window_years=window_years)
        path = chart_path("heatmap", pair.label)
        write_chart(fig, path)
        out["heatmap"] = path
        logger.info("Wrote %s", path.name)

    return out


def generate(
    commodities: list[str] | None = None,
    viz: str | None = None,
    window_years: int = 5,
    mode: str = "combined",
) -> dict:
    """Generate the requested visualizations across all (or filtered) pairs.

    Args:
        commodities: filter (e.g. ["soja", "milho"]); None = all.
        viz: one of VIZ_NAMES or "all" (default: all).
        window_years: window for multi/companion/map/heatmap (default 5).
        mode: "combined" (one HTML per viz with cascading dropdowns; default)
              or "per-pair" (legacy: one HTML per pair × viz).

    Returns:
        For mode="combined": {viz_name: output_path | None}
        For mode="per-pair":  {pair_label: {viz_name: output_path | None}}
    """
    if viz is None or viz == "all":
        selected: set[str] = set(VIZ_NAMES)
    elif viz in VIZ_NAMES:
        selected = {viz}
    else:
        raise ValueError(f"Unknown viz {viz!r}; expected one of {VIZ_NAMES + ('all',)}")

    pairs = BASIS_PAIRS
    if commodities:
        pairs = [p for p in pairs if p.commodity in commodities]

    if not pairs:
        logger.warning("No basis pairs match filter %s", commodities)
        return {}

    if mode == "per-pair":
        return {p.label: _generate_for_pair(p, selected, window_years) for p in pairs}

    if mode != "combined":
        raise ValueError(f"Unknown mode {mode!r}; expected 'combined' or 'per-pair'")

    return _generate_combined(pairs, selected, window_years)


def _generate_combined(
    pairs: list[BasisPairConfig],
    selected: set[str],
    window_years: int,
) -> dict[str, Path | None]:
    """Generate ONE HTML per viz type spanning all pairs (cascading dropdowns)."""
    # Pre-load all pair data once
    pair_data: list[tuple[BasisPairConfig, pd.DataFrame]] = []
    for pair in pairs:
        df = load_pair_data(pair)
        if df.empty:
            logger.info("Skipping %s — no materialized basis data", pair.label)
            continue
        pair_data.append((pair, df))

    out: dict[str, Path | None] = {v: None for v in selected}
    if not pair_data:
        return out

    if "seasonality" in selected:
        fig = seasonality.build_combined(pair_data)
        path = CHARTS_DIR / "seasonality.html"
        write_chart(fig, path)
        out["seasonality"] = path
        logger.info("Wrote %s (%d pairs)", path.name, len(pair_data))

    if "companion" in selected:
        # Combined CSV with extra "pair" column
        from ..config import CSV_DIR
        frames = []
        for pair, df in pair_data:
            stats = compute_stats(df, window_years=window_years)
            if not stats.empty:
                stats = stats.copy()
                stats.insert(0, "pair", pair.label)
                frames.append(stats)
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            CSV_DIR.mkdir(parents=True, exist_ok=True)
            path = CSV_DIR / "basis-stats.csv"
            combined.to_csv(path, index=False, float_format="%.2f")
            out["companion"] = path
            logger.info("Wrote %s (%d rows across %d pairs)", path.name, len(combined), len(frames))

    # Other viz still per-pair until refactored to combined dropdowns
    for viz_name in ("multi", "map", "heatmap"):
        if viz_name not in selected:
            continue
        for pair, df in pair_data:
            if viz_name == "multi":
                fig = multi_location.build(df, pair, window_years=window_years)
                path = chart_path("multi-location", pair.label)
            elif viz_name == "map":
                fig = deviation_map.build(df, pair, window_years=window_years)
                path = chart_path("deviation-map", pair.label)
            else:
                fig = heatmap.build(df, pair, window_years=window_years)
                path = chart_path("heatmap", pair.label)
            write_chart(fig, path)
            logger.info("Wrote %s", path.name)
        # Mark produced (any pair counts)
        out[viz_name] = CHARTS_DIR

    return out
