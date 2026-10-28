"""Read-only transaction browsing for the Data Explorer.

Every row of the `sales` table is returned (valid and invalid), so users can
see exactly what was excluded and why. Revenue is NOT recalculated here: it
is joined from the `valid_sales` view, so invalid rows have no revenue.

Safety:
  * every user-supplied filter value is a bound `?` parameter;
  * the sort column and direction come from fixed whitelists, never from user text.
"""

import sqlite3

# API sort key -> SQL expression (whitelist; user text is never inserted into SQL)
SORT_COLUMNS = {
    "order_date": "s.order_date",
    "transaction_id": "s.transaction_id",
    "product": "s.product",
    "region": "s.region",
    "quantity": "s.quantity",
    "unit_price": "s.unit_price",
    "revenue": "v.revenue",
    "status": "s.status",
}

FROM_CLAUSE = """
FROM sales AS s
LEFT JOIN valid_sales AS v ON v.source_row = s.source_row
"""


def _escape_like(text: str) -> str:
    """Make % and _ in user text match literally inside LIKE (escape character: !)."""
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def build_filters(search=None, region=None, product=None, status=None, month=None):
    """Return (WHERE clause, parameters) for the chosen filters."""
    conditions, params = [], []
    if search:
        pattern = f"%{_escape_like(search)}%"
        conditions.append("(s.transaction_id LIKE ? ESCAPE '!' OR s.product LIKE ? ESCAPE '!')")
        params += [pattern, pattern]
    if region:
        conditions.append("s.region = ?")
        params.append(region)
    if product:
        conditions.append("s.product = ?")
        params.append(product)
    if status:
        conditions.append("s.status = ?")
        params.append(status)
    if month:
        conditions.append("strftime('%Y-%m', s.order_date) = ?")
        params.append(month)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


def search_transactions(conn: sqlite3.Connection, *, search=None, region=None, product=None,
                        status=None, month=None, sort="order_date", order="asc",
                        limit=25, offset=0) -> dict:
    if sort not in SORT_COLUMNS or order not in ("asc", "desc"):
        raise ValueError("Unsupported sort option")
    where, params = build_filters(search, region, product, status, month)

    totals = conn.execute(
        f"""
        SELECT COUNT(*)                     AS matching,
               COALESCE(SUM(s.is_valid), 0) AS valid,
               COALESCE(SUM(v.revenue), 0)  AS revenue
        {FROM_CLAUSE} {where}
        """,
        params,
    ).fetchone()

    rows = conn.execute(
        f"""
        SELECT s.source_row, s.transaction_id, s.order_date_raw, s.order_date, s.product,
               s.category, s.region, s.sales_channel, s.quantity, s.unit_price,
               s.discount_amount, s.status, s.is_valid, s.invalid_reason, v.revenue
        {FROM_CLAUSE} {where}
        ORDER BY {SORT_COLUMNS[sort]} {order.upper()} NULLS LAST, s.source_row
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    return {
        "matching": totals["matching"],
        "matching_valid": totals["valid"],
        "matching_excluded": totals["matching"] - totals["valid"],
        "matching_revenue": round(float(totals["revenue"]), 2),
        "limit": limit,
        "offset": offset,
        "transactions": [
            {**dict(row), "is_valid": bool(row["is_valid"])} for row in rows
        ],
    }


def filter_options(conn: sqlite3.Connection) -> dict:
    """Distinct values for the explorer's dropdowns (all rows, valid or not)."""
    def distinct(expression: str) -> list:
        return [r[0] for r in conn.execute(
            f"SELECT DISTINCT {expression} AS value FROM sales "
            f"WHERE {expression} IS NOT NULL AND {expression} <> '' ORDER BY value")]

    return {
        "regions": distinct("region"),
        "products": distinct("product"),
        "statuses": distinct("status"),
        "months": distinct("strftime('%Y-%m', order_date)"),
    }
