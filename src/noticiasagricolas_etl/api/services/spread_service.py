"""Regional price spread and rankings."""

from .. import database as db


def _build_date_filter(indicator: str, date: str | None = None,
                       date_from: str | None = None,
                       date_to: str | None = None,
                       extra_base: str = "measure = 'price' AND location IS NOT NULL") -> tuple[str, list]:
    """Build WHERE clause for spread queries. Returns (where_str, params).

    The returned WHERE always starts with 'WHERE indicator = ? AND ...'
    """
    clauses = ["indicator = ?", extra_base]
    params: list = [indicator]

    if date:
        clauses.append("date = ?")
        params.append(date)
    elif date_from or date_to:
        if date_from:
            clauses.append("date >= ?")
            params.append(str(date_from))
        if date_to:
            clauses.append("date <= ?")
            params.append(str(date_to))
    else:
        # Latest date via subquery — needs indicator param again
        clauses.append(
            "date = (SELECT MAX(date) FROM prices "
            "WHERE indicator = ? AND measure = 'price' AND location IS NOT NULL)"
        )
        params.append(indicator)

    return "WHERE " + " AND ".join(clauses), params


def get_regional_spread(
    indicator: str,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Price dispersion across locations: mean, std, IQR, by-state breakdown."""
    base_extra = "measure = 'price' AND location IS NOT NULL AND value IS NOT NULL"
    where, params = _build_date_filter(indicator, date, date_from, date_to, extra_base=base_extra)

    sql = f"""
        SELECT
            AVG(value) AS mean_price,
            STDDEV(value) AS std_price,
            MEDIAN(value) AS median_price,
            QUANTILE_CONT(value, 0.25) AS q25,
            QUANTILE_CONT(value, 0.75) AS q75,
            MIN(value) AS min_price,
            MAX(value) AS max_price,
            COUNT(*) AS location_count,
            MIN(date) AS from_date,
            MAX(date) AS to_date
        FROM prices {where}
    """
    overall = db.query(sql, params)
    stats = overall[0] if overall else {}
    if stats.get("q25") is not None and stats.get("q75") is not None:
        stats["iqr"] = stats["q75"] - stats["q25"]
    for k in ("from_date", "to_date"):
        if stats.get(k):
            stats[k] = str(stats[k])

    state_extra = "measure = 'price' AND location IS NOT NULL AND value IS NOT NULL AND state IS NOT NULL"
    state_where, state_params = _build_date_filter(indicator, date, date_from, date_to, extra_base=state_extra)

    sql_state = f"""
        SELECT state,
               AVG(value) AS mean_price,
               STDDEV(value) AS std_price,
               MIN(value) AS min_price,
               MAX(value) AS max_price,
               COUNT(*) AS location_count
        FROM prices {state_where}
        GROUP BY state
        ORDER BY mean_price ASC
    """
    by_state = db.query(sql_state, state_params)

    return {
        "indicator": indicator,
        "overall": stats,
        "by_state": by_state,
    }


def get_rankings(
    indicator: str,
    date: str | None = None,
    measure: str = "price",
    limit: int = 50,
) -> dict:
    """Locations ranked by price (cheapest to most expensive)."""
    use_date = date if (date and date != "latest") else None

    clauses = ["indicator = ?", "measure = ?", "location IS NOT NULL", "value IS NOT NULL"]
    params: list = [indicator, measure]

    if use_date:
        clauses.append("date = ?")
        params.append(use_date)
    else:
        clauses.append(
            "date = (SELECT MAX(date) FROM prices "
            "WHERE indicator = ? AND measure = ? AND location IS NOT NULL)"
        )
        params.extend([indicator, measure])

    where = "WHERE " + " AND ".join(clauses)

    sql = f"""
        SELECT location, state, value, unit, currency, date
        FROM prices {where}
        ORDER BY value ASC
        LIMIT ?
    """
    params.append(limit)
    rows = db.query(sql, params)
    for i, row in enumerate(rows):
        row["rank"] = i + 1
        row["date"] = str(row["date"])

    return {
        "indicator": indicator,
        "date": rows[0]["date"] if rows else date,
        "rankings": rows,
    }
