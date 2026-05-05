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
) -> dict[str, dict[str, Path | None]]:
    """Generate the requested visualizations across all (or filtered) pairs.

    Args:
        commodities: filter (e.g. ["soja", "milho"]); None = all.
        viz: one of VIZ_NAMES or "all" (default: all).
        window_years: window for multi/companion/map/heatmap (default 5).
        mode: "combined" (cascading dropdown HTMLs spanning all pairs; default)
              or "per-pair" (one HTML per pair × viz).

    Returns:
        Always `{pair_label: {viz_name: output_path | None}}`. In "combined"
        mode, the chart for cascading-dropdown viz (seasonality, companion)
        is shared — every pair_label entry points to the same Path. The
        per-pair viz (multi, map, heatmap) point to per-pair files. Single
        consistent shape lets callers avoid hasattr/isinstance branching.
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
) -> dict[str, dict[str, Path | None]]:
    """Generate cascading-dropdown HTMLs spanning all pairs.

    Returns the same `{pair_label: {viz: Path|None}}` shape as per-pair mode.
    For viz that produce ONE shared HTML (seasonality, companion), every
    pair_label entry points to the same Path; for viz that stay per-pair
    (multi, map, heatmap), each pair_label points to its own file.
    """
    pair_data: list[tuple[BasisPairConfig, pd.DataFrame]] = []
    for pair in pairs:
        df = load_pair_data(pair)
        if df.empty:
            logger.info("Skipping %s — no materialized basis data", pair.label)
            continue
        pair_data.append((pair, df))

    # Initialize output with one entry per pair (whether or not it produced data),
    # so callers can iterate uniformly.
    out: dict[str, dict[str, Path | None]] = {
        p.label: {v: None for v in selected} for p in pairs
    }
    if not pair_data:
        return out

    # Shared chart 1 — seasonality (one HTML with cascading commodity/pair/praça dropdowns)
    seasonality_path: Path | None = None
    if "seasonality" in selected:
        fig = seasonality.build_combined(pair_data)
        seasonality_path = CHARTS_DIR / "seasonality.html"
        write_chart(fig, seasonality_path)
        logger.info("Wrote %s (%d pairs)", seasonality_path.name, len(pair_data))

    # Shared chart 2 — companion stats CSV
    companion_path: Path | None = None
    if "companion" in selected:
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
            companion_path = CSV_DIR / "basis-stats.csv"
            combined.to_csv(companion_path, index=False, float_format="%.2f")
            logger.info(
                "Wrote %s (%d rows across %d pairs)",
                companion_path.name, len(combined), len(frames),
            )

    # Per-pair charts
    pair_labels_with_data = {p.label for p, _ in pair_data}
    for pair, df in pair_data:
        slot = out[pair.label]
        if "seasonality" in selected and seasonality_path is not None:
            slot["seasonality"] = seasonality_path
        if "companion" in selected and companion_path is not None:
            slot["companion"] = companion_path

        if "multi" in selected:
            fig = multi_location.build(df, pair, window_years=window_years)
            path = chart_path("multi-location", pair.label)
            write_chart(fig, path)
            slot["multi"] = path
            logger.info("Wrote %s", path.name)
        if "map" in selected:
            fig = deviation_map.build(df, pair, window_years=window_years)
            path = chart_path("deviation-map", pair.label)
            write_chart(fig, path)
            slot["map"] = path
            logger.info("Wrote %s", path.name)
        if "heatmap" in selected:
            fig = heatmap.build(df, pair, window_years=window_years)
            path = chart_path("heatmap", pair.label)
            write_chart(fig, path)
            slot["heatmap"] = path
            logger.info("Wrote %s", path.name)

    # Pairs without data already have all-None slots from the initialization above
    _ = pair_labels_with_data
    return out
