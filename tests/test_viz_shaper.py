"""Unit tests for viz.shaper — pure-DataFrame reshapes for chart inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from noticiasagricolas_etl.viz.shaper import (
    doy_envelope,
    weekly_zscore,
    windowed,
)


def _make_long(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """rows = [(date, location, value), ...]"""
    df = pd.DataFrame(rows, columns=["date", "location", "value"])
    df["date"] = pd.to_datetime(df["date"])
    return df


class TestWindowed:
    def test_filters_to_n_years_back_from_max_date(self) -> None:
        # max=2024-06-01, window=4 → cutoff=2020-06-01. The 2020 row sits exactly
        # on the cutoff and stays (>= boundary).
        df = _make_long([
            ("2018-06-01", "A", 1.0),
            ("2020-06-01", "A", 2.0),
            ("2024-06-01", "A", 3.0),
        ])
        out = windowed(df, window_years=4)
        assert len(out) == 2
        assert out["date"].min() == pd.Timestamp("2020-06-01")

    def test_returns_empty_when_input_empty(self) -> None:
        df = pd.DataFrame(columns=["date", "location", "value"])
        out = windowed(df, window_years=5)
        assert out.empty

    def test_explicit_today_anchor(self) -> None:
        # today=2021-12-31, window=2 → cutoff=2019-12-31. Only 2020 row passes.
        df = _make_long([
            ("2018-06-01", "A", 1.0),
            ("2020-06-01", "A", 2.0),
            ("2024-06-01", "A", 3.0),
        ])
        out = windowed(df, window_years=2, today=pd.Timestamp("2021-12-31"))
        assert len(out) == 1
        assert out["date"].min() == pd.Timestamp("2020-06-01")


class TestDoyEnvelope:
    def test_returns_366_rows_indexed_by_doy(self) -> None:
        # Two years of synthetic data
        dates = pd.date_range("2022-01-01", "2023-12-31", freq="D")
        df = pd.DataFrame({
            "date": dates,
            "value": np.arange(len(dates), dtype=float),
        })
        env = doy_envelope(df, window_years=5)
        assert len(env) == 366
        assert list(env.columns) == ["min", "p25", "p50", "p75", "max"]

    def test_quantiles_ordered_min_p25_p50_p75_max(self) -> None:
        # 3 past years × 7 consecutive days each; same value pattern. The 7-day
        # smoothing has enough neighbors to produce a non-NaN result.
        rows = []
        for year in (2021, 2022, 2023):
            for d in range(1, 8):  # Jun 1..7
                rows.append((f"{year}-06-{d:02d}", float(year - 2020) * 10.0 * d))
        df = pd.DataFrame(rows, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])
        env = doy_envelope(df, window_years=5, today=pd.Timestamp("2024-01-15"))
        # doy 152 = June 1 in non-leap years
        row = env.loc[152]
        assert row["min"] <= row["p25"] <= row["p50"] <= row["p75"] <= row["max"]

    def test_returns_empty_envelope_when_no_data(self) -> None:
        df = pd.DataFrame({"date": [], "value": []})
        env = doy_envelope(df, window_years=5)
        assert env.empty

    def test_excludes_current_year(self) -> None:
        # Past year (2022) has value 100; current year (2024) has value 999.
        # Envelope should reflect only 2022 (current year excluded).
        dates = list(pd.date_range("2022-01-01", "2022-12-31", freq="D"))
        dates += list(pd.date_range("2024-01-01", "2024-01-15", freq="D"))
        values = [100.0] * 365 + [999.0] * 15
        df = pd.DataFrame({"date": dates, "value": values})
        env = doy_envelope(df, window_years=5, today=pd.Timestamp("2024-01-15"))
        # doy 1 (Jan 1) — only 2022 contributes; envelope should be 100 (not 999)
        assert env.loc[1, "p50"] == 100.0


class TestWeeklyZscore:
    def test_returns_one_row_per_location_week_with_zscore(self) -> None:
        df = _make_long([
            ("2024-01-01", "A", 1.0),
            ("2024-01-08", "A", 2.0),
            ("2024-01-15", "A", 3.0),
            ("2024-01-22", "A", 4.0),
            ("2024-01-01", "B", 10.0),
            ("2024-01-08", "B", 20.0),
        ])
        out = weekly_zscore(df, window_years=5)
        assert {"location", "week", "value", "zscore"} <= set(out.columns)
        # Each (location, week) is unique
        assert len(out) == out[["location", "week"]].drop_duplicates().shape[0]

    def test_zscore_is_zero_when_constant(self) -> None:
        # std=0 → zscore should be NaN (per impl in original heatmap)
        df = _make_long([
            ("2024-01-01", "A", 5.0),
            ("2024-01-08", "A", 5.0),
            ("2024-01-15", "A", 5.0),
        ])
        out = weekly_zscore(df, window_years=5)
        assert out["zscore"].isna().all()

    def test_returns_empty_on_empty_input(self) -> None:
        df = pd.DataFrame(columns=["date", "location", "value"])
        out = weekly_zscore(df, window_years=5)
        assert out.empty

    def test_handles_multi_location_independently(self) -> None:
        # Location A: variable; Location B: constant
        df = _make_long([
            ("2024-01-01", "A", 1.0),
            ("2024-01-08", "A", 5.0),
            ("2024-01-15", "A", 9.0),
            ("2024-01-01", "B", 100.0),
            ("2024-01-08", "B", 100.0),
            ("2024-01-15", "B", 100.0),
        ])
        out = weekly_zscore(df, window_years=5)
        # A's z-scores are real numbers; B's are NaN (zero variance)
        a_scores = out[out["location"] == "A"]["zscore"]
        b_scores = out[out["location"] == "B"]["zscore"]
        assert not a_scores.isna().all()
        assert b_scores.isna().all()
