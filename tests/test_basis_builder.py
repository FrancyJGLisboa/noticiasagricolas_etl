"""Tests for basis_builder with synthetic Parquet fixtures."""

from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from noticiasagricolas_etl.basis.calculator import (
    select_front_month as _select_front_month,
)
from noticiasagricolas_etl.basis.locations import (
    normalize_location as _normalize_location,
)
from noticiasagricolas_etl.basis.sources import (
    load_futures_prices as _load_futures_prices,
    load_physical_prices as _load_physical_prices,
    load_ptax as _load_ptax,
)
from noticiasagricolas_etl.basis_builder import build_all, build_pair
from noticiasagricolas_etl.basis_config import (
    BASIS_PAIRS,
    BU_PER_SC_CORN,
    BU_PER_SC_SOJA,
    BU_PER_SC_WHEAT,
    LB_PER_ARROBA,
    LB_PER_SC_COFFEE,
    BasisPairConfig,
    get_pairs,
)
from noticiasagricolas_etl.storage import SCHEMA


# ── Helpers ──────────────────────────────────────────────────────────────────

def _row(dt, commodity, indicator, indicator_name, location, contract_month,
         column_name, value, unit, measure, currency, unit_std,
         price_basis, contract, state, market_type):
    return {
        "date": dt, "commodity": commodity, "indicator": indicator,
        "indicator_name": indicator_name, "location": location,
        "contract_month": contract_month, "column_name": column_name,
        "value": value, "value_raw": str(value) if value else "",
        "unit": unit, "measure": measure, "currency": currency,
        "unit_std": unit_std, "price_basis": price_basis,
        "contract": contract, "state": state, "market_type": market_type,
    }


def _write_parquet(parquet_dir, commodity, rows):
    path = parquet_dir / f"commodity={commodity}"
    path.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, path / "data.parquet")


@pytest.fixture
def setup_dirs(tmp_path, monkeypatch):
    """Set up temp Parquet dirs and monkeypatch config paths."""
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    basis_dir = tmp_path / "parquet_basis"
    basis_dir.mkdir()
    monkeypatch.setattr("noticiasagricolas_etl.config.PARQUET_DIR", parquet_dir)
    monkeypatch.setattr("noticiasagricolas_etl.config.PARQUET_BASIS_DIR", basis_dir)
    # Patch the names where they're actually looked up at call-time
    monkeypatch.setattr("noticiasagricolas_etl.basis.sources.PARQUET_DIR", parquet_dir)
    monkeypatch.setattr("noticiasagricolas_etl.basis.output.PARQUET_BASIS_DIR", basis_dir)
    return parquet_dir, basis_dir


# ── Front-month detection ────────────────────────────────────────────────────

class TestFrontMonthDetection:
    def test_selects_nearest_contract(self):
        """Normal case: picks smallest contract >= date's month."""
        df = pd.DataFrame([
            {"date": date(2025, 3, 15), "contract": "2025-03", "futures_price_raw": 100.0},
            {"date": date(2025, 3, 15), "contract": "2025-05", "futures_price_raw": 102.0},
            {"date": date(2025, 3, 15), "contract": "2025-07", "futures_price_raw": 104.0},
        ])
        result = _select_front_month(df)
        assert len(result) == 1
        assert result.iloc[0]["futures_contract"] == "2025-03"
        assert result.iloc[0]["futures_price_raw"] == 100.0

    def test_month_rollover(self):
        """When current month contract doesn't exist, picks next available."""
        df = pd.DataFrame([
            {"date": date(2025, 4, 10), "contract": "2025-05", "futures_price_raw": 102.0},
            {"date": date(2025, 4, 10), "contract": "2025-07", "futures_price_raw": 104.0},
        ])
        result = _select_front_month(df)
        assert len(result) == 1
        assert result.iloc[0]["futures_contract"] == "2025-05"

    def test_expired_contracts_fallback(self):
        """All contracts expired — falls back to most recent."""
        df = pd.DataFrame([
            {"date": date(2025, 6, 15), "contract": "2025-03", "futures_price_raw": 100.0},
            {"date": date(2025, 6, 15), "contract": "2025-05", "futures_price_raw": 102.0},
        ])
        result = _select_front_month(df)
        assert len(result) == 1
        assert result.iloc[0]["futures_contract"] == "2025-05"

    def test_multiple_dates(self):
        """Each date gets its own front-month selection."""
        df = pd.DataFrame([
            {"date": date(2025, 3, 15), "contract": "2025-03", "futures_price_raw": 100.0},
            {"date": date(2025, 3, 15), "contract": "2025-05", "futures_price_raw": 102.0},
            {"date": date(2025, 5, 10), "contract": "2025-03", "futures_price_raw": 99.0},
            {"date": date(2025, 5, 10), "contract": "2025-05", "futures_price_raw": 103.0},
        ])
        result = _select_front_month(df)
        assert len(result) == 2
        r = result.set_index("date")
        assert r.loc[date(2025, 3, 15), "futures_contract"] == "2025-03"
        assert r.loc[date(2025, 5, 10), "futures_contract"] == "2025-05"

    def test_empty_input(self):
        df = pd.DataFrame(columns=["date", "contract", "futures_price_raw"])
        result = _select_front_month(df)
        assert result.empty


# ── PTAX forward-fill ────────────────────────────────────────────────────────

class TestPTAXLoading:
    def test_ptax_ffill(self, setup_dirs):
        """Weekend gap correctly carries Friday's rate."""
        parquet_dir, _ = setup_dirs
        _write_parquet(parquet_dir, "mercado-financeiro", [
            _row(date(2025, 1, 3), "mercado-financeiro", "cambio-ptax", "PTAX",
                 "Dólar", None, "preco", 5.19, "R$/US$", "price", "BRL", "usd",
                 "spot", None, None, "indicator"),
            # No data for Sat 1/4, Sun 1/5
            _row(date(2025, 1, 6), "mercado-financeiro", "cambio-ptax", "PTAX",
                 "Dólar", None, "preco", 5.21, "R$/US$", "price", "BRL", "usd",
                 "spot", None, None, "indicator"),
        ])
        import duckdb
        conn = duckdb.connect(":memory:")
        ptax = _load_ptax(conn)
        conn.close()

        # Should have all dates from Jan 3 to Jan 6
        assert len(ptax) == 4  # Jan 3, 4, 5, 6
        # Weekend dates should be forward-filled with Friday's value
        sat = ptax[ptax["date"] == date(2025, 1, 4)]
        assert len(sat) == 1
        assert sat.iloc[0]["ptax"] == 5.19
        sun = ptax[ptax["date"] == date(2025, 1, 5)]
        assert len(sun) == 1
        assert sun.iloc[0]["ptax"] == 5.19
        # Monday has its own value
        mon = ptax[ptax["date"] == date(2025, 1, 6)]
        assert mon.iloc[0]["ptax"] == 5.21

    def test_ptax_filters_dolar_only(self, setup_dirs):
        """Only Dólar rows are loaded, not Euro."""
        parquet_dir, _ = setup_dirs
        _write_parquet(parquet_dir, "mercado-financeiro", [
            _row(date(2025, 1, 3), "mercado-financeiro", "cambio-ptax", "PTAX",
                 "Dólar", None, "preco", 5.19, "R$/US$", "price", "BRL", "usd",
                 "spot", None, None, "indicator"),
            _row(date(2025, 1, 3), "mercado-financeiro", "cambio-ptax", "PTAX",
                 "Euro", None, "preco", 6.18, "R$/€", "price", "BRL", "eur",
                 "spot", None, None, "indicator"),
        ])
        import duckdb
        conn = duckdb.connect(":memory:")
        ptax = _load_ptax(conn)
        conn.close()

        assert len(ptax) == 1
        assert ptax.iloc[0]["ptax"] == 5.19

    def test_ptax_missing_parquet(self, setup_dirs):
        """Returns empty when no mercado-financeiro Parquet exists."""
        import duckdb
        conn = duckdb.connect(":memory:")
        ptax = _load_ptax(conn)
        conn.close()
        assert ptax.empty


# ── Conversion accuracy ──────────────────────────────────────────────────────

class TestConversionAccuracy:
    def test_soja_b3_ptax_only(self):
        """Soja B3: US$/sc -> BRL/sc = fut * PTAX."""
        pair = [p for p in BASIS_PAIRS if p.label == "soja-b3"][0]
        result = pair.convert_futures(24.75, 5.19)
        assert abs(result - 24.75 * 5.19) < 0.01

    def test_soja_cbot_unit_and_ptax(self):
        """Soja CBOT: US$/bu -> BRL/sc = fut * bu/sc * PTAX."""
        pair = [p for p in BASIS_PAIRS if p.label == "soja-cbot"][0]
        result = pair.convert_futures(11.11, 5.19)
        expected = 11.11 * BU_PER_SC_SOJA * 5.19
        assert abs(result - expected) < 0.01

    def test_milho_b3_direct(self):
        """Milho B3: R$/sc -> R$/sc = fut (no conversion)."""
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        result = pair.convert_futures(62.5, 0.0)
        assert result == 62.5

    def test_milho_cbot_unit_and_ptax(self):
        """Milho CBOT: US$/bu -> BRL/sc = fut * bu/sc * PTAX."""
        pair = [p for p in BASIS_PAIRS if p.label == "milho-cbot"][0]
        result = pair.convert_futures(4.50, 5.19)
        expected = 4.50 * BU_PER_SC_CORN * 5.19
        assert abs(result - expected) < 0.01

    def test_trigo_cbot(self):
        """Trigo CBOT: US$/bu -> BRL/sc."""
        pair = [p for p in BASIS_PAIRS if p.label == "trigo-cbot"][0]
        result = pair.convert_futures(6.00, 5.00)
        expected = 6.00 * BU_PER_SC_WHEAT * 5.00
        assert abs(result - expected) < 0.01

    def test_algodao_nybot_cents(self):
        """Algodao NYBOT: US¢/lb -> BRL/@ = fut * lb/@ / 100 * PTAX."""
        pair = [p for p in BASIS_PAIRS if p.label == "algodao-nybot"][0]
        result = pair.convert_futures(85.0, 5.00)
        expected = 85.0 * LB_PER_ARROBA / 100 * 5.00
        assert abs(result - expected) < 0.01

    def test_cafe_b3_ptax(self):
        """Cafe B3: US$/sc -> BRL/sc = fut * PTAX."""
        pair = [p for p in BASIS_PAIRS if p.label == "cafe-b3"][0]
        result = pair.convert_futures(300.0, 5.00)
        assert abs(result - 1500.0) < 0.01

    def test_cafe_nybot_preconverted(self):
        """Cafe NYBOT: source pre-converts to R$/sc, no conversion needed."""
        pair = [p for p in BASIS_PAIRS if p.label == "cafe-nybot"][0]
        assert pair.needs_ptax is False
        result = pair.convert_futures(2488.19, 0.0)
        assert result == 2488.19  # identity — already in R$/sc

    def test_boi_gordo_direct(self):
        """Boi Gordo B3: R$/@ -> R$/@ (direct)."""
        pair = [p for p in BASIS_PAIRS if p.label == "boi-gordo-b3"][0]
        result = pair.convert_futures(320.0, 0.0)
        assert result == 320.0


# ── Full build_pair pipeline ─────────────────────────────────────────────────

class TestBuildPair:
    @pytest.fixture
    def synthetic_data(self, setup_dirs):
        """Create synthetic Parquet for milho B3 (simplest — no PTAX)."""
        parquet_dir, basis_dir = setup_dirs
        d1 = date(2025, 3, 10)
        d2 = date(2025, 3, 11)

        _write_parquet(parquet_dir, "milho", [
            # Physical prices
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Dourados/MS", None, "preco", 52.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "MS", "physical"),
            _row(d2, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 59.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            # Futures prices — two contracts
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 62.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mai/25", "ajuste", 64.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-05", None, "b3"),
            _row(d2, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 63.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
            _row(d2, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mai/25", "ajuste", 65.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-05", None, "b3"),
        ])
        return parquet_dir, basis_dir

    def test_milho_b3_basis(self, synthetic_data):
        """Milho B3 direct pair: basis = physical - futures (no conversion)."""
        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()

        # d1: Campinas 58-62=-4, Dourados 52-62=-10
        # d2: Campinas 59-63=-4
        assert len(result) == 3

        campinas_d1 = result[(result["date"] == date(2025, 3, 10)) &
                             (result["location"] == "Campinas/SP")]
        assert len(campinas_d1) == 1
        assert campinas_d1.iloc[0]["basis_brl"] == pytest.approx(-4.0)
        assert campinas_d1.iloc[0]["futures_contract"] == "2025-03"
        assert campinas_d1.iloc[0]["futures_price_raw"] == 62.0
        assert campinas_d1.iloc[0]["futures_price_brl"] == 62.0

        dourados_d1 = result[(result["date"] == date(2025, 3, 10)) &
                             (result["location"] == "Dourados/MS")]
        assert dourados_d1.iloc[0]["basis_brl"] == pytest.approx(-10.0)

        # PTAX should be NaN for direct pairs
        assert np.isnan(campinas_d1.iloc[0]["ptax"])
        # basis_usd should be NaN (no PTAX)
        assert np.isnan(campinas_d1.iloc[0]["basis_usd"])

    def test_basis_pct_computation(self, synthetic_data):
        """Verify basis_pct = (basis_brl / futures_price_brl) * 100."""
        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()

        for _, row in result.iterrows():
            expected_pct = (row["basis_brl"] / row["futures_price_brl"]) * 100
            assert row["basis_pct"] == pytest.approx(expected_pct, abs=0.001)


class TestBuildPairWithPTAX:
    @pytest.fixture
    def soja_data(self, setup_dirs):
        """Create synthetic soja B3 data requiring PTAX."""
        parquet_dir, basis_dir = setup_dirs
        d1 = date(2025, 3, 10)

        _write_parquet(parquet_dir, "soja", [
            # Physical
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja Fisico",
                 "Cascavel/PR", None, "preco", 121.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "PR", "physical"),
            # Futures B3
            _row(d1, "soja", "soja-b3-pregao-regular", "Soja B3",
                 None, "Mai/25", "ajuste", 24.75, "US$/sc60kg", "price", "USD",
                 "sc60kg", "futures", "2025-05", None, "b3"),
            # Futures CBOT
            _row(d1, "soja", "soja-bolsa-de-chicago-cme-group", "Soja CBOT",
                 None, "Mai/25", "ajuste", 11.11, "US$/bu", "price", "USD",
                 "bu", "futures", "2025-05", None, "cme"),
        ])
        _write_parquet(parquet_dir, "mercado-financeiro", [
            _row(d1, "mercado-financeiro", "cambio-ptax", "PTAX",
                 "Dólar", None, "preco", 5.19, "R$/US$", "price", "BRL", "usd",
                 "spot", None, None, "indicator"),
        ])
        return parquet_dir, basis_dir

    def test_soja_b3_with_ptax(self, soja_data):
        """Soja B3: futures_brl = 24.75 * 5.19, basis = 121 - 128.45."""
        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "soja-b3"][0]
        ptax = _load_ptax(conn)

        result = build_pair(conn, pair, ptax)
        conn.close()

        assert len(result) == 1
        row = result.iloc[0]
        expected_fut_brl = 24.75 * 5.19
        assert row["futures_price_brl"] == pytest.approx(expected_fut_brl, abs=0.01)
        assert row["basis_brl"] == pytest.approx(121.0 - expected_fut_brl, abs=0.01)
        assert row["ptax"] == pytest.approx(5.19)
        assert row["basis_usd"] == pytest.approx(row["basis_brl"] / 5.19, abs=0.01)

    def test_soja_cbot_with_unit_conversion(self, soja_data):
        """Soja CBOT: futures_brl = 11.11 * 2.2046 * 5.19."""
        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "soja-cbot"][0]
        ptax = _load_ptax(conn)

        result = build_pair(conn, pair, ptax)
        conn.close()

        assert len(result) == 1
        row = result.iloc[0]
        expected_fut_brl = 11.11 * BU_PER_SC_SOJA * 5.19
        assert row["futures_price_brl"] == pytest.approx(expected_fut_brl, abs=0.01)
        assert row["basis_brl"] == pytest.approx(121.0 - expected_fut_brl, abs=0.01)


# ── Division by zero ─────────────────────────────────────────────────────────

class TestDivisionByZero:
    def test_basis_pct_nan_when_futures_zero(self, setup_dirs):
        """When futures_price_brl = 0, basis_pct should be NaN."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)

        _write_parquet(parquet_dir, "milho", [
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 0.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()

        assert len(result) == 1
        assert np.isnan(result.iloc[0]["basis_pct"])


# ── Missing data (inner join skips) ──────────────────────────────────────────

class TestMissingData:
    def test_no_physical_data(self, setup_dirs):
        """build_pair returns empty when no physical data exists."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "milho", [
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 62.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()
        assert result.empty

    def test_no_futures_data(self, setup_dirs):
        """build_pair returns empty when no futures data exists."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "milho", [
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()
        assert result.empty

    def test_no_overlapping_dates(self, setup_dirs):
        """build_pair returns empty when physical and futures have no common dates."""
        parquet_dir, _ = setup_dirs
        _write_parquet(parquet_dir, "milho", [
            _row(date(2025, 3, 10), "milho",
                 "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            _row(date(2025, 3, 11), "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 62.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "milho-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()
        assert result.empty

    def test_missing_ptax_for_ptax_pair(self, setup_dirs):
        """Pair needing PTAX returns empty when PTAX data is missing."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "soja", [
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja Fisico",
                 "Cascavel/PR", None, "preco", 121.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "PR", "physical"),
            _row(d1, "soja", "soja-b3-pregao-regular", "Soja B3",
                 None, "Mai/25", "ajuste", 24.75, "US$/sc60kg", "price", "USD",
                 "sc60kg", "futures", "2025-05", None, "b3"),
        ])
        # No mercado-financeiro parquet -> no PTAX

        import duckdb
        conn = duckdb.connect(":memory:")
        pair = [p for p in BASIS_PAIRS if p.label == "soja-b3"][0]
        ptax = pd.DataFrame(columns=["date", "ptax"])

        result = build_pair(conn, pair, ptax)
        conn.close()
        assert result.empty


# ── build_all ────────────────────────────────────────────────────────────────

class TestBuildAll:
    def test_skips_missing_parquet(self, setup_dirs):
        """build_all skips cafe/boi-gordo when Parquet doesn't exist."""
        parquet_dir, basis_dir = setup_dirs
        d1 = date(2025, 3, 10)

        _write_parquet(parquet_dir, "milho", [
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 62.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
        ])

        summary = build_all()

        # cafe and boi-gordo should be skipped (0 rows)
        assert summary.get("cafe-b3", 0) == 0
        assert summary.get("cafe-nybot", 0) == 0
        assert summary.get("boi-gordo-b3", 0) == 0
        # milho-b3 should have data
        assert summary["milho-b3"] > 0

    def test_build_all_with_commodity_filter(self, setup_dirs):
        """build_all with commodity filter only builds matching pairs."""
        parquet_dir, basis_dir = setup_dirs
        d1 = date(2025, 3, 10)

        _write_parquet(parquet_dir, "milho", [
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 62.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
        ])
        _write_parquet(parquet_dir, "soja", [
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja Fisico",
                 "Cascavel/PR", None, "preco", 121.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "PR", "physical"),
        ])

        summary = build_all(commodities=["milho"])

        # Only milho pairs should be in summary
        assert "milho-b3" in summary
        assert "soja-b3" not in summary

    def test_writes_parquet_output(self, setup_dirs):
        """build_all writes Parquet files to parquet_basis directory."""
        parquet_dir, basis_dir = setup_dirs
        d1 = date(2025, 3, 10)

        _write_parquet(parquet_dir, "milho", [
            _row(d1, "milho", "milho-mercado-fisico-sindicatos-e-cooperativas", "Milho Fisico",
                 "Campinas/SP", None, "preco", 58.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "spot", None, "SP", "physical"),
            _row(d1, "milho", "milho-b3-prego-regular", "Milho B3",
                 None, "Mar/25", "ajuste", 62.0, "R$/sc60kg", "price", "BRL",
                 "sc60kg", "futures", "2025-03", None, "b3"),
        ])

        build_all(commodities=["milho"])

        output_path = basis_dir / "commodity=milho" / "data.parquet"
        assert output_path.exists()

        # Read back and verify
        df = pd.read_parquet(output_path)
        assert len(df) > 0
        assert "basis_brl" in df.columns


# ── Config helpers ───────────────────────────────────────────────────────────

class TestBasisConfig:
    def test_all_9_pairs_defined(self):
        assert len(BASIS_PAIRS) == 9

    def test_get_pairs_filter(self):
        soja_pairs = get_pairs(["soja"])
        assert len(soja_pairs) == 2
        assert all(p.commodity == "soja" for p in soja_pairs)

    def test_get_pairs_no_filter(self):
        assert get_pairs() == BASIS_PAIRS

    def test_unique_labels(self):
        labels = [p.label for p in BASIS_PAIRS]
        assert len(labels) == len(set(labels))

    def test_conversion_constants(self):
        assert abs(BU_PER_SC_SOJA - 2.2046) < 0.001
        assert abs(BU_PER_SC_CORN - 2.3621) < 0.001
        assert abs(BU_PER_SC_WHEAT - 2.2046) < 0.001
        assert abs(LB_PER_SC_COFFEE - 132.277) < 0.01
        assert abs(LB_PER_ARROBA - 33.069) < 0.01

    def test_physical_indicators_is_tuple(self):
        for p in BASIS_PAIRS:
            assert isinstance(p.physical_indicators, tuple)
            assert len(p.physical_indicators) >= 1

    def test_soja_has_two_physical_indicators(self):
        soja_pairs = get_pairs(["soja"])
        for p in soja_pairs:
            assert len(p.physical_indicators) == 2
            assert "soja-mercado-fisico-sindicatos-e-cooperativas" in p.physical_indicators
            assert "soja-mercado-fisico-ms" in p.physical_indicators


# ── Port location normalization ──────────────────────────────────────────────

class TestPortNormalization:
    def test_santos_variants(self):
        assert _normalize_location("Porto Santos/SP (Fev/Mar-2025) (Dellagro)") == "Porto Santos/SP"
        assert _normalize_location("Porto Santos/SP (disponível)") == "Porto Santos/SP"
        assert _normalize_location("Porto Santos/SP (Ago/Set/22)(Dellagro)") == "Porto Santos/SP"

    def test_paranagua_variants(self):
        assert _normalize_location("Porto Paranaguá (disponível) (Insoy Commodities)") == "Porto Paranaguá/PR"
        assert _normalize_location("Porto Paranaguá (Mar/21) (Insoy Commodities)") == "Porto Paranaguá/PR"
        assert _normalize_location("Porto Paranagua (Fev/22) (Insoy)") == "Porto Paranaguá/PR"

    def test_other_ports(self):
        assert _normalize_location("Porto de São Francisco do Sul/SC (disponível) (Belgrano Commodities Ltda)") == "Porto São Francisco do Sul/SC"
        assert _normalize_location("Porto Imbituba/SC (disponível) (Belgrano Commodities Ltda)") == "Porto Imbituba/SC"
        assert _normalize_location("Porto Rio Grande (Insoy Commodities)") == "Porto Rio Grande/RS"

    def test_bare_city_names(self):
        assert _normalize_location("Maringá") == "Maringá/PR"
        assert _normalize_location("Paranaguá") == "Paranaguá/PR"
        assert _normalize_location("Dourados") == "Dourados/MS"
        assert _normalize_location("Campo Grande") == "Campo Grande/MS"
        assert _normalize_location("Oeste da Bahia") == "Oeste da Bahia/BA"
        # Bare city with parenthetical suffix (AIBA cooperative)
        assert _normalize_location("Oeste da Bahia (AIBA)") == "Oeste da Bahia/BA"

    def test_broker_suffixes_stripped(self):
        assert _normalize_location("Ubiratã/PR (Coagru)") == "Ubiratã/PR"
        assert _normalize_location("Rio Verde/GO (Comigo)") == "Rio Verde/GO"
        assert _normalize_location("Rondonópolis/MT (Samir Rosa Assessoria Comercial)") == "Rondonópolis/MT"
        assert _normalize_location("Sorriso/MT (Sindicato) Transgênica Balcão") == "Sorriso/MT"
        assert _normalize_location("Eldorado/MS (Copagril") == "Eldorado/MS"

    def test_plain_locations_unchanged(self):
        assert _normalize_location("Campinas/SP") == "Campinas/SP"
        assert _normalize_location("Ubiratã/PR") == "Ubiratã/PR"

    def test_aggregation_averages_duplicates(self, setup_dirs):
        """Port variants on same date are averaged into one row."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "soja", [
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja Fisico",
                 "Porto Santos/SP (Fev/Mar-2025) (Dellagro)", None, "preco", 130.0,
                 "R$/sc60kg", "price", "BRL", "sc60kg", "spot", None, "SP", "physical"),
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja Fisico",
                 "Porto Santos/SP (disponível)", None, "preco", 132.0,
                 "R$/sc60kg", "price", "BRL", "sc60kg", "spot", None, "SP", "physical"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        result = _load_physical_prices(
            conn,
            ("soja-mercado-fisico-sindicatos-e-cooperativas",),
            "soja",
        )
        conn.close()

        assert len(result) == 1
        assert result.iloc[0]["location"] == "Porto Santos/SP"
        assert result.iloc[0]["state"] == "SP"
        assert result.iloc[0]["physical_price_brl"] == pytest.approx(131.0)  # average


# ── Multi-indicator loading ──────────────────────────────────────────────────

class TestMultiIndicator:
    def test_loads_from_two_indicators(self, setup_dirs):
        """Physical prices are loaded from multiple indicators and merged."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "soja", [
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja Fisico",
                 "Ubiratã/PR (Coagru)", None, "preco", 112.0,
                 "R$/sc60kg", "price", "BRL", "sc60kg", "spot", None, "PR", "physical"),
            _row(d1, "soja", "soja-mercado-fisico-ms", "Soja MS",
                 "Maringá", None, "preco", 115.0,
                 "R$/sc60kg", "price", "BRL", "sc60kg", "spot", None, None, "physical"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        result = _load_physical_prices(
            conn,
            ("soja-mercado-fisico-sindicatos-e-cooperativas", "soja-mercado-fisico-ms"),
            "soja",
        )
        conn.close()

        assert len(result) == 2
        locations = set(result["location"])
        assert "Ubiratã/PR" in locations  # broker suffix stripped
        assert "Maringá/PR" in locations  # bare city normalized

        maringa = result[result["location"] == "Maringá/PR"]
        assert maringa.iloc[0]["state"] == "PR"  # state extracted from normalized location

    def test_kg_locations_converted_to_arroba(self, setup_dirs):
        """Locations with (kg) in name are converted to R$/@ by ×15."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "boi-gordo", [
            _row(d1, "boi-gordo", "boi-gordo-scot-consultoria", "Boi Gordo",
                 "RS Oeste (kg)", None, "preco", 10.0,
                 "R$/kg", "price", "BRL", "kg", "spot", None, None, "physical"),
            _row(d1, "boi-gordo", "boi-gordo-scot-consultoria", "Boi Gordo",
                 "Goiânia/GO", None, "preco", 300.0,
                 "R$/@", "price", "BRL", "@", "spot", None, "GO", "physical"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        result = _load_physical_prices(conn, ("boi-gordo-scot-consultoria",), "boi-gordo")
        conn.close()

        rs = result[result["location"] == "RS Oeste"]
        assert len(rs) == 1
        assert rs.iloc[0]["physical_price_brl"] == pytest.approx(150.0)  # 10 * 15

        go = result[result["location"] == "Goiânia/GO"]
        assert go.iloc[0]["physical_price_brl"] == pytest.approx(300.0)  # unchanged

    def test_zero_prices_filtered(self, setup_dirs):
        """Rows with physical_price_brl = 0 are excluded."""
        parquet_dir, _ = setup_dirs
        d1 = date(2025, 3, 10)
        _write_parquet(parquet_dir, "soja", [
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja",
                 "Cascavel/PR", None, "preco", 0.0,
                 "R$/sc60kg", "price", "BRL", "sc60kg", "spot", None, "PR", "physical"),
            _row(d1, "soja", "soja-mercado-fisico-sindicatos-e-cooperativas", "Soja",
                 "Londrina/PR", None, "preco", 120.0,
                 "R$/sc60kg", "price", "BRL", "sc60kg", "spot", None, "PR", "physical"),
        ])

        import duckdb
        conn = duckdb.connect(":memory:")
        result = _load_physical_prices(conn, ("soja-mercado-fisico-sindicatos-e-cooperativas",), "soja")
        conn.close()

        assert len(result) == 1
        assert result.iloc[0]["location"] == "Londrina/PR"
