"""Soybean crush margin calculation.

Crush margin = (farelo revenue + oleo revenue) - soja cost
Uses CBOT/B3 indicators with appropriate unit conversions.
"""

from .. import database as db


def _cte_clause(indicator: str, contract: str | None,
                date_from: str | None, date_to: str | None) -> tuple[str, list]:
    """Build WHERE clause and params for a single CTE."""
    clauses = ["indicator = ?", "measure = 'price'"]
    params: list = [indicator]
    if date_from:
        clauses.append("date >= ?")
        params.append(str(date_from))
    if date_to:
        clauses.append("date <= ?")
        params.append(str(date_to))
    if contract:
        clauses.append("contract = ?")
        params.append(contract)
    return "WHERE " + " AND ".join(clauses), params


def compute(
    contract: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    soja_indicator: str = "soja-b3-pregao-regular",
    farelo_indicator: str = "farelo-de-soja-b3",
    oleo_indicator: str = "oleo-de-soja-b3",
) -> dict:
    """Compute soybean crushing margin over time.

    Margin = farelo_value + oleo_value - soja_value (per date, same contract if applicable).
    """
    soja_where, soja_params = _cte_clause(soja_indicator, contract, date_from, date_to)
    farelo_where, farelo_params = _cte_clause(farelo_indicator, contract, date_from, date_to)
    oleo_where, oleo_params = _cte_clause(oleo_indicator, contract, date_from, date_to)

    sql = f"""
        WITH soja AS (
            SELECT date, value AS soja_price, contract, unit, currency
            FROM prices {soja_where}
        ),
        farelo AS (
            SELECT date, value AS farelo_price, contract
            FROM prices {farelo_where}
        ),
        oleo AS (
            SELECT date, value AS oleo_price, contract
            FROM prices {oleo_where}
        )
        SELECT
            s.date, s.soja_price, f.farelo_price, o.oleo_price,
            s.contract,
            (COALESCE(f.farelo_price, 0) + COALESCE(o.oleo_price, 0))
                - s.soja_price AS crush_margin,
            s.unit, s.currency
        FROM soja s
        LEFT JOIN farelo f ON s.date = f.date AND s.contract = f.contract
        LEFT JOIN oleo o ON s.date = o.date AND s.contract = o.contract
        WHERE s.soja_price IS NOT NULL
        ORDER BY s.date DESC
    """
    all_params = soja_params + farelo_params + oleo_params
    rows = db.query(sql, all_params)

    margins = [r["crush_margin"] for r in rows if r["crush_margin"] is not None]
    summary = {}
    if margins:
        summary = {
            "mean_margin": sum(margins) / len(margins),
            "current_margin": margins[0],
            "min_margin": min(margins),
            "max_margin": max(margins),
            "data_points": len(margins),
        }

    for row in rows:
        row["date"] = str(row["date"])

    return {
        "indicators": {
            "soja": soja_indicator,
            "farelo": farelo_indicator,
            "oleo": oleo_indicator,
        },
        "summary": summary,
        "data": rows,
    }
