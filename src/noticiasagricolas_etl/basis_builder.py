"""Build materialized daily basis time series (physical - futures).

Reads existing Parquet data via DuckDB, computes basis per commodity-location
pair, and writes Hive-partitioned Parquet to data/parquet_basis/.
"""

import logging
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .basis_config import BasisPairConfig, get_pairs
from .config import CSV_DIR, PARQUET_BASIS_DIR, PARQUET_DIR
from .normalize import extract_state

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


# ── Port location normalization ──────────────────────────────────────────────

# Patterns: "Porto Santos/SP (Fev/Mar-2025) (Dellagro)" -> "Porto Santos/SP"
#           "Porto Paranaguá (disponível) (Insoy Commodities)" -> "Porto Paranaguá/PR"
_PORT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^Porto Santos/SP\b.*"), "Porto Santos/SP"),
    (re.compile(r"^Porto Paranagu[áa]\b.*"), "Porto Paranaguá/PR"),
    (re.compile(r"^Porto de São Francisco do Sul/SC\b.*"), "Porto São Francisco do Sul/SC"),
    (re.compile(r"^Porto Imbituba/SC\b.*"), "Porto Imbituba/SC"),
    (re.compile(r"^Porto Rio Grande\b.*"), "Porto Rio Grande/RS"),
]

# Bare city names from soja-mercado-fisico-ms (no state code)
_BARE_CITY_STATE: dict[str, str] = {
    "Paranaguá": "PR",
    "Maringá": "PR",
    "Campo Grande": "MS",
    "Dourados": "MS",
    "Maracaju": "MS",
    "Ponta Porã": "MS",
    "Sidrolândia": "MS",
    "São Gabriel do Oeste": "MS",
    "Chapadão do Sul": "MS",
    "Caarapó": "MS",
    "Sonora": "MS",
    "Oeste da Bahia": "BA",
}


_INDICATOR_LOCATIONS: dict[str, str] = {
    "boi-gordo-indicador-esalq-bmf": "Indicador ESALQ/SP",
}


def _indicator_location(indicator: str) -> str:
    """Map indicator slug to a synthetic location for indicators without location."""
    return _INDICATOR_LOCATIONS.get(indicator, f"Indicador {indicator}")


def _normalize_location(location: str) -> str:
    """Normalize location names to canonical form for chart-ready output.

    - Strips contract/broker details from port names
    - Adds state code to bare city names (from soja-mercado-fisico-ms)
    - Strips parenthetical broker/cooperative suffixes and trailing qualifiers
      e.g. "Rio Verde/GO (Comigo)" → "Rio Verde/GO"
           "Sorriso/MT (Sindicato) Transgênica Balcão" → "Sorriso/MT"
    """
    if not location:
        return location

    # Port normalization (specific patterns first)
    for pattern, canonical in _PORT_PATTERNS:
        if pattern.match(location):
            return canonical

    # Bare city → City/ST (must check before stripping parens)
    stripped = location.strip()
    if "/" not in stripped and "(" not in stripped:
        for city, state in _BARE_CITY_STATE.items():
            if stripped == city:
                return f"{city}/{state}"

    # Strip parenthetical suffixes: "(Comigo)", "(Sindicato) Transgênica ...", etc.
    if "(" in location:
        cleaned = re.sub(r"\s*\(.*$", "", location).strip()
        if cleaned:
            # Re-check bare city mapping on cleaned result
            # e.g. "Oeste da Bahia (AIBA)" → "Oeste da Bahia" → "Oeste da Bahia/BA"
            if "/" not in cleaned:
                for city, state in _BARE_CITY_STATE.items():
                    if cleaned == city:
                        return f"{city}/{state}"
            return cleaned

    return location


def _normalize_and_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize location names and average duplicates on same date+location.

    When port entries are collapsed (e.g. multiple Santos variants on one date),
    takes the mean physical price. Keeps the first physical_indicator and
    recomputes state from the normalized location.

    Also converts R$/kg locations (e.g. "RS Oeste (kg)") to R$/@ by × 15.
    """
    if df.empty:
        return df

    df = df.copy()

    # Convert R$/kg locations to R$/@ before normalization strips the "(kg)" tag
    kg_mask = df["location"].str.contains(r"\(kg\)", na=False)
    if kg_mask.any():
        df.loc[kg_mask, "physical_price_brl"] = df.loc[kg_mask, "physical_price_brl"] * 15.0

    # Filter out zero/negative prices (holiday anomalies)
    df = df[df["physical_price_brl"] > 0]

    df["location"] = df["location"].apply(_normalize_location)
    df["state"] = df["location"].apply(extract_state)

    # Average duplicates (same date + location from port aggregation)
    grouped = df.groupby(["date", "location"], as_index=False).agg({
        "state": "first",
        "physical_indicator": "first",
        "physical_price_brl": "mean",
    })
    return grouped


# ── Data loading ─────────────────────────────────────────────────────────────

def _parquet_exists(commodity: str) -> bool:
    """Check if source Parquet data exists for a commodity."""
    path = PARQUET_DIR / f"commodity={commodity}" / "data.parquet"
    return path.exists()


def _load_ptax(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load PTAX USD rate from mercado-financeiro Parquet.

    Filters: indicator='cambio-ptax', location='Dólar', measure='price'.
    Forward-fills missing dates (weekends/holidays).
    Returns DataFrame(date, ptax).
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

    # Expand to full calendar range and forward-fill
    min_date = df["date"].min()
    max_date = df["date"].max()
    all_dates = pd.date_range(min_date, max_date, freq="D")
    full = pd.DataFrame({"date": all_dates.date})
    full = full.merge(df, on="date", how="left")
    full["ptax"] = full["ptax"].ffill()
    return full


def _load_physical_prices(
    conn: duckdb.DuckDBPyConnection,
    indicators: tuple[str, ...],
    commodity: str,
) -> pd.DataFrame:
    """Load physical prices from one or more indicators.

    Filters by measure='price', value IS NOT NULL, location IS NOT NULL.
    Normalizes port/bare-city locations and averages duplicates.
    Returns DataFrame(date, location, state, physical_indicator, physical_price_brl).
    """
    parquet_path = PARQUET_DIR / f"commodity={commodity}" / "data.parquet"
    if not parquet_path.exists():
        return pd.DataFrame(columns=["date", "location", "state", "physical_indicator", "physical_price_brl"])

    frames = []
    for indicator in indicators:
        # Physical/multi-location data (location IS NOT NULL)
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

        # Indicator-type data without location (e.g. ESALQ reference prices)
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
            # Assign synthetic location from indicator name
            df_ind["location"] = _indicator_location(indicator)
            df_ind["state"] = None
            frames.append(df_ind)

    if not frames:
        return pd.DataFrame(columns=["date", "location", "state", "physical_indicator", "physical_price_brl"])

    combined = pd.concat(frames, ignore_index=True)
    return _normalize_and_aggregate(combined)


def _load_futures_prices(
    conn: duckdb.DuckDBPyConnection, indicator: str, commodity: str,
) -> pd.DataFrame:
    """Load futures prices where contract IS NOT NULL, measure='price'.

    Returns DataFrame(date, contract, futures_price_raw).
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


def _select_front_month(futures_df: pd.DataFrame) -> pd.DataFrame:
    """For each date, pick nearest-expiry contract >= date's YYYY-MM.

    Fallback to most recent contract if all have expired.
    Returns DataFrame(date, futures_contract, futures_price_raw) — one row per date.
    """
    if futures_df.empty:
        return pd.DataFrame(columns=["date", "futures_contract", "futures_price_raw"])

    results = []
    for dt, group in futures_df.groupby("date"):
        date_ym = f"{dt.year}-{dt.month:02d}"
        # Contracts >= current month
        valid = group[group["contract"] >= date_ym]
        if not valid.empty:
            # Nearest expiry = smallest contract
            row = valid.loc[valid["contract"].idxmin()]
        else:
            # Fallback: most recent contract
            row = group.loc[group["contract"].idxmax()]
        results.append({
            "date": dt,
            "futures_contract": row["contract"],
            "futures_price_raw": row["futures_price_raw"],
        })

    return pd.DataFrame(results)


# ── Basis computation ────────────────────────────────────────────────────────

def build_pair(
    conn: duckdb.DuckDBPyConnection,
    config: BasisPairConfig,
    ptax_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute basis for one commodity-futures pair.

    1. Load physical prices (all locations, all indicators)
    2. Load futures, select front month per date
    3. Join physical x futures on date
    4. If needs_ptax: join PTAX on date
    5. Apply config.convert_futures to get futures_price_brl
    6. Compute basis_brl, basis_usd, basis_pct
    """
    physical = _load_physical_prices(conn, config.physical_indicators, config.commodity)
    if physical.empty:
        logger.info("No physical data for %s", config.label)
        return pd.DataFrame(columns=[f.name for f in BASIS_SCHEMA])

    futures_raw = _load_futures_prices(conn, config.futures_indicator, config.commodity)
    if futures_raw.empty:
        logger.info("No futures data for %s", config.label)
        return pd.DataFrame(columns=[f.name for f in BASIS_SCHEMA])

    futures = _select_front_month(futures_raw)

    # Join physical x futures on date (inner join — only dates with both)
    merged = physical.merge(futures, on="date", how="inner")
    if merged.empty:
        logger.info("No overlapping dates for %s", config.label)
        return pd.DataFrame(columns=[f.name for f in BASIS_SCHEMA])

    # Join PTAX if needed
    if config.needs_ptax:
        if ptax_df.empty:
            logger.warning("PTAX data missing, cannot compute %s", config.label)
            return pd.DataFrame(columns=[f.name for f in BASIS_SCHEMA])
        merged = merged.merge(ptax_df, on="date", how="inner")
        if merged.empty:
            logger.info("No overlapping PTAX dates for %s", config.label)
            return pd.DataFrame(columns=[f.name for f in BASIS_SCHEMA])
    else:
        merged["ptax"] = np.nan

    # Apply futures conversion
    if config.needs_ptax:
        merged["futures_price_brl"] = merged.apply(
            lambda r: config.convert_futures(r["futures_price_raw"], r["ptax"]),
            axis=1,
        )
    else:
        merged["futures_price_brl"] = merged["futures_price_raw"].apply(
            lambda v: config.convert_futures(v, 0.0)
        )

    # Compute basis
    merged["basis_brl"] = merged["physical_price_brl"] - merged["futures_price_brl"]
    merged["basis_usd"] = np.where(
        merged["ptax"].notna() & (merged["ptax"] != 0),
        merged["basis_brl"] / merged["ptax"],
        np.nan,
    )
    merged["basis_pct"] = np.where(
        merged["futures_price_brl"] != 0,
        (merged["basis_brl"] / merged["futures_price_brl"]) * 100,
        np.nan,
    )

    # Trade-desk quote columns:
    # - basis_centavos_sc: BR convention, only for sc60kg-denominated physicals.
    # - basis_cents_bu: CBOT global convention, only for grains with bu_per_sc
    #   set AND with PTAX available (needs USD conversion).
    if config.physical_unit.endswith("/sc60kg"):
        merged["basis_centavos_sc"] = merged["basis_brl"] * 100.0
    else:
        merged["basis_centavos_sc"] = np.nan
    if config.bu_per_sc is not None:
        merged["basis_cents_bu"] = np.where(
            merged["ptax"].notna() & (merged["ptax"] != 0),
            merged["basis_brl"] / merged["ptax"] / config.bu_per_sc * 100.0,
            np.nan,
        )
    else:
        merged["basis_cents_bu"] = np.nan

    # Build output
    merged["futures_indicator"] = config.futures_indicator

    result = merged[[
        "date", "location", "state", "physical_indicator",
        "physical_price_brl", "futures_indicator", "futures_contract",
        "futures_price_raw", "futures_price_brl", "ptax",
        "basis_brl", "basis_usd", "basis_pct",
        "basis_centavos_sc", "basis_cents_bu",
    ]].copy()

    result = result.sort_values(["date", "location"]).reset_index(drop=True)
    return result


def _write_basis_parquet(commodity: str, df: pd.DataFrame) -> Path:
    """Write basis DataFrame to Hive-partitioned Parquet."""
    out_dir = PARQUET_BASIS_DIR / f"commodity={commodity}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "data.parquet"

    table = pa.Table.from_pandas(df, schema=BASIS_SCHEMA, preserve_index=False)
    pq.write_table(table, path)
    logger.info("Wrote %d basis rows to %s", len(df), path)
    return path


def build_all(
    commodities: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Build basis panels for all configured pairs (or filtered by commodity).

    Skips pairs where Parquet data doesn't exist.
    Writes to data/parquet_basis/commodity={name}/data.parquet.
    Returns summary dict with row counts per pair.
    """
    conn = duckdb.connect(":memory:")
    pairs = get_pairs(commodities)
    summary: dict[str, int] = {}

    # Check which commodities have source data
    needed_commodities = {p.commodity for p in pairs}
    for commodity in needed_commodities:
        if not _parquet_exists(commodity):
            logger.info("Skipping %s — no source Parquet data", commodity)

    # Pre-load PTAX once (shared across all pairs that need FX)
    any_needs_ptax = any(p.needs_ptax for p in pairs if _parquet_exists(p.commodity))
    ptax_df = _load_ptax(conn) if any_needs_ptax else pd.DataFrame(columns=["date", "ptax"])

    # Build per-commodity accumulator for merging multiple pairs
    commodity_dfs: dict[str, list[pd.DataFrame]] = {}

    for pair in pairs:
        if not _parquet_exists(pair.commodity):
            logger.info("Skipping pair %s — no Parquet for %s", pair.label, pair.commodity)
            summary[pair.label] = 0
            continue

        logger.info("Building basis pair: %s", pair.label)
        df = build_pair(conn, pair, ptax_df)
        summary[pair.label] = len(df)

        if not df.empty:
            commodity_dfs.setdefault(pair.commodity, []).append(df)

    # Write one Parquet + CSV per commodity (combining multiple pairs)
    for commodity, dfs in commodity_dfs.items():
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values(["date", "futures_indicator", "location"]).reset_index(drop=True)
        _write_basis_parquet(commodity, combined)
        _export_basis_csv(commodity, combined)

    conn.close()
    return summary


def _export_basis_csv(commodity: str, df: pd.DataFrame) -> None:
    """Export basis DataFrame as CSV to data/csv/basis-{commodity}.csv."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / f"basis-{commodity}.csv"
    df.to_csv(path, index=False)
    logger.info("Exported basis CSV: %s (%d rows)", path, len(df))
