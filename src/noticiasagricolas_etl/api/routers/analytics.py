"""Analytics endpoints: basis, crush margin, futures curve, regional spread, etc."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ..services import (
    anomaly_service,
    attribution_service,
    basis_panel_service,
    basis_percentile_service,
    basis_service,
    crush_percentile_service,
    crush_service,
    curve_service,
    fx_service,
    ratio_service,
    seasonal_service,
    spread_service,
    term_structure_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


def _handle_query(func, *args, **kwargs):
    """Wrap service calls with error handling."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.exception("Analytics query failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/basis")
def get_basis(
    commodity: str = Query(..., description="Commodity name"),
    physical_indicator: str = Query(..., description="Physical market indicator slug"),
    futures_indicator: str = Query(..., description="Futures indicator slug"),
    location: str | None = Query(None),
    contract: str | None = Query(None, description="Contract month YYYY-MM"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Compute basis (physical - futures) with historical stats and percentile."""
    return _handle_query(
        basis_service.compute,
        commodity=commodity,
        physical_indicator=physical_indicator,
        futures_indicator=futures_indicator,
        location=location, contract=contract,
        date_from=date_from, date_to=date_to,
    )


@router.get("/crush-margin")
def get_crush_margin(
    contract: str | None = Query(None, description="Contract month YYYY-MM"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    soja_indicator: str = Query("soja-b3-pregao-regular"),
    farelo_indicator: str = Query("farelo-de-soja-b3"),
    oleo_indicator: str = Query("oleo-de-soja-b3"),
):
    """Soja crush margin = (farelo + oleo) - soja cost."""
    return _handle_query(
        crush_service.compute,
        contract=contract, date_from=date_from, date_to=date_to,
        soja_indicator=soja_indicator,
        farelo_indicator=farelo_indicator,
        oleo_indicator=oleo_indicator,
    )


@router.get("/futures-curve")
def get_futures_curve(
    indicator: str = Query(..., description="Futures indicator slug"),
    date: str | None = Query(None, description="Date (YYYY-MM-DD), defaults to latest"),
):
    """All active contracts on a date with contango/backwardation label."""
    return _handle_query(curve_service.get_curve, indicator=indicator, date=date)


@router.get("/regional-spread")
def get_regional_spread(
    indicator: str = Query(...),
    date: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Price dispersion: mean, std, IQR, by-state breakdown, extremes."""
    return _handle_query(
        spread_service.get_regional_spread,
        indicator=indicator, date=date,
        date_from=date_from, date_to=date_to,
    )


@router.get("/fx-adjusted")
def get_fx_adjusted(
    indicator: str = Query(...),
    target_currency: str = Query("USD", description="Target currency: USD or BRL"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Convert prices BRL<->USD using PTAX."""
    return _handle_query(
        fx_service.get_fx_adjusted,
        indicator=indicator, target_currency=target_currency,
        date_from=date_from, date_to=date_to,
    )


@router.get("/seasonal")
def get_seasonal(
    indicator: str = Query(...),
    location: str | None = Query(None),
    granularity: str = Query("monthly", description="monthly or weekly"),
    measure: str = Query("price"),
):
    """Multi-year seasonal averages with current-year comparison."""
    return _handle_query(
        seasonal_service.get_seasonal,
        indicator=indicator, location=location,
        granularity=granularity, measure=measure,
    )


@router.get("/basis-panel")
def get_basis_panel(
    commodity: str | None = Query(None, description="Commodity name"),
    location: str | None = Query(None, description="Physical market location"),
    state: str | None = Query(None, description="2-letter BR state code"),
    futures_indicator: str | None = Query(None, description="Futures indicator slug"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    """Query precomputed basis panel (physical - futures) with unit/FX conversion."""
    return _handle_query(
        basis_panel_service.get_basis_panel,
        commodity=commodity, location=location, state=state,
        futures_indicator=futures_indicator,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )


@router.get("/rankings")
def get_rankings(
    indicator: str = Query(...),
    date: str | None = Query(None, description="Date or 'latest'"),
    measure: str = Query("price"),
    limit: int = Query(50, ge=1, le=500),
):
    """Locations ranked by price (cheapest to most expensive)."""
    return _handle_query(
        spread_service.get_rankings,
        indicator=indicator, date=date, measure=measure, limit=limit,
    )


@router.get("/basis-percentile")
def get_basis_percentile(
    commodity: str = Query(..., description="Commodity name (e.g. soja, milho)"),
    location: str = Query(..., description="Praça (e.g. 'Sorriso/MT')"),
    futures_indicator: str | None = Query(None, description="Optional futures slug"),
    target_date: str | None = Query(None, description="ISO date; None = latest"),
    window_years: int = Query(5, ge=1, le=20),
    column: str = Query("basis_brl",
        description="basis_brl | basis_cents_bu | basis_centavos_sc | basis_pct"),
):
    """Today's basis percentile in the N-year history for one praça.

    Tells the trader 'is the current basis cheap or expensive vs typical?' as a
    0-100 number with a plain-Portuguese interpretation string.
    """
    return _handle_query(
        basis_percentile_service.get_basis_percentile,
        commodity=commodity, location=location,
        futures_indicator=futures_indicator,
        target_date=target_date, window_years=window_years,
        column=column,
    )


@router.get("/ratio")
def get_ratio(
    numerator_indicator: str = Query(..., description="e.g. soja-mercado-fisico-sindicatos-e-cooperativas"),
    denominator_indicator: str = Query(..., description="e.g. milho-mercado-fisico-sindicatos-e-cooperativas"),
    location: str | None = Query(None),
    measure: str = Query("price"),
    target_date: str | None = Query(None),
    window_years: int = Query(5, ge=1, le=20),
):
    """Time-series ratio of two indicators (e.g., soja:milho).

    Returns current ratio, percentile vs N-year history, recent series.
    Useful for crop allocation decisions (planting intent).
    """
    return _handle_query(
        ratio_service.get_ratio,
        numerator_indicator=numerator_indicator,
        denominator_indicator=denominator_indicator,
        location=location, measure=measure,
        target_date=target_date, window_years=window_years,
    )


@router.get("/term-structure")
def get_term_structure(
    futures_indicator: str = Query(..., description="e.g. soja-bolsa-de-chicago-cme-group"),
    target_date: str | None = Query(None, description="ISO date; None = latest"),
):
    """Futures curve shape: contango / backwardation classification + slope.

    Signals storage incentive (contango) or supply tightness (backwardation).
    """
    return _handle_query(
        term_structure_service.get_term_structure,
        futures_indicator=futures_indicator,
        target_date=target_date,
    )


@router.get("/crush-percentile")
def get_crush_percentile(
    target_date: str | None = Query(None),
    window_years: int = Query(5, ge=1, le=20),
    contract: str | None = Query(None),
    soja_indicator: str = Query("soja-b3-pregao-regular"),
    farelo_indicator: str = Query("farelo-de-soja-b3"),
    oleo_indicator: str = Query("oleo-de-soja-b3"),
):
    """Today's crush margin percentile vs N-year history.

    Drives industrial decision (esmagar vs ficar parado) — high decile means
    strong incentive to crush, low decile means crusher operates at a loss.
    """
    return _handle_query(
        crush_percentile_service.get_crush_percentile,
        target_date=target_date, window_years=window_years, contract=contract,
        soja_indicator=soja_indicator, farelo_indicator=farelo_indicator,
        oleo_indicator=oleo_indicator,
    )


@router.get("/price-attribution")
def get_price_attribution(
    commodity: str = Query(...),
    location: str = Query(...),
    futures_indicator: str = Query(..., description="CBOT pair (must have bu_per_sc)"),
    date_from: str = Query(..., description="ISO YYYY-MM-DD start"),
    date_to: str | None = Query(None, description="ISO end; None = latest"),
):
    """Decompose ΔP_local into FX vs CBOT vs basis contributions.

    Tells you 'preço caiu por câmbio, por CBOT, ou porque o basis afundou?'
    Quantifies each in R$/sc and as % of the total move.
    """
    return _handle_query(
        attribution_service.attribute_change,
        commodity=commodity, location=location,
        futures_indicator=futures_indicator,
        date_from=date_from, date_to=date_to,
    )


@router.get("/anomaly")
def get_anomaly(
    indicator: str = Query(...),
    location: str | None = Query(None),
    target_date: str | None = Query(None),
    window_days: int = Query(60, ge=10, le=365),
    z_threshold: float = Query(3.0, ge=1.0, le=10.0),
):
    """Z-score anomaly detection vs trailing rolling window.

    Flags potential typos in scraped data OR genuinely large market moves.
    """
    return _handle_query(
        anomaly_service.detect_anomaly,
        indicator=indicator, location=location,
        target_date=target_date, window_days=window_days,
        z_threshold=z_threshold,
    )
