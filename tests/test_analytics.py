"""Tests for backend/analytics.py.

Sample data (see conftest.py) has three valid rows:
    T1  2026-01  Desk   North  200
    T2  2026-02  Chair  South  130
    T3  2026-03  Desk   East    90
"""

import pytest

from backend import analytics
from backend.database import CSV_PATH, build_database


@pytest.fixture
def conn(sample_db, connect):
    return connect(sample_db)


# ---------- sample data ----------

def test_total_revenue(conn):
    assert analytics.total_revenue(conn) == {"total_revenue": 420.0, "transactions": 3}


def test_top_product_and_ranking(conn):
    result = analytics.top_product(conn)
    assert result["top"] == ["Desk"]
    assert result["top_revenue"] == 290.0
    assert [(r["name"], r["revenue"]) for r in result["ranking"]] == [("Desk", 290.0), ("Chair", 130.0)]


def test_top_region(conn):
    result = analytics.top_region(conn)
    assert result["top"] == ["North"]
    assert result["top_revenue"] == 200.0


def test_monthly_trend(conn):
    trend = analytics.monthly_revenue_trend(conn)
    assert [(m["month"], m["revenue"]) for m in trend] == [
        ("2026-01", 200.0), ("2026-02", 130.0), ("2026-03", 90.0)]
    assert trend[0]["label"] == "January 2026"


def test_compare_months(conn):
    result = analytics.compare_months(conn, "2026-01", "2026-03")
    assert [m["revenue"] for m in result["months"]] == [200.0, 90.0]
    assert result["difference"] == -110.0
    assert result["percent_change"] == -55.0


def test_compare_months_uses_earlier_month_as_baseline(conn):
    assert analytics.compare_months(conn, "2026-03", "2026-01") == \
        analytics.compare_months(conn, "2026-01", "2026-03")


def test_compare_month_without_any_records_raises(conn):
    with pytest.raises(analytics.NoDataError, match="December 2025"):
        analytics.compare_months(conn, "2025-12", "2026-01")


def test_unsupported_grouping_column_is_rejected(conn):
    with pytest.raises(ValueError):
        analytics._revenue_ranking(conn, "product; DROP TABLE sales")


# ---------- edge cases ----------

def test_month_with_only_invalid_rows_shows_zero_revenue(make_db, connect):
    conn = connect(make_db([
        "A1,10-01-2026,Desk,Furniture,North,Online,1,100,0,Completed",
        "A2,10-02-2026,Desk,Furniture,North,Online,1,100,0,Returned",
        "A3,10-03-2026,Desk,Furniture,North,Online,2,100,0,Completed",
    ]))
    trend = analytics.monthly_revenue_trend(conn)
    assert [(m["month"], m["revenue"]) for m in trend] == [
        ("2026-01", 100.0), ("2026-02", 0.0), ("2026-03", 200.0)]

    # February has records (so comparison is allowed) but zero valid revenue,
    # so the percentage change from February is undefined.
    result = analytics.compare_months(conn, "2026-02", "2026-03")
    assert result["difference"] == 200.0
    assert result["percent_change"] is None


def test_gap_month_without_records_is_filled_with_zero(make_db, connect):
    conn = connect(make_db([
        "A1,10-01-2026,Desk,Furniture,North,Online,1,100,0,Completed",
        "A2,10-03-2026,Desk,Furniture,North,Online,1,100,0,Completed",
    ]))
    trend = analytics.monthly_revenue_trend(conn)
    assert [m["month"] for m in trend] == ["2026-01", "2026-02", "2026-03"]
    assert trend[1]["revenue"] == 0.0
    with pytest.raises(analytics.NoDataError):
        analytics.compare_months(conn, "2026-01", "2026-02")


def test_tie_for_top_product(make_db, connect):
    conn = connect(make_db([
        "A1,10-01-2026,Desk,Furniture,North,Online,1,100,0,Completed",
        "A2,10-01-2026,Chair,Furniture,South,Online,2,50,0,Completed",
    ]))
    assert analytics.top_product(conn)["top"] == ["Chair", "Desk"]


def test_no_valid_sales(make_db, connect):
    conn = connect(make_db([
        "A1,10-01-2026,Desk,Furniture,North,Online,1,100,0,Returned",
    ]))
    assert analytics.total_revenue(conn) == {"total_revenue": 0.0, "transactions": 0}
    assert analytics.top_product(conn)["top"] == []
    assert analytics.monthly_revenue_trend(conn) == [
        {"month": "2026-01", "label": "January 2026", "revenue": 0.0, "transactions": 0}]


def test_available_years(make_db, connect):
    conn = connect(make_db([
        "A1,10-12-2025,Desk,Furniture,North,Online,1,100,0,Completed",
        "A2,10-01-2026,Desk,Furniture,North,Online,1,100,0,Completed",
    ]))
    assert analytics.available_years(conn) == [2025, 2026]


# ---------- the real data/sales.csv ----------
# Expected figures were cross-checked independently with Pandas on the raw CSV.

@pytest.fixture
def real_conn(db_path, connect):
    build_database(CSV_PATH, db_path)
    return connect(db_path)


def test_real_total_revenue(real_conn):
    assert analytics.total_revenue(real_conn) == {"total_revenue": 1439200.0, "transactions": 48}


def test_real_top_product(real_conn):
    result = analytics.top_product(real_conn)
    assert result["top"] == ["Monitor"]
    assert result["top_revenue"] == 473000.0


def test_real_top_region(real_conn):
    result = analytics.top_region(real_conn)
    assert result["top"] == ["South"]
    assert result["top_revenue"] == 411200.0


def test_real_monthly_trend(real_conn):
    trend = analytics.monthly_revenue_trend(real_conn)
    assert [(m["month"], m["revenue"]) for m in trend] == [
        ("2026-01", 210250.0), ("2026-02", 234600.0), ("2026-03", 223900.0),
        ("2026-04", 240700.0), ("2026-05", 318500.0), ("2026-06", 211250.0)]


def test_real_compare_march_april(real_conn):
    result = analytics.compare_months(real_conn, "2026-03", "2026-04")
    assert [m["revenue"] for m in result["months"]] == [223900.0, 240700.0]
    assert result["difference"] == 16800.0
    assert result["percent_change"] == 7.5
