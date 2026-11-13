"""Basis (physical - futures) computation, split by concern.

  - locations: praça/port name normalization
  - sources:   DuckDB queries against the source parquet
  - calculator: front-month selection + basis math (BRL/USD/cents-bu)
  - output:    arrow schema + parquet/CSV writers

The top-level `basis_builder` module orchestrates these.
"""

from .calculator import compute_basis_columns, select_front_month
from .locations import normalize_location
from .output import BASIS_SCHEMA, export_basis_csv, write_basis_parquet
from .quote_quality import export_quote_quality_csv, summarize_quote_quality
from .roll_adjustment import add_roll_adjustments
from .sources import load_futures_prices, load_physical_prices, load_physical_quote_rows, load_ptax

__all__ = [
    "BASIS_SCHEMA",
    "add_roll_adjustments",
    "compute_basis_columns",
    "export_basis_csv",
    "export_quote_quality_csv",
    "load_futures_prices",
    "load_physical_prices",
    "load_physical_quote_rows",
    "load_ptax",
    "normalize_location",
    "select_front_month",
    "summarize_quote_quality",
    "write_basis_parquet",
]
