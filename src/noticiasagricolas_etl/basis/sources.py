"""DuckDB-backed loaders for the source data that feeds basis computation.

Each loader pulls one slice from `data/parquet/commodity={name}/data.parquet`
and returns a tidy DataFrame ready for the calculator.

PTAX (BRL/USD reference) lives in the `mercado-financeiro` parquet, gets
forward-filled across weekends/holidays so basis joins don't drop rows.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

from ..config import PARQUET_DIR
from .locations import indicator_location, normalize_and_aggregate

logger = logging.getLogger(__name__)


def parquet_exists(commodity: str) -> bool:
    """Check whether the source parquet exists for `commodity`."""
    return (PARQUET_DIR / f"commodity={commodity}" / "data.parquet").exists()


def load_ptax(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load the PTAX BRL/USD reference, forward-filled across weekends/holidays.

    Returns DataFrame(date, ptax). Empty if the financial parquet is missing.
    """
    fin_path = PARQUET_DIR / "commodity=mercado-financeiro" / "data.parquet"
    if not fin_path.exists():
        logger.warning("No mercado-financeiro Parquet found at %s", fin_path)
        return pd.DataFrame(columns=["date", "ptax"])

    df = conn.execute("""
        SELECT date, value AS ptax
        FROM read_parquet(?)
        WHERE indicator = 'cambio-ptax'
          AND location = 'Dólar'
          AND measure = 'price'
          AND value IS NOT NULL
        ORDER BY date
    """, [str(fin_path)]).fetchdf()

    if df.empty:
        return pd.DataFrame(columns=["date", "ptax"])

    df["date"] = pd.to_datetime(df["date"]).dt.date
    min_date, max_date = df["date"].min(), df["date"].max()
    all_dates = pd.date_range(min_date, max_date, freq="D")
    full = pd.DataFrame({"date": all_dates.date}).merge(df, on="date", how="left")
    full["ptax"] = full["ptax"].ffill()
    return full


def load_physical_prices(
    conn: duckdb.DuckDBPyConnection,
    indicators: tuple[str, ...],
    commodity: str,
) -> pd.DataFrame:
    """Load physical (mercado-físico / indicator) prices for one commodity-pair's source slugs.

    Returns DataFrame(date, location, state, physical_indicator,
    physical_price_brl) with location names already normalized and same-day
    duplicates averaged.
    """
    parquet_path = PARQUET_DIR / f"commodity={commodity}" / "data.parquet"
    empty_cols = ["date", "location", "state", "physical_indicator", "physical_price_brl"]
    if not parquet_path.exists():
        return pd.DataFrame(columns=empty_cols)

    frames: list[pd.DataFrame] = []
    for indicator in indicators:
        df = conn.execute("""
            SELECT date, indicator AS physical_indicator, location, state,
                   value AS physical_price_brl
            FROM read_parquet(?)
            WHERE indicator = ?
              AND measure = 'price'
              AND value IS NOT NULL
              AND location IS NOT NULL
              AND market_type IN ('physical', 'indicator')
            ORDER BY date, location
        """, [str(parquet_path), indicator]).fetchdf()
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            frames.append(df)

        # Indicator-only rows (no location) — assign a synthetic location so
        # the basis join pattern still works.
        df_ind = conn.execute("""
            SELECT date, indicator AS physical_indicator,
                   value AS physical_price_brl
            FROM read_parquet(?)
            WHERE indicator = ?
              AND measure = 'price'
              AND value IS NOT NULL
              AND location IS NULL
              AND market_type = 'indicator'
            ORDER BY date
        """, [str(parquet_path), indicator]).fetchdf()
        if not df_ind.empty:
            df_ind["date"] = pd.to_datetime(df_ind["date"]).dt.date
            df_ind["location"] = indicator_location(indicator)
            df_ind["state"] = None
            frames.append(df_ind)

    if not frames:
        return pd.DataFrame(columns=empty_cols)

    combined = pd.concat(frames, ignore_index=True)
    return normalize_and_aggregate(combined)


def load_futures_prices(
    conn: duckdb.DuckDBPyConnection,
    indicator: str,
    commodity: str,
) -> pd.DataFrame:
    """Load futures (per-contract) price rows for one indicator.

    Returns DataFrame(date, contract, futures_price_raw). Empty if the
    commodity's parquet doesn't exist.
    """
    parquet_path = PARQUET_DIR / f"commodity={commodity}" / "data.parquet"
    if not parquet_path.exists():
        return pd.DataFrame(columns=["date", "contract", "futures_price_raw"])

    df = conn.execute("""
        SELECT date, contract, value AS futures_price_raw
        FROM read_parquet(?)
        WHERE indicator = ?
          AND measure = 'price'
          AND value IS NOT NULL
          AND contract IS NOT NULL
          AND price_basis = 'futures'
        ORDER BY date, contract
    """, [str(parquet_path), indicator]).fetchdf()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df
