"""The five analytics operations.

Every number comes from a fixed SQL query against the `valid_sales` view
(which already excludes returned orders, zero quantities, missing prices, ...).
User input is only ever passed as a bound `?` parameter, never pasted into SQL.
"""

import sqlite3
from calendar import month_name


class NoDataError(Exception):
    """Raised when the requested period has no sales records at all."""


def _round(value) -> float:
    return round(float(value or 0), 2)


def month_label(month: str) -> str:
    """'2026-03' -> 'March 2026'."""
    year, month_number = month.split("-")
    return f"{month_name[int(month_number)]} {year}"


def total_revenue(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(revenue), 0) AS total_revenue,
               COUNT(*)                  AS transactions
        FROM valid_sales
        """
    ).fetchone()
    return {"total_revenue": _round(row["total_revenue"]), "transactions": row["transactions"]}


def _revenue_ranking(conn: sqlite3.Connection, column: str) -> list[dict]:
    """Revenue per product or per region, highest first.

    `column` is chosen from a fixed whitelist (never from user text), because
    SQL column names cannot be passed as `?` parameters.
    """
    if column not in ("product", "region"):
        raise ValueError(f"Unsupported grouping column: {column}")
    rows = conn.execute(
        f"""
        SELECT {column}       AS name,
               SUM(revenue)   AS revenue,
               COUNT(*)       AS transactions
        FROM valid_sales
        GROUP BY {column}
        ORDER BY revenue DESC, name
        """
    ).fetchall()
    return [
        {"name": r["name"], "revenue": _round(r["revenue"]), "transactions": r["transactions"]}
        for r in rows
    ]


def _top_of(ranking: list[dict]) -> dict:
    """Return the leader(s); more than one name means a tie."""
    if not ranking:
        return {"top": [], "top_revenue": 0.0, "ranking": []}
    best = ranking[0]["revenue"]
    leaders = [item["name"] for item in ranking if item["revenue"] == best]
    return {"top": leaders, "top_revenue": best, "ranking": ranking}


def top_product(conn: sqlite3.Connection) -> dict:
    return _top_of(_revenue_ranking(conn, "product"))


def top_region(conn: sqlite3.Connection) -> dict:
    return _top_of(_revenue_ranking(conn, "region"))


def _months_between(first: str, last: str) -> list[str]:
    """All months from first to last inclusive, e.g. ['2026-01', '2026-02', ...]."""
    year, month = map(int, first.split("-"))
    end_year, end_month = map(int, last.split("-"))
    months = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def monthly_revenue_trend(conn: sqlite3.Connection) -> list[dict]:
    """Revenue for every month in the data range.

    Months that have records but no valid sales are shown as 0 instead of
    disappearing from the chart.
    """
    span = conn.execute(
        """
        SELECT MIN(strftime('%Y-%m', order_date)) AS first_month,
               MAX(strftime('%Y-%m', order_date)) AS last_month
        FROM sales
        WHERE order_date IS NOT NULL
        """
    ).fetchone()
    if span["first_month"] is None:
        return []

    rows = conn.execute(
        """
        SELECT order_month, SUM(revenue) AS revenue, COUNT(*) AS transactions
        FROM valid_sales
        GROUP BY order_month
        """
    ).fetchall()
    by_month = {r["order_month"]: r for r in rows}

    trend = []
    for month in _months_between(span["first_month"], span["last_month"]):
        row = by_month.get(month)
        trend.append({
            "month": month,
            "label": month_label(month),
            "revenue": _round(row["revenue"]) if row else 0.0,
            "transactions": row["transactions"] if row else 0,
        })
    return trend


def month_has_records(conn: sqlite3.Connection, month: str) -> bool:
    """True if the CSV contains ANY row (valid or not) for this 'YYYY-MM' month."""
    row = conn.execute(
        "SELECT 1 FROM sales WHERE strftime('%Y-%m', order_date) = ? LIMIT 1",
        (month,),
    ).fetchone()
    return row is not None


def month_revenue(conn: sqlite3.Connection, month: str) -> dict:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(revenue), 0) AS revenue, COUNT(*) AS transactions
        FROM valid_sales
        WHERE order_month = ?
        """,
        (month,),
    ).fetchone()
    return {
        "month": month,
        "label": month_label(month),
        "revenue": _round(row["revenue"]),
        "transactions": row["transactions"],
    }


def compare_months(conn: sqlite3.Connection, month_a: str, month_b: str) -> dict:
    """Compare two 'YYYY-MM' months. The earlier month is used as the baseline."""
    missing = [m for m in (month_a, month_b) if not month_has_records(conn, m)]
    if missing:
        names = ", ".join(month_label(m) for m in missing)
        raise NoDataError(f"There are no sales records for {names} in the dataset.")

    earlier, later = sorted([month_a, month_b])
    first = month_revenue(conn, earlier)
    second = month_revenue(conn, later)
    difference = _round(second["revenue"] - first["revenue"])
    # Percentage change is undefined when the baseline revenue is zero.
    percent_change = (
        round(difference / first["revenue"] * 100, 2) if first["revenue"] else None
    )
    return {
        "months": [first, second],
        "difference": difference,
        "percent_change": percent_change,
    }


def available_years(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT CAST(strftime('%Y', order_date) AS INTEGER) AS year
        FROM sales
        WHERE order_date IS NOT NULL
        ORDER BY year
        """
    ).fetchall()
    return [r["year"] for r in rows]


def revenue_share(part: float, total: float) -> float | None:
    """Percentage of total revenue, or None when the total is zero."""
    return round(part / total * 100, 2) if total else None


def dashboard_summary(conn: sqlite3.Connection) -> dict:
    """Headline figures for the dashboard, built only from the queries above."""
    totals = total_revenue(conn)
    products = top_product(conn)
    regions = top_region(conn)
    trend = monthly_revenue_trend(conn)

    def leader(result: dict) -> dict:
        return {
            "names": result["top"],
            "revenue": result["top_revenue"],
            "share_pct": revenue_share(result["top_revenue"], totals["total_revenue"]),
        }

    return {
        "total_revenue": totals["total_revenue"],
        "transactions": totals["transactions"],
        "top_product": leader(products),
        "top_region": leader(regions),
        # Same rule as the /ask trend answer: zero-revenue months are included.
        "best_month": max(trend, key=lambda m: m["revenue"]) if trend else None,
        "weakest_month": min(trend, key=lambda m: m["revenue"]) if trend else None,
        "monthly_trend": trend,
        "product_ranking": products["ranking"],
        "region_ranking": regions["ranking"],
    }
