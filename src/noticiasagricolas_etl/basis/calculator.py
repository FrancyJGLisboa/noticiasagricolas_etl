"""Pure basis math — no I/O, no DuckDB.

`select_front_month` picks the nearest-expiry contract per date.
`compute_basis_columns` joins physical/futures/PTAX and computes the basis
columns the materialized basis parquet exposes:

  - basis_brl       — physical_price_brl - futures_price_brl
  - basis_usd       — basis_brl / ptax (when needs_ptax)
  - basis_pct       — basis_brl / futures_price_brl × 100
  - basis_centavos_sc — basis_brl × 100 (only when physical_unit ends with /sc60kg)
  - basis_cents_bu  — basis_brl / ptax / bu_per_sc × 100 (CBOT global convention)

Both functions are pure: same inputs → same outputs, no side effects, no
side-channel state. Easy to unit-test against fabricated DataFrames.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..basis_config import BasisPairConfig

logger = logging.getLogger(__name__)


def select_front_month(futures_df: pd.DataFrame) -> pd.DataFrame:
    """For each date, pick the nearest-expiry contract whose YYYY-MM is >= the date's YYYY-MM.

    If all contracts have already expired (rare backfill edge case), falls back
    to the most recent contract on that date.

    Input: DataFrame(date, contract, futures_price_raw).
    Output: DataFrame(date, futures_contract, futures_price_raw) — one row per date.
    """
    if futures_df.empty:
        return pd.DataFrame(columns=["date", "futures_contract", "futures_price_raw"])

    results = []
    for dt, group in futures_df.groupby("date"):
        date_ym = f"{dt.year}-{dt.month:02d}"
        valid = group[group["contract"] >= date_ym]
        if not valid.empty:
            row = valid.loc[valid["contract"].idxmin()]
        else:
            row = group.loc[group["contract"].idxmax()]
        results.append({
            "date": dt,
            "futures_contract": row["contract"],
            "futures_price_raw": row["futures_price_raw"],
        })
    return pd.DataFrame(results)


def compute_basis_columns(
    physical: pd.DataFrame,
    futures_front_month: pd.DataFrame,
    ptax_df: pd.DataFrame,
    config: BasisPairConfig,
) -> pd.DataFrame:
    """Join physical × futures × ptax and compute the basis columns.

    Returns the wide basis DataFrame with all columns the BASIS_SCHEMA expects.
    Empty DataFrame if any join produces no rows. Logging is informational —
    callers decide whether to treat empty as fatal.
    """
    columns = [
        "date", "location", "state", "physical_indicator",
        "physical_price_brl", "futures_indicator", "futures_contract",
        "futures_price_raw", "futures_price_brl", "ptax",
        "basis_brl", "basis_usd", "basis_pct",
        "basis_centavos_sc", "basis_cents_bu",
    ]

    if physical.empty:
        logger.info("No physical data for %s", config.label)
        return pd.DataFrame(columns=columns)
    if futures_front_month.empty:
        logger.info("No futures data for %s", config.label)
        return pd.DataFrame(columns=columns)

    merged = physical.merge(futures_front_month, on="date", how="inner")
    if merged.empty:
        logger.info("No overlapping dates for %s", config.label)
        return pd.DataFrame(columns=columns)

    if config.needs_ptax:
        if ptax_df.empty:
            logger.warning("PTAX data missing, cannot compute %s", config.label)
            return pd.DataFrame(columns=columns)
        merged = merged.merge(ptax_df, on="date", how="inner")
        if merged.empty:
            logger.info("No overlapping PTAX dates for %s", config.label)
            return pd.DataFrame(columns=columns)
    else:
        merged["ptax"] = np.nan

    if config.needs_ptax:
        merged["futures_price_brl"] = merged.apply(
            lambda r: config.convert_futures(r["futures_price_raw"], r["ptax"]),
            axis=1,
        )
    else:
        merged["futures_price_brl"] = merged["futures_price_raw"].apply(
            lambda v: config.convert_futures(v, 0.0)
        )

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

    merged["futures_indicator"] = config.futures_indicator

    result = merged[columns].copy()
    return result.sort_values(["date", "location"]).reset_index(drop=True)
