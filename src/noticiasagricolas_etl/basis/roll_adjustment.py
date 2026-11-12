"""Add current-contract-anchored roll adjustments to materialized basis rows."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..basis_config import BasisPairConfig

ROLL_LOOKBACK_TRADING_DAYS = 5

ROLL_COLUMNS = [
    "roll",
    "roll_gap_brl",
    "roll_gap_cents_bu",
    "roll_gap_missing",
    "basis_brl_adj",
    "basis_usd_adj",
    "basis_centavos_sc_adj",
    "basis_cents_bu_adj",
]


@dataclass(frozen=True)
class _RollGap:
    """One roll gap expressed in every basis unit used by the pair."""

    brl: float
    usd: float
    centavos_sc: float
    cents_bu: float


def _is_cbot(indicator: str) -> bool:
    value = indicator.lower()
    return "chicago" in value or "cbot" in value


def _prepare_futures(futures_df: pd.DataFrame) -> pd.DataFrame:
    """Return one non-null quote per date and contract in stable source order."""
    if futures_df.empty:
        return pd.DataFrame(columns=["date", "contract", "futures_price_raw"])
    quotes = futures_df[["date", "contract", "futures_price_raw"]].copy()
    quotes["date"] = pd.to_datetime(quotes["date"])
    quotes = quotes.dropna(subset=["date", "contract", "futures_price_raw"])
    return (
        quotes.sort_values(["date", "contract"], kind="stable")
        .drop_duplicates(["date", "contract"], keep="first")
        .reset_index(drop=True)
    )


def _prepare_ptax(ptax_df: pd.DataFrame) -> dict[pd.Timestamp, float]:
    """Return a date-to-PTAX map with normalized timestamp keys."""
    if ptax_df.empty:
        return {}
    rates = ptax_df[["date", "ptax"]].dropna(subset=["date", "ptax"]).copy()
    rates["date"] = pd.to_datetime(rates["date"])
    rates = rates.drop_duplicates("date", keep="last")
    return {
        pd.Timestamp(row.date): float(row.ptax)
        for row in rates.itertuples(index=False)
    }


def _find_roll_gap(
    quotes: pd.DataFrame,
    ptax_by_date: dict[pd.Timestamp, float],
    *,
    outgoing_contract: str,
    incoming_contract: str,
    switch_date: pd.Timestamp,
    config: BasisPairConfig,
) -> _RollGap | None:
    """Find the last same-day contract gap in the five source dates before a roll."""
    before_switch = quotes[quotes["date"] < switch_date]
    trading_dates = before_switch["date"].drop_duplicates().tail(
        ROLL_LOOKBACK_TRADING_DAYS
    )
    if trading_dates.empty:
        return None

    candidates = before_switch[
        before_switch["date"].isin(trading_dates)
        & before_switch["contract"].isin([outgoing_contract, incoming_contract])
    ]
    if candidates.empty:
        return None

    pivot = candidates.pivot(
        index="date",
        columns="contract",
        values="futures_price_raw",
    )
    if outgoing_contract not in pivot.columns or incoming_contract not in pivot.columns:
        return None
    common = pivot.dropna(subset=[outgoing_contract, incoming_contract])
    if common.empty:
        return None

    gap_date = pd.Timestamp(common.index.max())
    outgoing_raw = float(common.loc[gap_date, outgoing_contract])
    incoming_raw = float(common.loc[gap_date, incoming_contract])

    if config.needs_ptax:
        ptax = ptax_by_date.get(gap_date)
        if ptax is None or ptax == 0:
            return None
    else:
        ptax = 0.0

    outgoing_brl = float(config.convert_futures(outgoing_raw, ptax))
    incoming_brl = float(config.convert_futures(incoming_raw, ptax))
    gap_brl = incoming_brl - outgoing_brl

    gap_usd = gap_brl / ptax if config.needs_ptax else float("nan")
    gap_centavos_sc = (
        gap_brl * 100.0
        if config.physical_unit.endswith("/sc60kg")
        else float("nan")
    )
    gap_cents_bu = (
        gap_usd / config.bu_per_sc * 100.0
        if config.needs_ptax and config.bu_per_sc is not None
        else float("nan")
    )
    return _RollGap(
        brl=gap_brl,
        usd=gap_usd,
        centavos_sc=gap_centavos_sc,
        cents_bu=gap_cents_bu,
    )


def add_roll_adjustments(
    basis_df: pd.DataFrame,
    futures_df: pd.DataFrame,
    ptax_df: pd.DataFrame,
    config: BasisPairConfig,
) -> pd.DataFrame:
    """Append roll metadata and backward-adjusted basis columns.

    The latest observation in each location and futures-reference series stays
    equal to the raw basis. Each earlier segment subtracts all later roll gaps.
    A missing roll gap makes adjusted values before that roll null.
    """
    result = basis_df.copy(deep=True)
    result["roll"] = False
    result["roll_gap_brl"] = np.nan
    result["roll_gap_cents_bu"] = np.nan
    result["roll_gap_missing"] = False
    for column in (
        "basis_brl_adj",
        "basis_usd_adj",
        "basis_centavos_sc_adj",
        "basis_cents_bu_adj",
    ):
        result[column] = np.nan

    if result.empty:
        return result

    quotes = _prepare_futures(futures_df)
    ptax_by_date = _prepare_ptax(ptax_df)
    dates = pd.to_datetime(result["date"])

    gap_usd = pd.Series(np.nan, index=result.index, dtype=float)
    gap_centavos_sc = pd.Series(np.nan, index=result.index, dtype=float)
    gap_cents_bu = pd.Series(np.nan, index=result.index, dtype=float)

    group_columns = ["location", "futures_indicator"]
    for _, group in result.assign(_date=dates).groupby(
        group_columns,
        sort=False,
        dropna=False,
    ):
        ordered = group.sort_values("_date", kind="stable")
        previous_contract = ordered["futures_contract"].shift()
        roll_mask = previous_contract.notna() & ordered["futures_contract"].ne(
            previous_contract
        )
        result.loc[ordered.index, "roll"] = roll_mask.to_numpy(dtype=bool)

        for position in np.flatnonzero(roll_mask.to_numpy(dtype=bool)):
            row_index = ordered.index[position]
            roll_gap = _find_roll_gap(
                quotes,
                ptax_by_date,
                outgoing_contract=str(previous_contract.iloc[position]),
                incoming_contract=str(ordered.iloc[position]["futures_contract"]),
                switch_date=pd.Timestamp(ordered.iloc[position]["_date"]),
                config=config,
            )
            if roll_gap is None:
                result.loc[row_index, "roll_gap_missing"] = True
                continue

            result.loc[row_index, "roll_gap_brl"] = roll_gap.brl
            if _is_cbot(config.futures_indicator):
                result.loc[row_index, "roll_gap_cents_bu"] = roll_gap.cents_bu
            gap_usd.loc[row_index] = roll_gap.usd
            gap_centavos_sc.loc[row_index] = roll_gap.centavos_sc
            gap_cents_bu.loc[row_index] = roll_gap.cents_bu

        metric_gaps = {
            "basis_brl": result["roll_gap_brl"],
            "basis_usd": gap_usd,
            "basis_centavos_sc": gap_centavos_sc,
            "basis_cents_bu": gap_cents_bu,
        }
        cumulative = {metric: 0.0 for metric in metric_gaps}
        blocked = False
        for row_index in reversed(ordered.index.tolist()):
            for metric, gaps in metric_gaps.items():
                output_column = f"{metric}_adj"
                raw_value = result.at[row_index, metric]
                if blocked or pd.isna(raw_value):
                    result.at[row_index, output_column] = np.nan
                else:
                    result.at[row_index, output_column] = (
                        float(raw_value) - cumulative[metric]
                    )

            if bool(result.at[row_index, "roll"]):
                if bool(result.at[row_index, "roll_gap_missing"]):
                    blocked = True
                    continue
                for metric, gaps in metric_gaps.items():
                    gap_value = gaps.at[row_index]
                    if not pd.isna(gap_value):
                        cumulative[metric] += float(gap_value)

    return result
