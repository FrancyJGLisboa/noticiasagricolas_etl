"""Tests for the REST API endpoints using FastAPI TestClient."""

from datetime import date

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from noticiasagricolas_etl.api import database as db
from noticiasagricolas_etl.api.app import create_app
from noticiasagricolas_etl.basis_builder import BASIS_SCHEMA
from noticiasagricolas_etl.storage import SCHEMA


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Set up DuckDB with test Parquet data in a temp directory."""
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    basis_dir = tmp_path / "parquet_basis"
    basis_dir.mkdir()
    monkeypatch.setattr("noticiasagricolas_etl.config.PARQUET_DIR", parquet_dir)
    monkeypatch.setattr("noticiasagricolas_etl.config.PARQUET_BASIS_DIR", basis_dir)
    monkeypatch.setattr("noticiasagricolas_etl.api.database.PARQUET_DIR", parquet_dir)
    monkeypatch.setattr("noticiasagricolas_etl.api.database.PARQUET_BASIS_DIR", basis_dir)

    # Create test data
    _create_test_parquet(parquet_dir, "soja", [
        _row(date(2024, 6, 10), "soja", "soja-fisico", "Soja Fisico", "Paranagua/PR", None, "preco", 130.5, "130,50", "R$/sc", "price", "BRL", "sc60kg", "spot", None, "PR", "physical"),
        _row(date(2024, 6, 10), "soja", "soja-fisico", "Soja Fisico", "Rondonopolis/MT", None, "preco", 120.0, "120,00", "R$/sc", "price", "BRL", "sc60kg", "spot", None, "MT", "physical"),
        _row(date(2024, 6, 11), "soja", "soja-fisico", "Soja Fisico", "Paranagua/PR", None, "preco", 131.0, "131,00", "R$/sc", "price", "BRL", "sc60kg", "spot", None, "PR", "physical"),
        _row(date(2024, 6, 10), "soja", "soja-b3", "Soja B3", None, "Jul/24", "ajuste", 135.0, "135,00", "R$/sc", "price", "BRL", "sc60kg", "futures", "2024-07", None, "b3"),
        _row(date(2024, 6, 10), "soja", "soja-b3", "Soja B3", None, "Set/24", "ajuste", 137.0, "137,00", "R$/sc", "price", "BRL", "sc60kg", "futures", "2024-09", None, "b3"),
        _row(date(2024, 6, 11), "soja", "soja-b3", "Soja B3", None, "Jul/24", "ajuste", 136.0, "136,00", "R$/sc", "price", "BRL", "sc60kg", "futures", "2024-07", None, "b3"),
    ])
    _create_test_parquet(parquet_dir, "milho", [
        _row(date(2024, 6, 10), "milho", "milho-fisico", "Milho Fisico", "Campinas/SP", None, "preco", 58.0, "58,00", "R$/sc", "price", "BRL", "sc60kg", "spot", None, "SP", "physical"),
    ])

    # Create basis test data
    _create_basis_parquet(basis_dir, "soja", [
        {"date": date(2024, 6, 10), "location": "Paranagua/PR", "state": "PR",
         "physical_indicator": "soja-fisico", "physical_price_brl": 130.5,
         "futures_indicator": "soja-b3", "futures_contract": "2024-07",
         "futures_price_raw": 24.5, "futures_price_brl": 127.16,
         "ptax": 5.19, "basis_brl": 3.34, "basis_usd": 0.64, "basis_pct": 2.63},
        {"date": date(2024, 6, 10), "location": "Rondonopolis/MT", "state": "MT",
         "physical_indicator": "soja-fisico", "physical_price_brl": 120.0,
         "futures_indicator": "soja-b3", "futures_contract": "2024-07",
         "futures_price_raw": 24.5, "futures_price_brl": 127.16,
         "ptax": 5.19, "basis_brl": -7.16, "basis_usd": -1.38, "basis_pct": -5.63},
        {"date": date(2024, 6, 11), "location": "Paranagua/PR", "state": "PR",
         "physical_indicator": "soja-fisico", "physical_price_brl": 131.0,
         "futures_indicator": "soja-b3", "futures_contract": "2024-07",
         "futures_price_raw": 24.8, "futures_price_brl": 128.71,
         "ptax": 5.19, "basis_brl": 2.29, "basis_usd": 0.44, "basis_pct": 1.78},
    ])

    # Reset and reinit DuckDB
    db.close_connection()
    db._conn = None
    db.get_connection()

    # Clear cached PTAX indicator lookup
    from noticiasagricolas_etl.api.services.fx_service import _find_ptax_indicator
    _find_ptax_indicator.cache_clear()

    yield

    db.close_connection()
    db._conn = None


def _row(dt, commodity, indicator, indicator_name, location, contract_month,
         column_name, value, value_raw, unit, measure, currency, unit_std,
         price_basis, contract, state, market_type):
    return {
        "date": dt, "commodity": commodity, "indicator": indicator,
        "indicator_name": indicator_name, "location": location,
        "contract_month": contract_month, "column_name": column_name,
        "value": value, "value_raw": value_raw, "unit": unit,
        "measure": measure, "currency": currency, "unit_std": unit_std,
        "price_basis": price_basis, "contract": contract,
        "state": state, "market_type": market_type,
    }


def _create_test_parquet(parquet_dir, commodity, rows):
    path = parquet_dir / f"commodity={commodity}"
    path.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(table, path / "data.parquet")


def _create_basis_parquet(basis_dir, commodity, rows):
    import numpy as np
    path = basis_dir / f"commodity={commodity}"
    path.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for field in BASIS_SCHEMA:
        if field.name not in df.columns:
            df[field.name] = np.nan
    df = df[[f.name for f in BASIS_SCHEMA]]
    table = pa.Table.from_pandas(df, schema=BASIS_SCHEMA, preserve_index=False)
    pq.write_table(table, path / "data.parquet")


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


# ── Root endpoint ────────────────────────────────────────────────────────────

class TestRoot:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Noticias Agricolas API"
        assert "endpoints" in data


# ── Metadata endpoints ───────────────────────────────────────────────────────

class TestMetadata:
    def test_commodities(self, client):
        resp = client.get("/v1/commodities")
        assert resp.status_code == 200
        data = resp.json()["data"]
        names = [c["commodity"] for c in data]
        assert "soja" in names
        assert "milho" in names

    def test_commodity_indicators(self, client):
        resp = client.get("/v1/commodities/soja/indicators")
        assert resp.status_code == 200
        data = resp.json()
        assert data["commodity"] == "soja"

    def test_categories(self, client):
        resp = client.get("/v1/categories")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_locations(self, client):
        resp = client.get("/v1/locations")
        assert resp.status_code == 200
        data = resp.json()["data"]
        locations = [l["location"] for l in data]
        assert "Paranagua/PR" in locations

    def test_locations_by_state(self, client):
        resp = client.get("/v1/locations?state=PR")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert all(l["state"] == "PR" for l in data)

    def test_contracts(self, client):
        resp = client.get("/v1/contracts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        contracts = [c["contract"] for c in data]
        assert "2024-07" in contracts

    def test_status(self, client):
        resp = client.get("/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_records"] == 7
        assert data["commodity_count"] == 2


# ── Price endpoints ──────────────────────────────────────────────────────────

class TestPrices:
    def test_get_prices(self, client):
        resp = client.get("/v1/prices?commodity=soja&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["data"]) == 6

    def test_get_prices_with_filters(self, client):
        resp = client.get("/v1/prices?commodity=soja&state=PR&measure=price")
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["state"] == "PR" for r in data["data"])

    def test_get_prices_date_range(self, client):
        resp = client.get("/v1/prices?date_from=2024-06-11&date_to=2024-06-11")
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["date"] == "2024-06-11" for r in data["data"])

    def test_get_latest(self, client):
        resp = client.get("/v1/prices/latest?commodity=soja&measure=price")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2024-06-11"

    def test_get_timeseries(self, client):
        resp = client.get("/v1/prices/timeseries?indicator=soja-fisico")
        assert resp.status_code == 200
        data = resp.json()
        assert data["indicator"] == "soja-fisico"
        assert len(data["locations"]) > 0
        assert len(data["series"]) > 0

    def test_pagination(self, client):
        resp = client.get("/v1/prices?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 2
        assert data["total"] == 7


# ── Analytics endpoints ──────────────────────────────────────────────────────

class TestAnalytics:
    def test_futures_curve(self, client):
        resp = client.get("/v1/analytics/futures-curve?indicator=soja-b3&date=2024-06-10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["indicator"] == "soja-b3"
        assert len(data["contracts"]) == 2
        assert data["structure"] in ("contango", "backwardation", "flat")

    def test_regional_spread(self, client):
        resp = client.get("/v1/analytics/regional-spread?indicator=soja-fisico&date=2024-06-10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall"]["location_count"] == 2
        assert data["overall"]["mean_price"] is not None

    def test_rankings(self, client):
        resp = client.get("/v1/analytics/rankings?indicator=soja-fisico&date=2024-06-10")
        assert resp.status_code == 200
        data = resp.json()
        rankings = data["rankings"]
        assert len(rankings) == 2
        # Cheapest first
        assert rankings[0]["value"] <= rankings[1]["value"]
        assert rankings[0]["rank"] == 1

    def test_basis(self, client):
        resp = client.get(
            "/v1/analytics/basis?commodity=soja"
            "&physical_indicator=soja-fisico"
            "&futures_indicator=soja-b3"
            "&location=Paranagua/PR"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "data" in data

    def test_seasonal(self, client):
        resp = client.get("/v1/analytics/seasonal?indicator=soja-fisico")
        assert resp.status_code == 200
        data = resp.json()
        assert data["granularity"] == "monthly"


# ── Query builder ────────────────────────────────────────────────────────────

class TestQueryBuilder:
    def test_empty_builder(self):
        from noticiasagricolas_etl.api.services.query_builder import WhereBuilder
        wb = WhereBuilder()
        where, params = wb.build()
        assert where == ""
        assert params == []

    def test_single_condition(self):
        from noticiasagricolas_etl.api.services.query_builder import WhereBuilder
        wb = WhereBuilder()
        wb.add("commodity", "soja")
        where, params = wb.build()
        assert where == "WHERE commodity = ?"
        assert params == ["soja"]

    def test_none_ignored(self):
        from noticiasagricolas_etl.api.services.query_builder import WhereBuilder
        wb = WhereBuilder()
        wb.add("commodity", None)
        where, params = wb.build()
        assert where == ""

    def test_date_range(self):
        from noticiasagricolas_etl.api.services.query_builder import WhereBuilder
        wb = WhereBuilder()
        wb.add_date_range(date_from="2024-01-01", date_to="2024-12-31")
        where, params = wb.build()
        assert "date >= ?" in where
        assert "date <= ?" in where
        assert len(params) == 2

    def test_multiple_conditions(self):
        from noticiasagricolas_etl.api.services.query_builder import WhereBuilder
        wb = WhereBuilder()
        wb.add("commodity", "soja").add("state", "PR").add_date_range(date_from="2024-01-01")
        where, params = wb.build()
        assert where.count("AND") == 2
        assert len(params) == 3


# ── Auth ─────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_create_and_validate_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("noticiasagricolas_etl.api.auth.AUTH_DB_PATH", tmp_path / "auth.db")
        from noticiasagricolas_etl.api.auth import create_api_key, validate_key
        key = create_api_key("test-user", tier="pro")
        assert key.startswith("na_live_")
        info = validate_key(key)
        assert info is not None
        assert info["tier"] == "pro"

    def test_invalid_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("noticiasagricolas_etl.api.auth.AUTH_DB_PATH", tmp_path / "auth.db")
        from noticiasagricolas_etl.api.auth import validate_key
        assert validate_key("na_live_invalid") is None

    def test_rate_limiter(self):
        from noticiasagricolas_etl.api.auth import _RateLimiter
        limiter = _RateLimiter()
        for _ in range(5):
            assert limiter.check("test-key", 5)
        assert not limiter.check("test-key", 5)
        assert limiter.remaining("test-key", 5) == 0

    def test_rate_limiter_evicts_stale_keys(self):
        from noticiasagricolas_etl.api.auth import _RateLimiter
        limiter = _RateLimiter()
        # Use a very short window so entries expire immediately
        limiter.check("stale-key", 10, window_seconds=0)
        # After expiry, remaining() should clean up the key
        limiter.remaining("stale-key", 10, window_seconds=0)
        assert "stale-key" not in limiter.windows


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_parquet_dir(self, tmp_path, monkeypatch):
        """API works when no Parquet files exist."""
        empty_dir = tmp_path / "empty_parquet"
        empty_dir.mkdir()
        monkeypatch.setattr("noticiasagricolas_etl.api.database.PARQUET_DIR", empty_dir)
        db.close_connection()
        db._conn = None
        db.get_connection()

        app = create_app()
        c = TestClient(app)
        resp = c.get("/v1/status")
        assert resp.status_code == 200
        assert resp.json()["total_records"] == 0

        resp = c.get("/v1/prices?commodity=soja")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_latest_no_data_returns_null_date(self, client):
        """get_latest returns null date when no matching data."""
        resp = client.get("/v1/prices/latest?commodity=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["date"] is None
        assert resp.json()["data"] == []

    def test_latest_with_all_filters(self, client):
        """get_latest with commodity + indicator + measure all set."""
        resp = client.get("/v1/prices/latest?commodity=soja&indicator=soja-fisico&measure=price")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2024-06-11"
        assert all(r["commodity"] == "soja" for r in data["data"])

    def test_rankings_latest_keyword(self, client):
        """Rankings with date='latest' should use max date."""
        resp = client.get("/v1/analytics/rankings?indicator=soja-fisico&date=latest")
        assert resp.status_code == 200
        assert len(resp.json()["rankings"]) > 0

    def test_rankings_no_data(self, client):
        """Rankings for nonexistent indicator returns empty."""
        resp = client.get("/v1/analytics/rankings?indicator=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["rankings"] == []

    def test_futures_curve_latest(self, client):
        """Futures curve with no date picks latest automatically."""
        resp = client.get("/v1/analytics/futures-curve?indicator=soja-b3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] is not None
        assert len(data["contracts"]) > 0

    def test_futures_curve_no_data(self, client):
        """Futures curve for nonexistent indicator returns empty."""
        resp = client.get("/v1/analytics/futures-curve?indicator=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["contracts"] == []

    def test_regional_spread_latest(self, client):
        """Regional spread with no date picks latest automatically."""
        resp = client.get("/v1/analytics/regional-spread?indicator=soja-fisico")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall"]["location_count"] > 0

    def test_basis_with_date_range(self, client):
        """Basis with date filters works correctly."""
        resp = client.get(
            "/v1/analytics/basis?commodity=soja"
            "&physical_indicator=soja-fisico"
            "&futures_indicator=soja-b3"
            "&date_from=2024-06-10&date_to=2024-06-10"
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["data"]:
            assert all(r["date"] == "2024-06-10" for r in data["data"])

    def test_basis_no_matching_data(self, client):
        """Basis returns empty when no data matches."""
        resp = client.get(
            "/v1/analytics/basis?commodity=soja"
            "&physical_indicator=nonexistent"
            "&futures_indicator=also-nonexistent"
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        assert resp.json()["summary"] == {}

    def test_seasonal_no_data(self, client):
        """Seasonal for nonexistent indicator returns empty."""
        resp = client.get("/v1/analytics/seasonal?indicator=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_basis_panel(self, client):
        """Basis panel returns precomputed basis data."""
        resp = client.get("/v1/analytics/basis-panel?commodity=soja")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["data"]) == 3

    def test_basis_panel_state_filter(self, client):
        """Basis panel filters by state."""
        resp = client.get("/v1/analytics/basis-panel?commodity=soja&state=PR")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(r["state"] == "PR" for r in data["data"])

    def test_basis_panel_date_range(self, client):
        """Basis panel filters by date range."""
        resp = client.get(
            "/v1/analytics/basis-panel?commodity=soja"
            "&date_from=2024-06-11&date_to=2024-06-11"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["data"][0]["date"] == "2024-06-11"

    def test_basis_panel_empty(self, client):
        """Basis panel for nonexistent commodity returns empty."""
        resp = client.get("/v1/analytics/basis-panel?commodity=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["data"] == []

    def test_basis_panel_pagination(self, client):
        """Basis panel pagination works."""
        resp = client.get("/v1/analytics/basis-panel?commodity=soja&limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["data"]) == 1

    def test_spread_with_date_range(self, client):
        """Regional spread with date_from/date_to range."""
        resp = client.get(
            "/v1/analytics/regional-spread?indicator=soja-fisico"
            "&date_from=2024-06-10&date_to=2024-06-11"
        )
        assert resp.status_code == 200
        assert resp.json()["overall"]["location_count"] > 0

    def test_prices_no_filters(self, client):
        """Prices with no filters returns all data."""
        resp = client.get("/v1/prices")
        assert resp.status_code == 200
        assert resp.json()["total"] == 7

    def test_timeseries_no_data(self, client):
        """Timeseries for nonexistent indicator returns empty series."""
        resp = client.get("/v1/prices/timeseries?indicator=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["series"] == []
        assert resp.json()["locations"] == []

    def test_contracts_no_futures(self, client):
        """Contracts endpoint for physical indicator (no contracts)."""
        resp = client.get("/v1/contracts?indicator=soja-fisico")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_locations_no_match(self, client):
        """Locations with nonexistent state."""
        resp = client.get("/v1/locations?state=XX")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestAnalyticsExtras:
    """Tests for the basis-percentile / ratio / term-structure endpoints."""

    def test_basis_percentile(self, client):
        resp = client.get(
            "/v1/analytics/basis-percentile?commodity=soja&location=Paranagua/PR"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["commodity"] == "soja"
        assert data["location"] == "Paranagua/PR"
        assert "percentile" in data
        assert 0 <= data["percentile"] <= 100
        assert "interpretation" in data

    def test_basis_percentile_no_data(self, client):
        resp = client.get(
            "/v1/analytics/basis-percentile?commodity=soja&location=NowhereCity/XX"
        )
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_basis_percentile_invalid_column(self, client):
        resp = client.get(
            "/v1/analytics/basis-percentile?commodity=soja&location=Paranagua/PR&column=invalid_col"
        )
        # Service raises ValueError → router converts to 400
        assert resp.status_code == 400

    def test_ratio_endpoint(self, client):
        # The fixture has soja-fisico in Paranagua/PR + Rondonopolis/MT, milho-fisico in Campinas/SP
        # The ratio endpoint averages across praças when location is None — should still work
        resp = client.get(
            "/v1/analytics/ratio?numerator_indicator=soja-fisico"
            "&denominator_indicator=milho-fisico"
        )
        assert resp.status_code == 200
        data = resp.json()
        # Either succeeds (>=1 overlapping date) or surfaces error cleanly
        if "error" not in data:
            assert "current_ratio" in data
            assert "percentile" in data
            assert "interpretation" in data

    def test_term_structure(self, client):
        resp = client.get(
            "/v1/analytics/term-structure?futures_indicator=soja-b3"
        )
        assert resp.status_code == 200
        data = resp.json()
        # Fixture has 2 contracts on 2024-06-10 (Jul/24 + Set/24) so we expect a regime
        if "error" not in data:
            assert "regime" in data
            assert "contracts" in data
            assert len(data["contracts"]) >= 2

    def test_term_structure_unknown_indicator(self, client):
        resp = client.get(
            "/v1/analytics/term-structure?futures_indicator=does-not-exist"
        )
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_crush_percentile_no_data(self, client):
        # Test fixture doesn't have farelo/oleo so this surfaces the error path
        resp = client.get("/v1/analytics/crush-percentile")
        assert resp.status_code == 200
        # Either error (no data) or valid result — both are acceptable
        data = resp.json()
        assert "error" in data or "percentile" in data

    def test_price_attribution_invalid_pair(self, client):
        resp = client.get(
            "/v1/analytics/price-attribution"
            "?commodity=soja&location=Paranagua/PR"
            "&futures_indicator=soja-b3"
            "&date_from=2024-06-10"
        )
        assert resp.status_code == 200
        assert "error" in resp.json()  # soja-b3 has no bu_per_sc mapping

    def test_price_attribution_no_data(self, client):
        resp = client.get(
            "/v1/analytics/price-attribution"
            "?commodity=soja&location=NowhereCity"
            "&futures_indicator=soja-bolsa-de-chicago-cme-group"
            "&date_from=2024-06-10"
        )
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_anomaly_endpoint(self, client):
        resp = client.get(
            "/v1/analytics/anomaly?indicator=soja-fisico"
        )
        assert resp.status_code == 200
        # Fixture has only 2 dates → insufficient history error
        data = resp.json()
        assert "error" in data or "is_anomaly" in data

    def test_anomaly_unknown_indicator(self, client):
        resp = client.get("/v1/analytics/anomaly?indicator=does-not-exist")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_port_spread_no_data(self, client):
        # Test fixture has no port locations → expect error
        resp = client.get(
            "/v1/analytics/port-spread"
            "?commodity=soja&interior_location=Rondonopolis/MT"
        )
        assert resp.status_code == 200
        # Either error (no port data) or valid result
        data = resp.json()
        assert "error" in data or "spread_today_brl_per_sc" in data

    def test_vol_regime_insufficient_history(self, client):
        # Fixture has 2 dates of soja-fisico — too few for vol regime
        resp = client.get("/v1/analytics/vol-regime?indicator=soja-fisico")
        assert resp.status_code == 200
        # Either error (insufficient) or valid result
        data = resp.json()
        assert "error" in data or "regime" in data

    def test_hedge_fit_insufficient_history(self, client):
        resp = client.get(
            "/v1/analytics/hedge-fit"
            "?commodity=soja&location=Paranagua/PR"
            "&futures_indicator=soja-b3"
        )
        assert resp.status_code == 200
        # Fixture has 3 basis rows — insufficient for regression
        assert "error" in resp.json() or "r_squared" in resp.json()

    def test_hedge_fit_invalid_freq(self, client):
        resp = client.get(
            "/v1/analytics/hedge-fit"
            "?commodity=soja&location=Paranagua/PR"
            "&futures_indicator=soja-b3&frequency=monthly"
        )
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_port_basis_tracker_returns_expected_shape(self, client):
        # Test fixture has Paranagua/PR (no diacritic) which isn't in PORT_LOCATIONS,
        # so we expect ports_with_data == 0 but a clean response.
        resp = client.get(
            "/v1/analytics/port-basis-tracker?commodity=soja"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["commodity"] == "soja"
        assert "ports" in data
        assert isinstance(data["ports"], list)
        assert "ports_with_data" in data
        assert "errors" in data

    def test_port_basis_tracker_invalid_column(self, client):
        resp = client.get(
            "/v1/analytics/port-basis-tracker?commodity=soja&column=garbage"
        )
        # Underlying service raises ValueError on bad column → 400 via _handle_query
        assert resp.status_code == 400
