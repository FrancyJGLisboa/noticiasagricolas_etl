"""Multi-year seasonal averages with current-year comparison."""

from .. import database as db
from .query_builder import WhereBuilder


def get_seasonal(
    indicator: str,
    location: str | None = None,
    granularity: str = "monthly",
    measure: str = "price",
) -> dict:
    """Compute seasonal averages across years.

    granularity: 'monthly' or 'weekly'
    Returns per-period averages plus current year's values for comparison.
    """
    wb = WhereBuilder()
    wb.add("indicator", indicator)
    wb.add("location", location)
    wb.add("measure", measure)
    where, params = wb.build()

    if granularity == "weekly":
        period_expr = "WEEKOFYEAR(date)"
        period_name = "week"
    else:
        period_expr = "MONTH(date)"
        period_name = "month"

    # where is always non-empty here (indicator is required), but guard anyway
    not_null = f"{where} AND value IS NOT NULL" if where else "WHERE value IS NOT NULL"

    sql_avg = f"""
        SELECT {period_expr} AS {period_name},
               AVG(value) AS avg_price,
               STDDEV(value) AS std_price,
               MIN(value) AS min_price,
               MAX(value) AS max_price,
               COUNT(*) AS data_points,
               COUNT(DISTINCT YEAR(date)) AS year_count
        FROM prices {not_null}
        GROUP BY {period_expr}
        ORDER BY {period_name}
    """
    averages = db.query(sql_avg, params)

    sql_current = f"""
        SELECT {period_expr} AS {period_name},
               AVG(value) AS current_avg,
               MIN(value) AS current_min,
               MAX(value) AS current_max
        FROM prices {not_null}
        AND YEAR(date) = YEAR(CURRENT_DATE)
        GROUP BY {period_expr}
        ORDER BY {period_name}
    """
    current = db.query(sql_current, params)
    current_map = {r[period_name]: r for r in current}

    for row in averages:
        cur = current_map.get(row[period_name], {})
        row["current_avg"] = cur.get("current_avg")
        row["current_min"] = cur.get("current_min")
        row["current_max"] = cur.get("current_max")
        if row["avg_price"] and cur.get("current_avg"):
            row["vs_avg_pct"] = (cur["current_avg"] - row["avg_price"]) / row["avg_price"] * 100
        else:
            row["vs_avg_pct"] = None

    return {
        "indicator": indicator,
        "granularity": granularity,
        "location": location,
        "data": averages,
    }
