"""Core price query service."""

from collections import defaultdict

from .. import database as db
from .query_builder import WhereBuilder


def _serialize_dates(rows: list[dict]) -> list[dict]:
    for row in rows:
        for key in ("date", "first_date", "last_date"):
            if row.get(key) is not None:
                row[key] = str(row[key])
    return rows


def get_prices(
    commodity: str | None = None,
    indicator: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    state: str | None = None,
    measure: str | None = None,
    market_type: str | None = None,
    contract: str | None = None,
    currency: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> dict:
    """Query prices with full filtering. Returns {data, total, limit, offset}."""
    wb = WhereBuilder()
    wb.add("commodity", commodity)
    wb.add("indicator", indicator)
    wb.add("location", location)
    wb.add("state", state)
    wb.add("measure", measure)
    wb.add("market_type", market_type)
    wb.add("contract", contract)
    wb.add("currency", currency)
    wb.add_date_range(date_from=date_from, date_to=date_to)
    where, params = wb.build()

    total = db.query(f"SELECT COUNT(*) AS total FROM prices {where}", params)[0]["total"]

    sql = f"""
        SELECT date, commodity, indicator, indicator_name, location,
               contract_month, column_name, value, unit,
               measure, currency, unit_std, price_basis, contract, state, market_type
        FROM prices {where}
        ORDER BY date DESC, indicator, location
        LIMIT ? OFFSET ?
    """
    rows = _serialize_dates(db.query(sql, params + [limit, offset]))
    return {"data": rows, "total": total, "limit": limit, "offset": offset}


def get_latest(
    commodity: str | None = None,
    indicator: str | None = None,
    measure: str = "price",
) -> dict:
    """Get most recent prices for a commodity/indicator."""
    # Build outer filter clauses and subquery clauses with separate param lists
    outer_clauses: list[str] = []
    outer_params: list = []
    sub_clauses: list[str] = []
    sub_params: list = []

    for col, val in [("commodity", commodity), ("indicator", indicator), ("measure", measure)]:
        if val is not None:
            outer_clauses.append(f"{col} = ?")
            outer_params.append(val)
            sub_clauses.append(f"{col} = ?")
            sub_params.append(val)

    sub_where = "WHERE " + " AND ".join(sub_clauses) if sub_clauses else ""
    if outer_clauses:
        outer_where = "WHERE " + " AND ".join(outer_clauses) + f" AND date = (SELECT MAX(date) FROM prices {sub_where})"
    else:
        outer_where = "WHERE date = (SELECT MAX(date) FROM prices)"

    sql = f"""
        SELECT date, commodity, indicator, indicator_name,
               location, contract_month, column_name, value, unit,
               measure, currency, unit_std, price_basis, contract, state, market_type
        FROM prices {outer_where}
        ORDER BY indicator, location
    """
    rows = _serialize_dates(db.query(sql, outer_params + sub_params))
    return {"data": rows, "date": rows[0]["date"] if rows else None}


def get_timeseries(
    indicator: str,
    location: str | None = None,
    measure: str = "price",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Get time series for charting: date + value pivoted by location."""
    wb = WhereBuilder()
    wb.add("indicator", indicator)
    wb.add("location", location)
    wb.add("measure", measure)
    wb.add_date_range(date_from=date_from, date_to=date_to)
    where, params = wb.build()

    rows = db.query(
        f"SELECT date, location, value FROM prices {where} ORDER BY date, location",
        params,
    )

    dates_map: dict[str, dict] = defaultdict(dict)
    locations_set: set[str] = set()
    for row in rows:
        d = str(row["date"])
        loc = row["location"] or "default"
        dates_map[d][loc] = row["value"]
        locations_set.add(loc)

    locations = sorted(locations_set)
    series = [
        {"date": d, **{loc: vals.get(loc) for loc in locations}}
        for d, vals in sorted(dates_map.items())
    ]
    return {"indicator": indicator, "locations": locations, "series": series}


def get_locations(
    commodity: str | None = None,
    state: str | None = None,
) -> list[dict]:
    """Get distinct locations with optional commodity/state filter."""
    wb = WhereBuilder()
    wb.add("commodity", commodity)
    wb.add("state", state)
    where, params = wb.build()

    not_null = "AND location IS NOT NULL" if where else "WHERE location IS NOT NULL"
    sql = f"""
        SELECT DISTINCT location, state, commodity, COUNT(*) AS record_count
        FROM prices {where} {not_null}
        GROUP BY location, state, commodity
        ORDER BY commodity, state, location
    """
    return db.query(sql, params)


def get_contracts(indicator: str | None = None) -> list[dict]:
    """Get available futures contract months."""
    wb = WhereBuilder()
    wb.add("indicator", indicator)
    where, params = wb.build()

    not_null = "AND contract IS NOT NULL" if where else "WHERE contract IS NOT NULL"
    sql = f"""
        SELECT DISTINCT indicator, contract, contract_month,
               MIN(date) AS first_date, MAX(date) AS last_date,
               COUNT(*) AS record_count
        FROM prices {where} {not_null}
        GROUP BY indicator, contract, contract_month
        ORDER BY indicator, contract DESC
    """
    return _serialize_dates(db.query(sql, params))
