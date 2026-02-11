"""Core price data endpoints."""

from fastapi import APIRouter, Query

from ..services import price_service

router = APIRouter(prefix="/v1", tags=["prices"])


@router.get("/prices")
def get_prices(
    commodity: str | None = Query(None, description="Commodity name, e.g. soja, milho"),
    indicator: str | None = Query(None, description="Indicator slug"),
    date_from: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    location: str | None = Query(None, description="Location name"),
    state: str | None = Query(None, description="2-letter BR state code, e.g. MT, PR"),
    measure: str | None = Query(None, description="Measure type: price, change_pct, change_abs, rate, index"),
    market_type: str | None = Query(None, description="Market type: physical, b3, cme, indicator, etc."),
    contract: str | None = Query(None, description="Contract month YYYY-MM"),
    currency: str | None = Query(None, description="Currency: BRL or USD"),
    limit: int = Query(1000, ge=1, le=50000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Query prices with full filtering and pagination."""
    return price_service.get_prices(
        commodity=commodity, indicator=indicator,
        date_from=date_from, date_to=date_to,
        location=location, state=state,
        measure=measure, market_type=market_type,
        contract=contract, currency=currency,
        limit=limit, offset=offset,
    )


@router.get("/prices/latest")
def get_latest_prices(
    commodity: str | None = Query(None),
    indicator: str | None = Query(None),
    measure: str = Query("price"),
):
    """Get most recent prices for a commodity/indicator."""
    return price_service.get_latest(commodity=commodity, indicator=indicator, measure=measure)


@router.get("/prices/timeseries")
def get_timeseries(
    indicator: str = Query(..., description="Indicator slug (required)"),
    location: str | None = Query(None),
    measure: str = Query("price"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Get time series pivoted by location, ideal for charting."""
    return price_service.get_timeseries(
        indicator=indicator, location=location, measure=measure,
        date_from=date_from, date_to=date_to,
    )
