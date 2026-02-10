"""YAML catalog loader."""

from pathlib import Path
from typing import Optional

import yaml

from .config import CATALOG_PATH, COMMODITY_CATEGORY_DEFAULTS
from .models import Category, CatalogEntry


def load_catalog(path: Optional[Path] = None) -> list[CatalogEntry]:
    """Load catalog entries from YAML file.

    If an entry does not have an explicit ``category``, it is resolved from
    COMMODITY_CATEGORY_DEFAULTS using the entry's ``commodity`` field.
    """
    path = path or CATALOG_PATH
    with open(path) as f:
        data = yaml.safe_load(f)

    entries = []
    for item in data.get("entries", []):
        entry = CatalogEntry(**item)
        # Resolve category from defaults when not explicitly set in YAML
        if entry.category is None:
            default_cat = COMMODITY_CATEGORY_DEFAULTS.get(entry.commodity)
            if default_cat:
                entry.category = Category(default_cat)
        entries.append(entry)
    return entries


def get_entries_by_commodity(
    entries: list[CatalogEntry], commodity: str
) -> list[CatalogEntry]:
    """Filter catalog entries by commodity."""
    return [e for e in entries if e.commodity == commodity and e.enabled]


def get_entry_by_slug(
    entries: list[CatalogEntry], slug: str
) -> Optional[CatalogEntry]:
    """Find a catalog entry by its slug."""
    for e in entries:
        if e.slug == slug:
            return e
    return None


def get_enabled_entries(entries: list[CatalogEntry]) -> list[CatalogEntry]:
    """Return only enabled catalog entries."""
    return [e for e in entries if e.enabled]


def get_entries_by_category(
    entries: list[CatalogEntry], category: str
) -> list[CatalogEntry]:
    """Filter enabled catalog entries by category string."""
    return [
        e for e in entries
        if e.enabled and e.category is not None and e.category.value == category
    ]


def list_categories(entries: list[CatalogEntry]) -> list[str]:
    """Return sorted list of unique category values present in entries."""
    return sorted({e.category.value for e in entries if e.category is not None})


def list_commodities(entries: list[CatalogEntry]) -> list[str]:
    """Return sorted list of unique commodity names."""
    return sorted({e.commodity for e in entries})
