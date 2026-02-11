"""MCP server exposing commodity price data as tools.

Wraps the same api/services/ functions used by the REST API.
Run with: na-mcp (stdio mode) or as SSE server.
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from ..api import database as db
from ..api.services import (
    basis_panel_service,
    basis_service,
    crush_service,
    curve_service,
    fx_service,
    price_service,
    seasonal_service,
    spread_service,
)
from ..catalog import load_catalog, list_commodities as _list_commodities

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Noticias Agricolas",
    instructions="Brazilian commodity price data — 158 indicators, 24 commodities, 2,200+ locations, 6 years of history.",
)


def _json(obj) -> str:
    """Serialize result to JSON string for MCP response."""
    return json.dumps(obj, ensure_ascii=False, default=str)


@mcp.tool()
async def list_commodities() -> str:
    """List all available commodities and their indicators.

    Use this first to discover what data is available before querying prices.
    Returns commodity names, indicator slugs, categories, and units.
    """
    db.get_connection()  # ensure initialized
    entries = load_catalog()
    commodities = {}
    for e in entries:
        if not e.enabled:
            continue
        if e.commodity not in commodities:
            commodities[e.commodity] = {
                "commodity": e.commodity,
                "category": e.category.value if e.category else None,
                "indicators": [],
            }
        commodities[e.commodity]["indicators"].append({
            "slug": e.slug,
            "name": e.name,
            "unit": e.unit,
            "page_type": e.page_type.value,
        })
    return _json({"commodities": list(commodities.values())})


@mcp.tool()
async def list_locations(
    commodity: str | None = None,
    state: str | None = None,
) -> str:
    """List available locations (cities/regions) for price data.

    Args:
        commodity: Filter by commodity name (e.g. 'soja', 'milho')
        state: Filter by 2-letter BR state code (e.g. 'MT', 'PR')
    """
    db.get_connection()
    result = price_service.get_locations(commodity=commodity, state=state)
    return _json({"locations": result})


@mcp.tool()
async def get_prices(
    commodity: str | None = None,
    indicator: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    state: str | None = None,
    measure: str | None = None,
    limit: int = 100,
) -> str:
    """Query commodity prices with filters.

    Use list_commodities first to find valid indicator slugs.

    Args:
        commodity: Commodity name (e.g. 'soja', 'milho', 'cafe')
        indicator: Indicator slug from catalog
        date_from: Start date YYYY-MM-DD
        date_to: End date YYYY-MM-DD
        location: Location name (e.g. 'Paranaguá/PR')
        state: 2-letter state code (e.g. 'MT')
        measure: 'price', 'change_pct', 'change_abs'
        limit: Max rows (default 100)
    """
    db.get_connection()
    result = price_service.get_prices(
        commodity=commodity, indicator=indicator,
        date_from=date_from, date_to=date_to,
        location=location, state=state,
        measure=measure, limit=limit,
    )
    return _json(result)


@mcp.tool()
async def get_latest_prices(
    commodity: str | None = None,
    indicator: str | None = None,
    measure: str = "price",
) -> str:
    """Get the most recent prices for a commodity or indicator.

    Args:
        commodity: Commodity name
        indicator: Indicator slug
        measure: 'price' (default), 'change_pct', 'change_abs'
    """
    db.get_connection()
    result = price_service.get_latest(commodity=commodity, indicator=indicator, measure=measure)
    return _json(result)


@mcp.tool()
async def get_basis(
    commodity: str,
    physical_indicator: str,
    futures_indicator: str,
    location: str | None = None,
    contract: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Compute basis (physical price minus futures price) for a Brazilian commodity.

    Returns time series with basis value, percentage, and historical percentile.
    Use list_commodities first to discover available indicators.

    Args:
        commodity: Commodity name (e.g. 'soja')
        physical_indicator: Physical market indicator slug
        futures_indicator: Futures indicator slug
        location: Optional location for physical prices
        contract: Optional contract month YYYY-MM
        date_from: Start date YYYY-MM-DD
        date_to: End date YYYY-MM-DD
    """
    db.get_connection()
    result = basis_service.compute(
        commodity=commodity,
        physical_indicator=physical_indicator,
        futures_indicator=futures_indicator,
        location=location, contract=contract,
        date_from=date_from, date_to=date_to,
    )
    return _json(result)


@mcp.tool()
async def get_basis_panel(
    commodity: str | None = None,
    location: str | None = None,
    state: str | None = None,
    futures_indicator: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> str:
    """Query precomputed basis panel (physical - futures) with unit/FX normalization.

    Returns materialized daily basis time series per commodity-location pair.
    Includes front-month auto-detection and PTAX currency conversion.

    Args:
        commodity: Commodity name (e.g. 'soja', 'milho', 'trigo')
        location: Physical market location filter
        state: 2-letter BR state code (e.g. 'PR', 'MT')
        futures_indicator: Futures indicator slug filter
        date_from: Start date YYYY-MM-DD
        date_to: End date YYYY-MM-DD
        limit: Max rows (default 100)
    """
    db.get_connection()
    result = basis_panel_service.get_basis_panel(
        commodity=commodity, location=location, state=state,
        futures_indicator=futures_indicator,
        date_from=date_from, date_to=date_to,
        limit=limit,
    )
    return _json(result)


@mcp.tool()
async def get_crush_margin(
    contract: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Compute soybean crushing margin: (farelo + oleo revenue) - soja cost.

    Uses B3 futures indicators by default.

    Args:
        contract: Optional contract month YYYY-MM
        date_from: Start date YYYY-MM-DD
        date_to: End date YYYY-MM-DD
    """
    db.get_connection()
    result = crush_service.compute(contract=contract, date_from=date_from, date_to=date_to)
    return _json(result)


@mcp.tool()
async def get_futures_curve(
    indicator: str,
    date: str | None = None,
) -> str:
    """Get all active futures contracts on a date with contango/backwardation label.

    Args:
        indicator: Futures indicator slug
        date: Date YYYY-MM-DD (defaults to most recent available)
    """
    db.get_connection()
    result = curve_service.get_curve(indicator=indicator, date=date)
    return _json(result)


@mcp.tool()
async def get_regional_spread(
    indicator: str,
    date: str | None = None,
) -> str:
    """Get price dispersion across locations with statistics.

    Returns mean, std, IQR, by-state breakdown, and extremes.

    Args:
        indicator: Indicator slug (physical market with multiple locations)
        date: Date YYYY-MM-DD (defaults to latest)
    """
    db.get_connection()
    result = spread_service.get_regional_spread(indicator=indicator, date=date)
    return _json(result)


@mcp.tool()
async def get_fx_adjusted(
    indicator: str,
    target_currency: str = "USD",
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Convert commodity prices between BRL and USD using PTAX exchange rate.

    Args:
        indicator: Indicator slug
        target_currency: 'USD' or 'BRL'
        date_from: Start date YYYY-MM-DD
        date_to: End date YYYY-MM-DD
    """
    db.get_connection()
    result = fx_service.get_fx_adjusted(
        indicator=indicator, target_currency=target_currency,
        date_from=date_from, date_to=date_to,
    )
    return _json(result)


@mcp.tool()
async def get_seasonal_pattern(
    indicator: str,
    location: str | None = None,
    granularity: str = "monthly",
) -> str:
    """Get multi-year seasonal price averages with current-year comparison.

    Useful for identifying seasonal patterns in commodity prices.

    Args:
        indicator: Indicator slug
        location: Optional location filter
        granularity: 'monthly' or 'weekly'
    """
    db.get_connection()
    result = seasonal_service.get_seasonal(
        indicator=indicator, location=location, granularity=granularity,
    )
    return _json(result)


@mcp.tool()
async def get_rankings(
    indicator: str,
    date: str | None = None,
    limit: int = 30,
) -> str:
    """Get locations ranked by price, cheapest to most expensive.

    Args:
        indicator: Physical market indicator slug
        date: Date YYYY-MM-DD or None for latest
        limit: Max locations to return (default 30)
    """
    db.get_connection()
    result = spread_service.get_rankings(indicator=indicator, date=date, limit=limit)
    return _json(result)


def main():
    """Entry point for na-mcp command (stdio mode)."""
    logging.basicConfig(level=logging.INFO)
    db.get_connection()  # Initialize before serving
    mcp.run()


if __name__ == "__main__":
    main()
