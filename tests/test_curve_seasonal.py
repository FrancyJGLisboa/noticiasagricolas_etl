"""Unit tests for curve_seasonal_service — direct math on fabricated data.

These tests bypass DuckDB by monkey-patching the slopes-history loader so
we can fabricate a known seasonal pattern and assert the z-score lands where
expected. The service's bucketing (Bucket from analytics.diagnostic) and
window selection are the math we want to lock down.
"""

from __future__ import annotations

import pandas as pd
import pytest

from noticiasagricolas_etl.api.services import curve_seasonal_service


def _fabricate_slopes(rows: list[tuple[str, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "slope_pct_per_month"])
    df["date"] = pd.to_datetime(df["date"])
    return df


@pytest.fixture
def patch_slopes(monkeypatch):
    """Monkey-patch the DuckDB-backed slopes loader with fabricated data."""
    def _set(rows):
        df = _fabricate_slopes(rows)
        monkeypatch.setattr(
            curve_seasonal_service, "_slopes_history",
            lambda *args, **kwargs: df,
        )
        return df
    return _set


class TestSeasonalWindow:
    """The ±window_days picker, isolated from the service entry point."""

    def test_picks_dates_within_window_excluding_target(self):
        slopes = _fabricate_slopes([
            ("2020-06-15", 0.5),  # ±14d → in
            ("2021-06-10", 0.4),  # ±14d → in
            ("2022-06-30", 0.6),  # 16d away from June 15 doy → out
            ("2023-06-15", 999.0),  # SAME date as target — must be excluded
            ("2024-12-15", 0.7),  # half-year away → out
        ])
        target = pd.Timestamp("2023-06-15")
        out = curve_seasonal_service._seasonal_window(slopes, target, window_days=14)
        assert len(out) == 2
        assert 999.0 not in out["slope_pct_per_month"].values

    def test_handles_year_boundary(self):
        # Target Jan 5; window=14 should also pick late-Dec dates from prior years.
        slopes = _fabricate_slopes([
            ("2020-12-25", 0.1),  # 11d before doy=5 across year → in
            ("2021-01-15", 0.2),  # 10d after → in
            ("2022-02-01", 0.3),  # 27d after → out
        ])
        target = pd.Timestamp("2023-01-05")
        out = curve_seasonal_service._seasonal_window(slopes, target, window_days=14)
        assert len(out) == 2

    def test_empty_input(self):
        slopes = _fabricate_slopes([])
        out = curve_seasonal_service._seasonal_window(
            slopes, pd.Timestamp("2024-06-15"), window_days=14,
        )
        assert out.empty


class TestGetCurveSeasonal:
    def test_zero_variance_baseline_returns_error(self, patch_slopes):
        # Constant slope across baseline → std=0 → service rejects
        rows = [(f"2020-06-{d:02d}", 0.5) for d in range(1, 29)]
        rows.append(("2024-06-15", 0.7))
        patch_slopes(rows)
        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="soja-cbot",
            target_date="2024-06-15",
            min_obs=10,
        )
        assert "error" in r
        assert "zero variance" in r["error"].lower()

    def test_high_zscore_classifies_muito_acima(self, patch_slopes):
        # Baseline mean ≈ 0, std ≈ 0.1; target = 0.5 → z ≈ +5
        import random
        random.seed(0)
        rows = []
        for year in range(2018, 2024):
            for d in range(1, 30):
                rows.append((f"{year}-06-{d:02d}", random.gauss(0.0, 0.1)))
        rows.append(("2024-06-15", 0.5))  # target — way above baseline
        patch_slopes(rows)

        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="soja-cbot",
            target_date="2024-06-15",
            min_obs=20,
        )
        assert "error" not in r
        assert r["z_score"] > 2.0
        assert r["regime"] == "muito_acima"
        assert "MUITO MAIS contango" in r["interpretation"]

    def test_low_zscore_classifies_muito_abaixo(self, patch_slopes):
        import random
        random.seed(1)
        rows = []
        for year in range(2018, 2024):
            for d in range(1, 30):
                rows.append((f"{year}-06-{d:02d}", random.gauss(0.0, 0.1)))
        rows.append(("2024-06-15", -0.5))
        patch_slopes(rows)

        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="soja-cbot", target_date="2024-06-15", min_obs=20,
        )
        assert "error" not in r
        assert r["z_score"] < -2.0
        assert r["regime"] == "muito_abaixo"
        assert "MUITO MAIS BACKWARDATED" in r["interpretation"]

    def test_typical_zscore_classifies_tipico(self, patch_slopes):
        import random
        random.seed(2)
        rows = []
        for year in range(2018, 2024):
            for d in range(1, 30):
                rows.append((f"{year}-06-{d:02d}", random.gauss(0.0, 0.5)))
        rows.append(("2024-06-15", 0.05))  # within ±0.5σ of mean
        patch_slopes(rows)

        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="soja-cbot", target_date="2024-06-15", min_obs=20,
        )
        assert "error" not in r
        assert -1.0 < r["z_score"] < 1.0
        assert r["regime"] == "tipico"

    def test_insufficient_history_returns_error(self, patch_slopes):
        # Only 5 obs in the window — below default min_obs=20
        rows = [
            ("2020-06-10", 0.1), ("2021-06-12", 0.2),
            ("2022-06-14", 0.3), ("2023-06-16", 0.4),
            ("2024-06-15", 0.5),
        ]
        patch_slopes(rows)
        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="soja-cbot", target_date="2024-06-15",
        )
        assert "error" in r
        assert "insufficient seasonal history" in r["error"]

    def test_no_data_returns_error(self, patch_slopes):
        patch_slopes([])
        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="bogus-indicator",
        )
        assert "error" in r
        assert "no slope history" in r["error"]

    def test_target_date_not_in_data_returns_error(self, patch_slopes):
        patch_slopes([
            ("2024-06-15", 0.3),
        ])
        r = curve_seasonal_service.get_curve_seasonal(
            futures_indicator="soja-cbot",
            target_date="2020-01-01",
        )
        assert "error" in r
        assert "no slope data on or before" in r["error"]
