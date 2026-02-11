"""Metadata endpoints: commodities, categories, locations, contracts, status."""

from fastapi import APIRouter, Query

from ... import catalog as cat_module
from ...config import PARQUET_DIR
from .. import database as db
from ..services import price_service

router = APIRouter(prefix="/v1", tags=["metadata"])


@router.get("/commodities")
def list_commodities():
    """List all commodities with date ranges and record counts."""
    rows = db.query("""
        SELECT commodity,
               MIN(date) AS first_date, MAX(date) AS last_date,
               COUNT(*) AS record_count,
               COUNT(DISTINCT indicator) AS indicator_count,
               COUNT(DISTINCT location) AS location_count
        FROM prices
        GROUP BY commodity
        ORDER BY commodity
    """)
    for row in rows:
        row["first_date"] = str(row["first_date"]) if row["first_date"] else None
        row["last_date"] = str(row["last_date"]) if row["last_date"] else None
    return {"data": rows}


@router.get("/commodities/{commodity}/indicators")
def commodity_indicators(commodity: str):
    """Get indicators for a specific commodity with metadata."""
    entries = cat_module.load_catalog()
    commodity_entries = cat_module.get_entries_by_commodity(entries, commodity)

    # Get data stats per indicator
    stats = db.query("""
        SELECT indicator,
               MIN(date) AS first_date, MAX(date) AS last_date,
               COUNT(*) AS record_count,
               COUNT(DISTINCT date) AS date_count,
               COUNT(DISTINCT location) AS location_count
        FROM prices
        WHERE commodity = ?
        GROUP BY indicator
    """, [commodity])
    stats_map = {s["indicator"]: s for s in stats}

    result = []
    for entry in commodity_entries:
        info = {
            "slug": entry.slug,
            "name": entry.name,
            "page_type": entry.page_type.value,
            "unit": entry.unit,
            "category": entry.category.value if entry.category else None,
            "source": entry.source,
        }
        s = stats_map.get(entry.slug, {})
        info["first_date"] = str(s["first_date"]) if s.get("first_date") else None
        info["last_date"] = str(s["last_date"]) if s.get("last_date") else None
        info["record_count"] = s.get("record_count", 0)
        info["date_count"] = s.get("date_count", 0)
        info["location_count"] = s.get("location_count", 0)
        result.append(info)

    return {"commodity": commodity, "indicators": result}


@router.get("/categories")
def list_categories():
    """List categories with commodity counts."""
    entries = cat_module.load_catalog()
    categories = {}
    for e in entries:
        if not e.enabled or not e.category:
            continue
        cat = e.category.value
        if cat not in categories:
            categories[cat] = {"category": cat, "commodities": set(), "indicator_count": 0}
        categories[cat]["commodities"].add(e.commodity)
        categories[cat]["indicator_count"] += 1

    result = []
    for cat in sorted(categories):
        c = categories[cat]
        result.append({
            "category": c["category"],
            "commodity_count": len(c["commodities"]),
            "commodities": sorted(c["commodities"]),
            "indicator_count": c["indicator_count"],
        })
    return {"data": result}


@router.get("/locations")
def list_locations(
    commodity: str | None = Query(None),
    state: str | None = Query(None),
):
    """Get distinct locations with state codes."""
    return {"data": price_service.get_locations(commodity, state)}


@router.get("/contracts")
def list_contracts(indicator: str | None = Query(None)):
    """Get available futures contract months."""
    return {"data": price_service.get_contracts(indicator)}


@router.get("/status")
def status():
    """Data freshness, record counts, last ETL run."""
    try:
        summary = db.query("""
            SELECT COUNT(*) AS total_records,
                   COUNT(DISTINCT commodity) AS commodity_count,
                   COUNT(DISTINCT indicator) AS indicator_count,
                   COUNT(DISTINCT location) AS location_count,
                   COUNT(DISTINCT date) AS date_count,
                   MIN(date) AS first_date,
                   MAX(date) AS last_date
            FROM prices
        """)[0]
        summary["first_date"] = str(summary["first_date"]) if summary["first_date"] else None
        summary["last_date"] = str(summary["last_date"]) if summary["last_date"] else None
    except Exception:
        summary = {
            "total_records": 0, "commodity_count": 0, "indicator_count": 0,
            "location_count": 0, "date_count": 0, "first_date": None, "last_date": None,
        }

    # Check Parquet directory
    parquet_files = list(PARQUET_DIR.glob("commodity=*/data.parquet")) if PARQUET_DIR.exists() else []

    return {
        **summary,
        "parquet_files": len(parquet_files),
        "parquet_dir": str(PARQUET_DIR),
    }
