"""Tests for backfill resume capability.

Verifies that:
1. Backfill saves data and resume skips already-covered dates
2. Expanding the date range only fetches new dates
3. Interrupted backfill preserves checkpointed data
4. generate_uncovered_dates correctly filters existing dates
"""

import shutil
import logging
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from noticiasagricolas_etl.backfill import (
    generate_backfill_dates,
    generate_uncovered_dates,
    get_covered_dates,
)
from noticiasagricolas_etl.models import CatalogEntry, PageType, PriceRecord
from noticiasagricolas_etl.storage import read_parquet, upsert, write_parquet, records_to_df

# Use a temp directory for all test data to avoid polluting real data
TEST_DATA_DIR = Path("/tmp/na_etl_test_resume")


def _make_entry(slug="test-indicator", commodity="test-commodity"):
    return CatalogEntry(
        commodity=commodity,
        slug=slug,
        name="Test Indicator",
        page_type=PageType.INDICATOR,
        unit="R$",
        has_date_nav=True,
        enabled=True,
    )


def _make_record(d: date, slug="test-indicator", commodity="test-commodity", value=100.0):
    return PriceRecord(
        date=d,
        commodity=commodity,
        indicator=slug,
        indicator_name="Test Indicator",
        location=None,
        contract_month=None,
        column_name="preco",
        value=value,
        value_raw=f"{value:.2f}".replace(".", ","),
        unit="R$",
    )


@pytest.fixture(autouse=True)
def temp_data_dirs(tmp_path, monkeypatch):
    """Redirect all storage to a temp directory for each test."""
    parquet_dir = tmp_path / "parquet"
    csv_dir = tmp_path / "csv"
    state_dir = tmp_path / "state"
    parquet_dir.mkdir()
    csv_dir.mkdir()
    state_dir.mkdir()

    monkeypatch.setattr("noticiasagricolas_etl.storage.PARQUET_DIR", parquet_dir)
    monkeypatch.setattr("noticiasagricolas_etl.storage.CSV_DIR", csv_dir)
    monkeypatch.setattr("noticiasagricolas_etl.backfill.read_parquet",
                        lambda c: _read_parquet_from(parquet_dir, c))
    monkeypatch.setattr("noticiasagricolas_etl.state.STATE_DIR", state_dir)

    return {"parquet": parquet_dir, "csv": csv_dir, "state": state_dir}


def _read_parquet_from(parquet_dir, commodity):
    """Read parquet from test directory."""
    import pyarrow.parquet as pq
    from noticiasagricolas_etl.storage import SCHEMA
    path = parquet_dir / f"commodity={commodity}" / "data.parquet"
    if not path.exists():
        return pd.DataFrame(columns=[f.name for f in SCHEMA])
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


# =============================================================================
# Unit tests for date generation with coverage filtering
# =============================================================================


class TestGenerateBackfillDates:
    def test_generates_business_days_only(self):
        dates = generate_backfill_dates(date(2024, 1, 1), date(2024, 1, 7))
        # Mon-Fri = 5 business days
        assert len(dates) == 5
        assert dates[0] == date(2024, 1, 1)  # Monday
        assert dates[-1] == date(2024, 1, 5)  # Friday
        # No weekend days
        for d in dates:
            assert d.weekday() < 5

    def test_empty_range(self):
        # Saturday to Sunday
        dates = generate_backfill_dates(date(2024, 1, 6), date(2024, 1, 7))
        assert dates == []


class TestGetCoveredDates:
    def test_empty_parquet_returns_empty_set(self):
        covered = get_covered_dates("nonexistent", "some-slug")
        assert covered == set()

    def test_returns_dates_for_matching_indicator(self, temp_data_dirs):
        # Write some records to parquet
        records = [
            _make_record(date(2024, 1, 2)),
            _make_record(date(2024, 1, 3)),
        ]
        upsert("test-commodity", records)

        covered = get_covered_dates("test-commodity", "test-indicator")
        assert covered == {date(2024, 1, 2), date(2024, 1, 3)}

    def test_ignores_other_indicators(self, temp_data_dirs):
        records = [
            _make_record(date(2024, 1, 2), slug="other-indicator"),
        ]
        upsert("test-commodity", records)

        covered = get_covered_dates("test-commodity", "test-indicator")
        assert covered == set()


class TestGenerateUncoveredDates:
    def test_all_uncovered_when_no_data(self):
        uncovered = generate_uncovered_dates(
            "test-commodity", "test-indicator",
            date(2024, 1, 1), date(2024, 1, 5),  # Mon-Fri
        )
        assert len(uncovered) == 5

    def test_filters_out_covered_dates(self, temp_data_dirs):
        # Pre-populate 2 dates
        records = [
            _make_record(date(2024, 1, 2)),
            _make_record(date(2024, 1, 3)),
        ]
        upsert("test-commodity", records)

        uncovered = generate_uncovered_dates(
            "test-commodity", "test-indicator",
            date(2024, 1, 1), date(2024, 1, 5),  # Mon-Fri = 5 bdays
        )
        # Should only need Mon, Thu, Fri
        assert date(2024, 1, 2) not in uncovered
        assert date(2024, 1, 3) not in uncovered
        assert len(uncovered) == 3

    def test_returns_empty_when_all_covered(self, temp_data_dirs):
        # Pre-populate all 5 business days
        records = [_make_record(date(2024, 1, d)) for d in [1, 2, 3, 4, 5]]
        upsert("test-commodity", records)

        uncovered = generate_uncovered_dates(
            "test-commodity", "test-indicator",
            date(2024, 1, 1), date(2024, 1, 5),
        )
        assert uncovered == []


# =============================================================================
# Integration tests for pipeline.backfill() with mocked HTTP
# =============================================================================


def _mock_process_entry(scraper, entry, target_date):
    """Mock _process_entry that returns deterministic records without HTTP."""
    if target_date is None:
        return []
    # Simulate holidays: return empty for weekday == 0 (Monday) to test empty handling
    return [
        PriceRecord(
            date=target_date,
            commodity=entry.commodity,
            indicator=entry.slug,
            indicator_name=entry.name,
            location=None,
            contract_month=None,
            column_name="preco",
            value=100.0 + target_date.day,
            value_raw=f"{100.0 + target_date.day:.2f}".replace(".", ","),
            unit="R$",
        ),
        PriceRecord(
            date=target_date,
            commodity=entry.commodity,
            indicator=entry.slug,
            indicator_name=entry.name,
            location=None,
            contract_month=None,
            column_name="variacao_pct",
            value=0.5,
            value_raw="0,50",
            unit="%",
        ),
    ]


class TestBackfillResume:
    """Integration tests: mock HTTP, real Parquet I/O."""

    def _run_backfill(self, slug="test-indicator", commodity="test-commodity",
                      start_date=None, end_date=None, resume=True):
        """Run backfill with mocked catalog and HTTP."""
        entry = _make_entry(slug=slug, commodity=commodity)

        with patch("noticiasagricolas_etl.pipeline.load_catalog") as mock_catalog, \
             patch("noticiasagricolas_etl.pipeline.get_entry_by_slug") as mock_get_slug, \
             patch("noticiasagricolas_etl.pipeline._process_entry", side_effect=_mock_process_entry) as mock_process, \
             patch("noticiasagricolas_etl.pipeline.Scraper"):

            mock_catalog.return_value = [entry]
            mock_get_slug.return_value = entry

            from noticiasagricolas_etl.pipeline import backfill
            backfill(
                slug=slug,
                start_date=start_date or date(2024, 1, 1),
                end_date=end_date or date(2024, 1, 12),  # 2 weeks = 10 bdays
                delay=0,
                resume=resume,
            )
            return mock_process

    def test_first_run_fetches_all_dates(self, temp_data_dirs):
        mock_process = self._run_backfill()

        # 10 business days: Jan 1-5 + Jan 8-12
        assert mock_process.call_count == 10

        # Verify data was written
        df = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        assert len(df) == 20  # 10 dates × 2 records each
        assert df["date"].nunique() == 10

    def test_resume_skips_all_covered_dates(self, temp_data_dirs):
        """Run twice with same range — second run should make ZERO HTTP requests."""
        # First run
        self._run_backfill()

        # Verify first run saved data
        df = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        assert len(df) == 20

        # Second run — should skip everything
        mock_process = self._run_backfill(resume=True)
        assert mock_process.call_count == 0  # ZERO requests!

        # Data unchanged
        df = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        assert len(df) == 20

    def test_resume_fetches_only_new_dates(self, temp_data_dirs):
        """Run for week 1, then expand to weeks 1+2 — should only fetch week 2."""
        # First run: Jan 1-5 (5 business days)
        self._run_backfill(start_date=date(2024, 1, 1), end_date=date(2024, 1, 5))

        df1 = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        assert df1["date"].nunique() == 5

        # Second run: Jan 1-12 (10 business days) — should only fetch Jan 8-12
        mock_process = self._run_backfill(
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 12), resume=True,
        )
        assert mock_process.call_count == 5  # only the 5 new dates

        # Should now have all 10 dates
        df2 = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        assert df2["date"].nunique() == 10

    def test_no_resume_refetches_everything(self, temp_data_dirs):
        """With resume=False, all dates are re-fetched."""
        # First run
        self._run_backfill()

        # Second run without resume
        mock_process = self._run_backfill(resume=False)
        assert mock_process.call_count == 10  # all 10 dates refetched

    def test_different_indicators_independent(self, temp_data_dirs):
        """Backfilling indicator A doesn't affect indicator B's resume state."""
        # Backfill indicator A
        self._run_backfill(slug="indicator-a")

        # Backfill indicator B — should still need all dates
        mock_process = self._run_backfill(slug="indicator-b")
        assert mock_process.call_count == 10  # full fetch for B

    def test_checkpoint_preserves_data_on_interruption(self, temp_data_dirs):
        """Simulate interruption after batch save — prior data survives."""
        call_count = 0

        def _process_with_crash(scraper, entry, target_date):
            nonlocal call_count
            call_count += 1
            if call_count > 55:  # crash after 55 dates (past the first batch save at 50)
                raise KeyboardInterrupt("simulated crash")
            return _mock_process_entry(scraper, entry, target_date)

        entry = _make_entry()

        with patch("noticiasagricolas_etl.pipeline.load_catalog") as mock_catalog, \
             patch("noticiasagricolas_etl.pipeline.get_entry_by_slug") as mock_get_slug, \
             patch("noticiasagricolas_etl.pipeline._process_entry", side_effect=_process_with_crash), \
             patch("noticiasagricolas_etl.pipeline.Scraper"):

            mock_catalog.return_value = [entry]
            mock_get_slug.return_value = entry

            from noticiasagricolas_etl.pipeline import backfill

            with pytest.raises(KeyboardInterrupt):
                backfill(
                    slug="test-indicator",
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 6, 30),  # ~130 business days
                    delay=0,
                    resume=False,
                )

        # The first batch of 50 should have been saved before the crash
        df = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        assert len(df) == 100  # 50 dates × 2 records each (batch saved at date 50)

        # Resume should skip the 50 saved dates
        remaining_mock = self._run_backfill(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            resume=True,
        )

        # Should have fetched the remaining ~80 dates (130 total - 50 saved)
        df_final = _read_parquet_from(temp_data_dirs["parquet"], "test-commodity")
        total_bdays = len(generate_backfill_dates(date(2024, 1, 1), date(2024, 6, 30)))
        assert df_final["date"].nunique() == total_bdays
        assert remaining_mock.call_count == total_bdays - 50


# =============================================================================
# Live integration test (small, uses real HTTP)
# =============================================================================


@pytest.mark.live
class TestBackfillResumeLive:
    """Live tests that hit the real website. Run with: pytest -m live"""

    def test_live_resume_skips_covered(self, temp_data_dirs):
        """Fetch 3 dates, then re-run — second run should be instant."""
        from noticiasagricolas_etl.pipeline import backfill
        from noticiasagricolas_etl.scraper import Scraper

        # Patch catalog to return just one indicator
        entry = CatalogEntry(
            commodity="soja",
            slug="soja-indicador-cepea-esalq-porto-paranagua",
            name="Soja Indicador CEPEA",
            page_type=PageType.INDICATOR,
            unit="R$",
            has_date_nav=True,
            enabled=True,
        )

        fetch_count = 0
        original_fetch = Scraper.fetch

        def counting_fetch(self, url):
            nonlocal fetch_count
            fetch_count += 1
            return original_fetch(self, url)

        with patch("noticiasagricolas_etl.pipeline.load_catalog", return_value=[entry]), \
             patch("noticiasagricolas_etl.pipeline.get_entry_by_slug", return_value=entry), \
             patch.object(Scraper, "fetch", counting_fetch):

            # First run: 3 business days
            backfill(
                slug="soja-indicador-cepea-esalq-porto-paranagua",
                start_date=date(2024, 12, 2),
                end_date=date(2024, 12, 4),  # Mon-Wed = 3 bdays
                delay=1.0,
                resume=True,
            )

        assert fetch_count == 3
        df = _read_parquet_from(temp_data_dirs["parquet"], "soja")
        first_count = len(df)
        assert first_count > 0

        # Second run: same range, should make 0 requests
        fetch_count = 0
        with patch("noticiasagricolas_etl.pipeline.load_catalog", return_value=[entry]), \
             patch("noticiasagricolas_etl.pipeline.get_entry_by_slug", return_value=entry), \
             patch.object(Scraper, "fetch", counting_fetch):

            backfill(
                slug="soja-indicador-cepea-esalq-porto-paranagua",
                start_date=date(2024, 12, 2),
                end_date=date(2024, 12, 4),
                delay=1.0,
                resume=True,
            )

        assert fetch_count == 0  # ZERO requests on resume!

        # Data unchanged
        df = _read_parquet_from(temp_data_dirs["parquet"], "soja")
        assert len(df) == first_count
