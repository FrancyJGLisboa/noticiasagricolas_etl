"""Focused tests for roll-aware basis opportunity analytics."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from noticiasagricolas_etl.analytics.basis_signals import (
    classified_changes,
    current_change_and_anomaly,
    percentile_metrics,
)
from noticiasagricolas_etl.api.services import (
    basis_opportunities_service,
    basis_percentile_service,
)
from noticiasagricolas_etl.api.services.hedge_fit_service import fit_hedge_frame


def test_changes_reject_contract_roll_and_long_gap():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-13"]
            ),
            "futures_contract": ["2026-01", "2026-01", "2026-03", "2026-03"],
            "basis_brl": [1.0, 2.0, 20.0, 21.0],
        }
    )

    changes, counts = classified_changes(frame, value_col="basis_brl", max_gap_days=5)

    assert counts == {"n_dropped_roll": 1, "n_dropped_gap": 1}
    assert changes["valid_change"].tolist() == [False, True, False, False]
    result = current_change_and_anomaly(frame, value_col="basis_brl")
    assert result["change_5d"] is None
    assert result["is_anomaly"] is False
    assert "data gap" in result["anomaly_reason"]


def test_contract_roll_never_flags_current_anomaly():
    dates = pd.bdate_range("2026-01-01", periods=70)
    frame = pd.DataFrame(
        {
            "date": dates,
            "futures_contract": ["2026-03"] * 69 + ["2026-05"],
            "basis_brl": np.r_[np.linspace(1, 2, 69), 100.0],
        }
    )

    result = current_change_and_anomaly(frame, value_col="basis_brl")

    assert result["is_anomaly"] is False
    assert result["anomaly_zscore"] is None
    assert result["n_dropped_roll"] == 1
    assert "contract roll" in result["anomaly_reason"]


def test_five_day_change_uses_only_valid_transitions_in_window():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-02-02", "2026-02-03", "2026-02-05", "2026-02-06"]
            ),
            "futures_contract": ["2026-03"] * 4,
            "basis_brl": [10.0, 11.0, 12.5, 14.0],
        }
    )

    result = current_change_and_anomaly(frame, value_col="basis_brl")

    assert result["change_5d"] == 4.0
    assert result["change_5d_reason"] is None


def test_seasonal_percentile_requires_30_observations():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-11-01", periods=29, freq="D"),
            "value": np.arange(29, dtype=float),
        }
    )

    metrics = percentile_metrics(
        frame,
        value_col="value",
        target_date=pd.Timestamp("2024-11-29"),
        window_years=5,
    )

    assert metrics["percentile_season"] is None
    assert metrics["n_obs_season"] == 29
    assert "minimum is 30" in metrics["seasonal_reason"]


def test_cbot_hedge_fit_uses_usd_and_reports_brl_separately():
    dates = pd.bdate_range("2025-01-02", periods=100)
    futures_usd = 20 + np.linspace(0, 3, len(dates)) + np.sin(np.arange(len(dates)))
    physical_usd = 10 + 0.55 * futures_usd + np.cos(np.arange(len(dates))) * 0.05
    ptax = 4.8 + np.linspace(0, 1.0, len(dates))
    contracts = np.where(np.arange(len(dates)) < 50, "2025-03", "2025-05")
    frame = pd.DataFrame(
        {
            "date": dates,
            "physical_price_brl": physical_usd * ptax,
            "futures_price_brl": futures_usd * ptax,
            "futures_contract": contracts,
            "ptax": ptax,
        }
    )

    result = fit_hedge_frame(
        frame,
        commodity="soja",
        location="Sorriso/MT",
        futures_indicator="soja-bolsa-de-chicago-cme-group",
        frequency="daily",
    )

    assert result["signal_currency"] == "USD"
    assert result["n_dropped_roll"] == 1
    assert result["beta"] == pytest_approx(0.55, abs=0.02)
    assert result["brl_fit"] is not None
    assert result["brl_fit"]["n_obs"] == result["n_obs"]


def pytest_approx(value: float, *, abs: float):
    """Import pytest lazily so the test data section stays compact."""
    import pytest

    return pytest.approx(value, abs=abs)


def _opportunity_rows() -> list[dict]:
    dates = pd.bdate_range("2021-11-01", "2026-11-11")
    rows: list[dict] = []
    for index, timestamp in enumerate(dates):
        basis_brl = -20 + index * 0.01
        rows.append(
            {
                "date": timestamp.date(),
                "location": "Active/MT",
                "state": "MT",
                "physical_indicator": "soja-fisico",
                "physical_price_brl": 120 + index * 0.01,
                "futures_indicator": "soja-bolsa-de-chicago-cme-group",
                "futures_contract": f"{timestamp.year}-{((timestamp.month - 1) // 2 * 2 + 1):02d}",
                "futures_price_brl": 140.0,
                "ptax": 5.0,
                "basis_brl": basis_brl,
                "basis_usd": basis_brl / 5,
                "basis_pct": basis_brl / 140 * 100,
                "basis_centavos_sc": basis_brl * 100,
                "basis_cents_bu": basis_brl / 5 / 2.2046 * 100,
            }
        )
    stale = rows[-1].copy()
    stale.update(
        {
            "date": date(2026, 9, 1),
            "location": "Stale/MT",
            "basis_brl": -10.0,
            "basis_cents_bu": -90.72,
        }
    )
    rows.append(stale)
    return rows


def test_opportunities_exclude_stale_and_expose_complete_signal(monkeypatch):
    monkeypatch.setattr(
        basis_opportunities_service.db,
        "query",
        lambda sql, params: _opportunity_rows(),
    )

    result = basis_opportunities_service.get_basis_opportunities(
        "soja",
        futures_indicator="soja-bolsa-de-chicago-cme-group",
        target_date="2026-11-11",
    )

    assert result["count"] == 1
    assert result["excluded_count"] == 1
    assert result["excluded"][0]["location"] == "Stale/MT"
    row = result["data"][0]
    required = {
        "current_basis",
        "percentile_all",
        "percentile_season",
        "change_5d",
        "anomaly_zscore",
        "hedge",
        "last_date",
        "n_obs_window",
        "days_since_last",
        "n_dropped_roll",
        "n_dropped_gap",
    }
    assert required <= row.keys()
    assert row["basis_column"] == "basis_cents_bu"
    assert row["basis_unit"] == "USD cents/bu"
    assert row["n_obs_season"] >= 30
    assert row["percentile_season"] is not None
    assert result["quote_count_available"] is False


def test_basis_interpretation_has_no_trade_instruction(monkeypatch):
    rows = [
        {
            "date": date(2026, 11, day),
            "futures_indicator": "soja-b3",
            "value": float(day),
        }
        for day in range(1, 31)
    ]
    monkeypatch.setattr(basis_percentile_service.db, "query", lambda sql, params: rows)

    result = basis_percentile_service.get_basis_percentile(
        commodity="soja",
        location="Sorriso/MT",
        futures_indicator="soja-b3",
        target_date="2026-11-30",
    )

    text = result["interpretation"].lower()
    for forbidden in (
        "buy",
        "sell",
        "hold",
        "comprar",
        "venda",
        "segurar",
        "recomprar",
    ):
        assert forbidden not in text
