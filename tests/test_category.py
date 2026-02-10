"""Tests for the category system: resolution, filtering, listing."""

import textwrap
from pathlib import Path

import pytest
import yaml

from noticiasagricolas_etl.catalog import (
    get_entries_by_category,
    list_categories,
    load_catalog,
)
from noticiasagricolas_etl.models import Category, CatalogEntry, PageType


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _write_yaml(path: Path, entries: list[dict]):
    """Write a minimal catalog YAML for testing."""
    path.write_text(yaml.dump({"entries": entries}, allow_unicode=True))


@pytest.fixture
def catalog_path(tmp_path):
    """Create a temp catalog.yaml with known entries."""
    entries = [
        {"commodity": "soja", "slug": "soja-indicador", "name": "Soja Ind",
         "page_type": "indicator", "unit": "R$"},
        {"commodity": "milho", "slug": "milho-indicador", "name": "Milho Ind",
         "page_type": "indicator", "unit": "R$"},
        {"commodity": "sucroenergetico", "slug": "acucar-cristal", "name": "Açúcar",
         "page_type": "physical_market", "unit": "R$"},
        {"commodity": "sucroenergetico", "slug": "etanol-b3-prego-regular",
         "name": "Etanol B3", "page_type": "b3_futures", "unit": "R$/m3",
         "category": "biofuels"},
        {"commodity": "boi-gordo", "slug": "boi-gordo-ind", "name": "Boi Gordo",
         "page_type": "indicator", "unit": "R$/@"},
        # Entry without matching default → category stays None
        {"commodity": "desconhecido", "slug": "desc-1", "name": "Unknown",
         "page_type": "indicator", "unit": "R$"},
    ]
    p = tmp_path / "catalog.yaml"
    _write_yaml(p, entries)
    return p


# ── Category resolution ──────────────────────────────────────────────────────


class TestCategoryResolution:
    def test_soja_gets_oilseeds_from_default(self, catalog_path):
        entries = load_catalog(catalog_path)
        soja = [e for e in entries if e.slug == "soja-indicador"][0]
        assert soja.category == Category.OILSEEDS

    def test_milho_gets_grains_from_default(self, catalog_path):
        entries = load_catalog(catalog_path)
        milho = [e for e in entries if e.slug == "milho-indicador"][0]
        assert milho.category == Category.GRAINS

    def test_sucroenergetico_defaults_to_sugar(self, catalog_path):
        entries = load_catalog(catalog_path)
        acucar = [e for e in entries if e.slug == "acucar-cristal"][0]
        assert acucar.category == Category.SUGAR

    def test_ethanol_explicit_override_to_biofuels(self, catalog_path):
        entries = load_catalog(catalog_path)
        etanol = [e for e in entries if e.slug == "etanol-b3-prego-regular"][0]
        assert etanol.category == Category.BIOFUELS

    def test_boi_gordo_gets_livestock(self, catalog_path):
        entries = load_catalog(catalog_path)
        boi = [e for e in entries if e.slug == "boi-gordo-ind"][0]
        assert boi.category == Category.LIVESTOCK

    def test_unknown_commodity_has_no_category(self, catalog_path):
        entries = load_catalog(catalog_path)
        desc = [e for e in entries if e.slug == "desc-1"][0]
        assert desc.category is None


# ── Filter by category ───────────────────────────────────────────────────────


class TestGetEntriesByCategory:
    def test_filter_oilseeds(self, catalog_path):
        entries = load_catalog(catalog_path)
        oilseeds = get_entries_by_category(entries, "oilseeds")
        assert len(oilseeds) == 1
        assert oilseeds[0].slug == "soja-indicador"

    def test_filter_biofuels(self, catalog_path):
        entries = load_catalog(catalog_path)
        biofuels = get_entries_by_category(entries, "biofuels")
        assert len(biofuels) == 1
        assert biofuels[0].slug == "etanol-b3-prego-regular"

    def test_filter_sugar(self, catalog_path):
        entries = load_catalog(catalog_path)
        sugar = get_entries_by_category(entries, "sugar")
        assert len(sugar) == 1
        assert sugar[0].commodity == "sucroenergetico"

    def test_nonexistent_category_returns_empty(self, catalog_path):
        entries = load_catalog(catalog_path)
        result = get_entries_by_category(entries, "doesnotexist")
        assert result == []

    def test_disabled_entries_excluded(self, tmp_path):
        entries_data = [
            {"commodity": "soja", "slug": "soja-disabled", "name": "Disabled",
             "page_type": "indicator", "unit": "R$", "enabled": False},
        ]
        p = tmp_path / "catalog.yaml"
        _write_yaml(p, entries_data)
        entries = load_catalog(p)
        oilseeds = get_entries_by_category(entries, "oilseeds")
        assert oilseeds == []


# ── List categories ──────────────────────────────────────────────────────────


class TestListCategories:
    def test_returns_sorted_unique_categories(self, catalog_path):
        entries = load_catalog(catalog_path)
        cats = list_categories(entries)
        assert cats == sorted(cats)
        assert "oilseeds" in cats
        assert "grains" in cats
        assert "sugar" in cats
        assert "biofuels" in cats
        assert "livestock" in cats

    def test_none_categories_excluded(self, catalog_path):
        entries = load_catalog(catalog_path)
        cats = list_categories(entries)
        assert None not in cats


# ── Backward compatibility ───────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_entries_without_new_fields_still_load(self, tmp_path):
        """Old-style entries (no category/source/frequency/description) still parse."""
        entries_data = [
            {"commodity": "soja", "slug": "soja-old", "name": "Old Entry",
             "page_type": "indicator", "unit": "R$"},
        ]
        p = tmp_path / "catalog.yaml"
        _write_yaml(p, entries_data)
        entries = load_catalog(p)
        assert len(entries) == 1
        e = entries[0]
        assert e.source is None
        assert e.frequency is None
        assert e.description is None
        # Category should be resolved from defaults
        assert e.category == Category.OILSEEDS

    def test_new_fields_populate_when_present(self, tmp_path):
        entries_data = [
            {"commodity": "soja", "slug": "soja-new", "name": "New Entry",
             "page_type": "indicator", "unit": "R$",
             "source": "Cepea/Esalq (USP)", "frequency": "daily",
             "description": "Test description"},
        ]
        p = tmp_path / "catalog.yaml"
        _write_yaml(p, entries_data)
        entries = load_catalog(p)
        e = entries[0]
        assert e.source == "Cepea/Esalq (USP)"
        assert e.frequency == "daily"
        assert e.description == "Test description"
