"""Pure basis math — no I/O, no DuckDB.

`select_front_month` applies each market's contract-roll policy.
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

import calendar
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..basis_config import BasisPairConfig, ContractRollPolicy

logger = logging.getLogger(__name__)


_FRONT_MONTH_COLUMNS = ["date", "futures_contract", "futures_price_raw"]


def _select_nearest_available(futures_df: pd.DataFrame) -> pd.DataFrame:
    """Preserve the legacy per-date selection for markets without a roll policy."""
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
    return pd.DataFrame(results, columns=_FRONT_MONTH_COLUMNS)


def _shift_weekdays(value: date, count: int) -> date:
    """Shift a date by weekdays without embedding a B3 holiday calendar."""
    direction = 1 if count > 0 else -1
    remaining = abs(count)
    result = value
    while remaining:
        result += timedelta(days=direction)
        if result.weekday() < 5:
            remaining -= 1
    return result


def _last_weekday(year: int, month: int) -> date:
    result = date(year, month, calendar.monthrange(year, month)[1])
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def _expected_last_session(contract: str, policy: ContractRollPolicy) -> date:
    """Return the expected final session for a supported B3 contract."""
    try:
        year_text, month_text = contract.split("-", maxsplit=1)
        year, month = int(year_text), int(month_text)
        if not 1 <= month <= 12:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid normalized futures contract {contract!r}; expected YYYY-MM"
        ) from exc

    if policy == "b3_sjc":
        return _shift_weekdays(date(year, month, 1), -2)
    if policy == "b3_ccm":
        result = date(year, month, 15)
        while result.weekday() >= 5:
            result += timedelta(days=1)
        return result
    if policy == "b3_icf":
        return _shift_weekdays(_last_weekday(year, month), -6)
    if policy == "b3_bgi":
        return _last_weekday(year, month)
    raise ValueError(f"Unsupported B3 contract roll policy: {policy!r}")


def _select_b3_front_month(
    futures_df: pd.DataFrame,
    policy: ContractRollPolicy,
) -> pd.DataFrame:
    """Select a monotonic B3 contract series and keep gaps in the source data.

    The expected final session supplies the roll threshold. The source quote
    remains authoritative around exchange holidays. The selector keeps the
    current contract while its quote exists. It advances only when that quote
    is absent at or after the threshold.
    """
    contracts = sorted(futures_df["contract"].dropna().unique())
    if not contracts:
        return pd.DataFrame(columns=_FRONT_MONTH_COLUMNS)
    last_sessions = {
        contract: _expected_last_session(contract, policy)
        for contract in contracts
    }

    results = []
    contract_index: int | None = None
    for raw_date, group in futures_df.groupby("date", sort=True):
        observation_date = pd.Timestamp(raw_date).date()

        if contract_index is None:
            date_ym = f"{observation_date.year}-{observation_date.month:02d}"
            contract_index = next(
                (i for i, contract in enumerate(contracts) if contract >= date_ym),
                len(contracts) - 1,
            )

        target_rows = group[group["contract"] == contracts[contract_index]]
        while (
            target_rows.empty
            and contract_index < len(contracts) - 1
            and observation_date
            >= last_sessions[contracts[contract_index]]
        ):
            contract_index += 1
            target_rows = group[group["contract"] == contracts[contract_index]]

        if target_rows.empty:
            continue

        row = target_rows.iloc[0]
        results.append({
            "date": raw_date,
            "futures_contract": row["contract"],
            "futures_price_raw": row["futures_price_raw"],
        })

    return pd.DataFrame(results, columns=_FRONT_MONTH_COLUMNS)


def select_front_month(
    futures_df: pd.DataFrame,
    contract_roll_policy: ContractRollPolicy = "nearest_available",
) -> pd.DataFrame:
    """Select one front-month contract price for each source date.

    B3 policies preserve a monotonic contract series. A temporary missing quote
    creates a gap instead of substituting a later contract before expiry.
    Markets without a policy retain the legacy nearest-available selection.

    Input: DataFrame(date, contract, futures_price_raw).
    Output: DataFrame(date, futures_contract, futures_price_raw) — one row per date.
    """
    if futures_df.empty:
        return pd.DataFrame(columns=_FRONT_MONTH_COLUMNS)
    if contract_roll_policy == "nearest_available":
        return _select_nearest_available(futures_df)
    return _select_b3_front_month(futures_df, contract_roll_policy)


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
