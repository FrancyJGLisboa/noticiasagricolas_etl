"""Tests for backward, current-contract-anchored basis roll adjustment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from noticiasagricolas_etl.basis.roll_adjustment import add_roll_adjustments
from noticiasagricolas_etl.basis_config import BASIS_PAIRS


def _pair(label: str):
    return next(pair for pair in BASIS_PAIRS if pair.label == label)


def _basis_frame(contracts: list[str], basis: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=len(contracts), freq="B")
    return pd.DataFrame(
        {
            "date": dates.date,
            "location": "Test/GO",
            "futures_indicator": "milho-b3-prego-regular",
            "futures_contract": contracts,
            "ptax": np.nan,
            "basis_brl": basis,
            "basis_usd": np.nan,
            "basis_centavos_sc": np.asarray(basis) * 100,
            "basis_cents_bu": np.nan,
        }
    )


def _futures(rows: list[tuple[int, str, float]]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=10, freq="B")
    return pd.DataFrame(
        [
            {
                "date": dates[date_index].date(),
                "contract": contract,
                "futures_price_raw": price,
            }
            for date_index, contract, price in rows
        ]
    )


def test_single_roll_uses_last_common_quote_and_anchors_latest_value():
    basis = _basis_frame(
        ["2025-01", "2025-01", "2025-03", "2025-03"],
        [10.0, 11.0, 7.0, 8.0],
    )
    futures = _futures(
        [
            (0, "2025-01", 100.0),
            (0, "2025-03", 104.0),
            (1, "2025-01", 101.0),
            (1, "2025-03", 106.0),
            (2, "2025-03", 107.0),
            (3, "2025-03", 108.0),
        ]
    )
    original = basis.copy(deep=True)

    result = add_roll_adjustments(
        basis,
        futures,
        pd.DataFrame(columns=["date", "ptax"]),
        _pair("milho-b3"),
    )

    assert result["roll"].tolist() == [False, False, True, False]
    assert result.loc[:1, "roll_gap_brl"].isna().all()
    assert result.loc[2, "roll_gap_brl"] == pytest.approx(5.0)
    assert result["roll_gap_missing"].tolist() == [False, False, False, False]
    assert result["basis_brl_adj"].tolist() == pytest.approx([5.0, 6.0, 7.0, 8.0])
    assert result["basis_centavos_sc_adj"].tolist() == pytest.approx(
        [500.0, 600.0, 700.0, 800.0]
    )
    pd.testing.assert_frame_equal(result[original.columns], original)
    assert result.iloc[-1]["basis_brl_adj"] == result.iloc[-1]["basis_brl"]


def test_two_rolls_subtract_all_later_gaps():
    basis = _basis_frame(
        ["2025-01", "2025-01", "2025-03", "2025-03", "2025-05", "2025-05"],
        [20.0, 21.0, 17.0, 18.0, 16.0, 17.0],
    )
    futures = _futures(
        [
            (0, "2025-01", 100.0),
            (0, "2025-03", 105.0),
            (1, "2025-01", 101.0),
            (1, "2025-03", 106.0),
            (2, "2025-03", 107.0),
            (2, "2025-05", 110.0),
            (3, "2025-03", 108.0),
            (3, "2025-05", 111.0),
            (4, "2025-05", 112.0),
            (5, "2025-05", 113.0),
        ]
    )

    result = add_roll_adjustments(
        basis,
        futures,
        pd.DataFrame(columns=["date", "ptax"]),
        _pair("milho-b3"),
    )

    assert result.loc[result["roll"], "roll_gap_brl"].tolist() == pytest.approx(
        [5.0, 3.0]
    )
    assert result["basis_brl_adj"].tolist() == pytest.approx(
        [12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    )


def test_missing_common_quote_leaves_step_unadjusted_without_nulls():
    basis = _basis_frame(
        ["2025-01", "2025-01", "2025-03", "2025-03"],
        [10.0, 11.0, 7.0, 8.0],
    )
    futures = _futures(
        [
            (0, "2025-01", 100.0),
            (1, "2025-01", 101.0),
            (2, "2025-03", 107.0),
            (3, "2025-03", 108.0),
        ]
    )

    result = add_roll_adjustments(
        basis,
        futures,
        pd.DataFrame(columns=["date", "ptax"]),
        _pair("milho-b3"),
    )

    assert result["roll_gap_missing"].tolist() == [False, False, True, False]
    assert result["basis_brl_adj"].tolist() == pytest.approx([10.0, 11.0, 7.0, 8.0])


def test_missing_gap_preserves_boundary_step_between_adjusted_segments():
    basis = _basis_frame(
        [
            "2025-01",
            "2025-01",
            "2025-03",
            "2025-03",
            "2025-05",
            "2025-05",
            "2025-07",
            "2025-07",
        ],
        [20.0, 21.0, 17.0, 18.0, 8.0, 9.0, 6.0, 7.0],
    )
    futures = _futures(
        [
            (0, "2025-01", 100.0),
            (0, "2025-03", 105.0),
            (1, "2025-01", 101.0),
            (1, "2025-03", 106.0),
            (2, "2025-03", 107.0),
            (3, "2025-03", 108.0),
            (4, "2025-05", 110.0),
            (4, "2025-07", 112.0),
            (5, "2025-05", 111.0),
            (5, "2025-07", 113.0),
            (6, "2025-07", 114.0),
            (7, "2025-07", 115.0),
        ]
    )

    result = add_roll_adjustments(
        basis,
        futures,
        pd.DataFrame(columns=["date", "ptax"]),
        _pair("milho-b3"),
    )

    assert result.loc[result["roll"], "roll_gap_missing"].tolist() == [
        False,
        True,
        False,
    ]
    assert result["basis_brl_adj"].tolist() == pytest.approx(
        [13.0, 14.0, 15.0, 16.0, 6.0, 7.0, 6.0, 7.0]
    )
    raw_missing_step = result.loc[4, "basis_brl"] - result.loc[3, "basis_brl"]
    adjusted_missing_step = (
        result.loc[4, "basis_brl_adj"] - result.loc[3, "basis_brl_adj"]
    )
    assert adjusted_missing_step == pytest.approx(raw_missing_step)
    for raw_column in (
        "basis_brl",
        "basis_usd",
        "basis_centavos_sc",
        "basis_cents_bu",
    ):
        adjusted_column = f"{raw_column}_adj"
        assert result[raw_column].notna().equals(result[adjusted_column].notna())


def test_no_roll_keeps_adjusted_columns_equal_to_raw_columns():
    basis = _basis_frame(["2025-03"] * 4, [1.0, 2.0, 3.0, 4.0])
    futures = _futures([(index, "2025-03", 100.0 + index) for index in range(4)])

    result = add_roll_adjustments(
        basis,
        futures,
        pd.DataFrame(columns=["date", "ptax"]),
        _pair("milho-b3"),
    )

    assert not result["roll"].any()
    assert not result["roll_gap_missing"].any()
    pd.testing.assert_series_equal(
        result["basis_brl_adj"], result["basis_brl"], check_names=False
    )
    pd.testing.assert_series_equal(
        result["basis_centavos_sc_adj"],
        result["basis_centavos_sc"],
        check_names=False,
    )


def test_cbot_roll_gap_is_exposed_in_cents_per_bushel():
    basis = _basis_frame(
        ["2025-01", "2025-01", "2025-03", "2025-03"],
        [10.0, 11.0, 7.0, 8.0],
    )
    basis["futures_indicator"] = "soja-bolsa-de-chicago-cme-group"
    basis["ptax"] = 5.0
    basis["basis_usd"] = basis["basis_brl"] / 5.0
    basis["basis_cents_bu"] = basis["basis_usd"] / _pair("soja-cbot").bu_per_sc * 100
    futures = _futures(
        [
            (0, "2025-01", 10.00),
            (0, "2025-03", 10.20),
            (1, "2025-01", 10.10),
            (1, "2025-03", 10.35),
            (2, "2025-03", 10.40),
            (3, "2025-03", 10.45),
        ]
    )
    ptax = pd.DataFrame(
        {"date": pd.date_range("2025-01-02", periods=4, freq="B").date, "ptax": 5.0}
    )

    result = add_roll_adjustments(basis, futures, ptax, _pair("soja-cbot"))

    roll = result[result["roll"]].iloc[0]
    assert roll["roll_gap_cents_bu"] == pytest.approx(25.0)
    assert result.iloc[-1]["basis_cents_bu_adj"] == pytest.approx(
        result.iloc[-1]["basis_cents_bu"]
    )
