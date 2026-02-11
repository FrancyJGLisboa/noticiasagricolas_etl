"""Futures curve: all active contracts on a date."""

from .. import database as db


def get_curve(
    indicator: str,
    date: str | None = None,
) -> dict:
    """Get all active contracts for an indicator on a given date.

    If date is None, uses the most recent available date.
    Returns contracts sorted by contract month with contango/backwardation label.
    """
    clauses = ["indicator = ?", "contract IS NOT NULL", "measure = 'price'"]
    params: list = [indicator]

    if date:
        clauses.append("date = ?")
        params.append(date)
    else:
        clauses.append(
            "date = (SELECT MAX(date) FROM prices "
            "WHERE indicator = ? AND contract IS NOT NULL AND measure = 'price')"
        )
        params.append(indicator)

    where = "WHERE " + " AND ".join(clauses)

    sql = f"""
        SELECT date, contract, contract_month, value, unit, currency
        FROM prices {where}
        ORDER BY contract ASC
    """
    rows = db.query(sql, params)

    # Determine curve structure
    structure = "flat"
    if len(rows) >= 2:
        prices = [r["value"] for r in rows if r["value"] is not None]
        if len(prices) >= 2:
            if prices[-1] > prices[0]:
                structure = "contango"
            elif prices[-1] < prices[0]:
                structure = "backwardation"

    for row in rows:
        row["date"] = str(row["date"])

    return {
        "indicator": indicator,
        "date": rows[0]["date"] if rows else date,
        "structure": structure,
        "contracts": rows,
    }
