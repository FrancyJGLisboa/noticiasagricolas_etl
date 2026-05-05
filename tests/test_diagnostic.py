"""Unit tests for analytics.diagnostic — the shared percentile/bucket/window-stats core."""

from __future__ import annotations

import pandas as pd
import pytest

from noticiasagricolas_etl.analytics.diagnostic import (
    PERCENTILE_3,
    PERCENTILE_5,
    Bucket,
    WindowStats,
    compute_window_stats,
)


def _series(dates: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "value": values})


class TestBucket:
    def test_classifies_5_bucket_percentile(self) -> None:
        b = PERCENTILE_5
        assert b.classify(5) == "extreme_low"
        assert b.classify(10) == "extreme_low"
        assert b.classify(20) == "low"
        assert b.classify(50) == "normal"
        assert b.classify(80) == "high"
        assert b.classify(95) == "extreme_high"

    def test_classifies_3_bucket_percentile(self) -> None:
        b = PERCENTILE_3
        assert b.classify(10) == "low"
        assert b.classify(50) == "normal"
        assert b.classify(80) == "high"

    def test_threshold_inclusive_lower(self) -> None:
        b = Bucket(thresholds=(10.0, 25.0), labels=("a", "b", "c"))
        # value <= threshold goes to that bucket
        assert b.classify(10) == "a"
        assert b.classify(25) == "b"
        assert b.classify(26) == "c"

    def test_validates_label_count(self) -> None:
        with pytest.raises(ValueError):
            Bucket(thresholds=(10.0, 25.0), labels=("a", "b"))  # need 3 labels

    def test_handles_abs_value_use_case(self) -> None:
        # anomaly-style: |z| thresholds
        b = Bucket(thresholds=(2.0, 3.0, 4.0), labels=("normal", "mild", "moderate", "severe"))
        assert b.classify(abs(-1.5)) == "normal"
        assert b.classify(abs(-2.5)) == "mild"
        assert b.classify(abs(3.5)) == "moderate"
        assert b.classify(abs(-5.0)) == "severe"


class TestComputeWindowStats:
    def test_returns_error_on_empty_input(self) -> None:
        result = compute_window_stats(
            pd.DataFrame({"date": [], "value": []}),
            target_date=None,
            window_years=5,
        )
        assert isinstance(result, dict)
        assert "error" in result

    def test_picks_latest_when_target_none(self) -> None:
        df = _series(
            ["2024-01-01", "2024-06-01", "2024-12-01"],
            [100.0, 110.0, 120.0],
        )
        result = compute_window_stats(df, target_date=None, window_years=5)
        assert isinstance(result, WindowStats)
        assert result.target_date == "2024-12-01"
        assert result.value == 120.0

    def test_picks_target_date_or_before(self) -> None:
        df = _series(
            ["2024-01-01", "2024-06-01", "2024-12-01"],
            [100.0, 110.0, 120.0],
        )
        result = compute_window_stats(df, target_date="2024-08-15", window_years=5)
        assert isinstance(result, WindowStats)
        assert result.target_date == "2024-06-01"
        assert result.value == 110.0

    def test_returns_error_when_target_before_first_obs(self) -> None:
        df = _series(["2024-01-01"], [100.0])
        result = compute_window_stats(df, target_date="2023-01-01", window_years=5)
        assert isinstance(result, dict)
        assert "error" in result

    def test_percentile_calculation(self) -> None:
        # 10 evenly-spaced values 1..10 over 10 years; target = 5 should be P50
        dates = [f"{2015+i}-06-01" for i in range(10)]
        values = [float(i + 1) for i in range(10)]
        df = _series(dates, values)
        result = compute_window_stats(df, target_date=None, window_years=20)
        assert isinstance(result, WindowStats)
        # Target is last value (10) → percentile 100
        assert result.percentile == 100.0
        assert result.min == 1.0
        assert result.max == 10.0
        assert result.n_obs == 10

    def test_window_truncates_to_n_years(self) -> None:
        # 10 yearly observations; window=3 should pick last 3
        dates = [f"{2015+i}-06-01" for i in range(10)]
        values = [float(i + 1) for i in range(10)]
        df = _series(dates, values)
        result = compute_window_stats(df, target_date=None, window_years=3)
        assert isinstance(result, WindowStats)
        # Last value is 2024-06-01 = 10.0, window cutoff is 2021-06-01
        # So window contains 2021-06=7, 2022-06=8, 2023-06=9, 2024-06=10
        assert result.n_obs == 4
        assert result.min == 7.0
        assert result.max == 10.0

    def test_drops_nan_values(self) -> None:
        df = pd.DataFrame({
            "date": ["2024-01-01", "2024-06-01", "2024-12-01"],
            "value": [100.0, None, 120.0],
        })
        result = compute_window_stats(df, target_date=None, window_years=5)
        assert isinstance(result, WindowStats)
        assert result.n_obs == 2
        assert result.value == 120.0

    def test_supports_custom_value_col(self) -> None:
        df = pd.DataFrame({
            "date": ["2024-01-01", "2024-06-01"],
            "basis_brl": [10.0, 12.0],
        })
        result = compute_window_stats(
            df,
            value_col="basis_brl",
            target_date=None,
            window_years=5,
        )
        assert isinstance(result, WindowStats)
        assert result.value == 12.0

    def test_as_dict_returns_all_fields(self) -> None:
        df = _series(["2024-01-01", "2024-12-01"], [100.0, 120.0])
        result = compute_window_stats(df, target_date=None, window_years=5)
        assert isinstance(result, WindowStats)
        d = result.as_dict()
        assert set(d.keys()) >= {
            "target_date", "value", "percentile",
            "n_obs", "mean", "p25", "p50", "p75", "min", "max",
        }
