"""Basis computation: physical price minus futures price."""

from .. import database as db


def compute(
    commodity: str,
    physical_indicator: str,
    futures_indicator: str,
    location: str | None = None,
    contract: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Compute basis = physical - futures for matching dates.

    Returns time series with basis value, percentage, and historical percentile.
    """
    # Build physical CTE filters and params
    phys_clauses = ["indicator = ?", "measure = 'price'"]
    phys_params: list = [physical_indicator]
    if location:
        phys_clauses.append("location = ?")
        phys_params.append(location)
    if date_from:
        phys_clauses.append("date >= ?")
        phys_params.append(str(date_from))
    if date_to:
        phys_clauses.append("date <= ?")
        phys_params.append(str(date_to))

    # Build futures CTE filters and params
    fut_clauses = ["indicator = ?", "measure = 'price'"]
    fut_params: list = [futures_indicator]
    if contract:
        fut_clauses.append("contract = ?")
        fut_params.append(contract)
    if date_from:
        fut_clauses.append("date >= ?")
        fut_params.append(str(date_from))
    if date_to:
        fut_clauses.append("date <= ?")
        fut_params.append(str(date_to))

    phys_where = "WHERE " + " AND ".join(phys_clauses)
    fut_where = "WHERE " + " AND ".join(fut_clauses)

    sql = f"""
        WITH physical AS (
            SELECT date, location, value AS physical_price, unit, currency
            FROM prices
            {phys_where}
        ),
        futures AS (
            SELECT date, value AS futures_price, contract, unit AS fut_unit,
                   currency AS fut_currency
            FROM prices
            {fut_where}
        ),
        basis_raw AS (
            SELECT
                ph.date, ph.location, ph.physical_price,
                fu.futures_price, fu.contract AS futures_contract,
                ph.physical_price - fu.futures_price AS basis,
                CASE WHEN fu.futures_price != 0
                     THEN (ph.physical_price - fu.futures_price)
                          / fu.futures_price * 100
                     ELSE NULL END AS basis_pct,
                ph.currency, ph.unit
            FROM physical ph
            INNER JOIN futures fu ON ph.date = fu.date
        )
        SELECT *, PERCENT_RANK() OVER (ORDER BY basis) AS basis_percentile
        FROM basis_raw
        ORDER BY date DESC
    """
    params = phys_params + fut_params
    rows = db.query(sql, params)

    basis_values = [r["basis"] for r in rows if r["basis"] is not None]
    summary = {}
    if basis_values:
        summary = {
            "mean_basis": sum(basis_values) / len(basis_values),
            "min_basis": min(basis_values),
            "max_basis": max(basis_values),
            "current_basis": basis_values[0],
            "current_percentile": rows[0]["basis_percentile"],
            "data_points": len(basis_values),
        }

    for row in rows:
        row["date"] = str(row["date"])

    return {
        "commodity": commodity,
        "physical_indicator": physical_indicator,
        "futures_indicator": futures_indicator,
        "summary": summary,
        "data": rows,
    }
