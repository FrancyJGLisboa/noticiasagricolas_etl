"""DuckDB connection and Parquet view registration."""

import logging
from pathlib import Path

import duckdb

from ..config import PARQUET_BASIS_DIR, PARQUET_DIR

logger = logging.getLogger(__name__)

_conn: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get or create the DuckDB connection with Parquet views."""
    global _conn
    if _conn is None:
        _conn = _create_connection()
    return _conn


def _create_connection() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    _register_views(conn)
    _register_basis_view(conn)
    return conn


def _register_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Create a view over all Parquet files using Hive partitioning.

    If no Parquet files exist, creates an empty view with the expected schema.
    """
    parquet_files = list(PARQUET_DIR.glob("commodity=*/data.parquet")) if PARQUET_DIR.exists() else []

    if parquet_files:
        parquet_glob = str(PARQUET_DIR / "commodity=*" / "data.parquet")
        conn.execute(f"""
            CREATE OR REPLACE VIEW prices AS
            SELECT * FROM read_parquet(
                '{parquet_glob}',
                hive_partitioning = true
            )
        """)
        logger.info("Registered DuckDB view 'prices' over %d Parquet files", len(parquet_files))
    else:
        # Empty view with expected columns so queries don't crash
        conn.execute("""
            CREATE OR REPLACE VIEW prices AS
            SELECT
                NULL::DATE AS date, NULL::VARCHAR AS commodity,
                NULL::VARCHAR AS indicator, NULL::VARCHAR AS indicator_name,
                NULL::VARCHAR AS location, NULL::VARCHAR AS contract_month,
                NULL::VARCHAR AS column_name, NULL::DOUBLE AS value,
                NULL::VARCHAR AS value_raw, NULL::VARCHAR AS unit,
                NULL::VARCHAR AS measure, NULL::VARCHAR AS currency,
                NULL::VARCHAR AS unit_std, NULL::VARCHAR AS price_basis,
                NULL::VARCHAR AS contract, NULL::VARCHAR AS state,
                NULL::VARCHAR AS market_type
            WHERE false
        """)
        logger.warning("No Parquet files found in %s — created empty view", PARQUET_DIR)


def _register_basis_view(conn: duckdb.DuckDBPyConnection) -> None:
    """Create a view over basis Parquet files using Hive partitioning.

    If no basis Parquet files exist, creates an empty view with the expected schema.
    """
    basis_files = list(PARQUET_BASIS_DIR.glob("commodity=*/data.parquet")) if PARQUET_BASIS_DIR.exists() else []

    if basis_files:
        basis_glob = str(PARQUET_BASIS_DIR / "commodity=*" / "data.parquet")
        conn.execute(f"""
            CREATE OR REPLACE VIEW basis AS
            SELECT * FROM read_parquet(
                '{basis_glob}',
                hive_partitioning = true
            )
        """)
        logger.info("Registered DuckDB view 'basis' over %d Parquet files", len(basis_files))
    else:
        conn.execute("""
            CREATE OR REPLACE VIEW basis AS
            SELECT
                NULL::DATE AS date, NULL::VARCHAR AS commodity,
                NULL::VARCHAR AS location, NULL::VARCHAR AS state,
                NULL::VARCHAR AS physical_indicator,
                NULL::DOUBLE AS physical_price_brl,
                NULL::VARCHAR AS futures_indicator,
                NULL::VARCHAR AS futures_contract,
                NULL::DOUBLE AS futures_price_raw,
                NULL::DOUBLE AS futures_price_brl,
                NULL::DOUBLE AS ptax,
                NULL::DOUBLE AS basis_brl,
                NULL::DOUBLE AS basis_usd,
                NULL::DOUBLE AS basis_pct
            WHERE false
        """)
        logger.warning("No basis Parquet files found in %s — created empty view", PARQUET_BASIS_DIR)


def refresh_views() -> None:
    """Re-register views after ETL updates."""
    conn = get_connection()
    _register_views(conn)
    _register_basis_view(conn)


def close_connection() -> None:
    """Close the DuckDB connection."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def query(sql: str, params: list | None = None) -> list[dict]:
    """Execute a SQL query and return results as list of dicts."""
    conn = get_connection()
    if params:
        result = conn.execute(sql, params)
    else:
        result = conn.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def query_df(sql: str, params: list | None = None):
    """Execute a SQL query and return a pandas DataFrame."""
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetchdf()
    return conn.execute(sql).fetchdf()
