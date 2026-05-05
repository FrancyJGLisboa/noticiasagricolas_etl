"""Build materialized daily basis (physical - futures) time series.

Thin orchestrator: pulls source rows via `basis.sources`, runs the math via
`basis.calculator`, persists via `basis.output`. The split exists so the
basis math is testable without DuckDB and the I/O paths are isolated.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

from .basis import (
    BASIS_SCHEMA,
    compute_basis_columns,
    export_basis_csv,
    load_futures_prices,
    load_physical_prices,
    load_ptax,
    select_front_month,
    write_basis_parquet,
)
from .basis.sources import parquet_exists
from .basis_config import BasisPairConfig, get_pairs

logger = logging.getLogger(__name__)


def build_pair(
    conn: duckdb.DuckDBPyConnection,
    config: BasisPairConfig,
    ptax_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute basis for one commodity-futures pair.

    Loads physical prices for all locations + indicators of this pair, picks
    the front-month futures contract per date, then runs the basis math
    against the joined frame. Returns the wide BASIS_SCHEMA DataFrame; empty
    if any source slice is empty.
    """
    physical = load_physical_prices(conn, config.physical_indicators, config.commodity)
    futures_raw = load_futures_prices(conn, config.futures_indicator, config.commodity)
    front_month = select_front_month(futures_raw)
    return compute_basis_columns(physical, front_month, ptax_df, config)


def build_all(
    commodities: list[str] | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Build basis panels for all configured pairs (optionally filtered).

    Skips pairs whose source parquet doesn't exist. Writes one combined
    parquet + CSV per commodity (multiple pairs per commodity merge into one
    file). Returns `{pair_label: row_count}`.
    """
    conn = duckdb.connect(":memory:")
    pairs = get_pairs(commodities)
    summary: dict[str, int] = {}

    for commodity in {p.commodity for p in pairs}:
        if not parquet_exists(commodity):
            logger.info("Skipping %s — no source Parquet data", commodity)

    any_needs_ptax = any(p.needs_ptax for p in pairs if parquet_exists(p.commodity))
    ptax_df = load_ptax(conn) if any_needs_ptax else pd.DataFrame(columns=["date", "ptax"])

    commodity_dfs: dict[str, list[pd.DataFrame]] = {}
    for pair in pairs:
        if not parquet_exists(pair.commodity):
            logger.info("Skipping pair %s — no Parquet for %s", pair.label, pair.commodity)
            summary[pair.label] = 0
            continue

        logger.info("Building basis pair: %s", pair.label)
        df = build_pair(conn, pair, ptax_df)
        summary[pair.label] = len(df)
        if not df.empty:
            commodity_dfs.setdefault(pair.commodity, []).append(df)

    for commodity, dfs in commodity_dfs.items():
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values(
            ["date", "futures_indicator", "location"]
        ).reset_index(drop=True)
        write_basis_parquet(commodity, combined)
        export_basis_csv(commodity, combined)

    conn.close()
    return summary


# Re-exports for backward compatibility with callers that imported from this module.
__all__ = ["BASIS_SCHEMA", "build_all", "build_pair"]
