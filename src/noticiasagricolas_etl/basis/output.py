"""Write basis DataFrames to Hive-partitioned parquet + flat CSV mirror."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..config import CSV_DIR, PARQUET_BASIS_DIR

logger = logging.getLogger(__name__)


BASIS_SCHEMA = pa.schema([
    ("date", pa.date32()),
    ("location", pa.string()),
    ("state", pa.string()),
    ("physical_indicator", pa.string()),
    ("physical_price_brl", pa.float64()),
    ("futures_indicator", pa.string()),
    ("futures_contract", pa.string()),
    ("futures_price_raw", pa.float64()),
    ("futures_price_brl", pa.float64()),
    ("ptax", pa.float64()),
    ("basis_brl", pa.float64()),
    ("basis_usd", pa.float64()),
    ("basis_pct", pa.float64()),
    ("basis_centavos_sc", pa.float64()),
    ("basis_cents_bu", pa.float64()),
])


def write_basis_parquet(commodity: str, df: pd.DataFrame) -> Path:
    """Write basis DataFrame to data/parquet_basis/commodity={commodity}/data.parquet."""
    out_dir = PARQUET_BASIS_DIR / f"commodity={commodity}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "data.parquet"

    table = pa.Table.from_pandas(df, schema=BASIS_SCHEMA, preserve_index=False)
    pq.write_table(table, path)
    logger.info("Wrote %d basis rows to %s", len(df), path)
    return path


def export_basis_csv(commodity: str, df: pd.DataFrame) -> Path:
    """Write basis DataFrame to data/csv/basis-{commodity}.csv."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / f"basis-{commodity}.csv"
    df.to_csv(path, index=False)
    logger.info("Exported basis CSV: %s (%d rows)", path, len(df))
    return path
