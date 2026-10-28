"""Tests for backend/database.py."""

from backend.database import build_database, get_connection


def test_all_rows_loaded_and_summary_correct(sample_csv, db_path):
    summary = build_database(sample_csv, db_path)
    assert summary["total_rows"] == 11
    assert summary["valid_rows"] == 3
    assert summary["excluded_rows"] == 8
    excluded_ids = [row["transaction_id"] for row in summary["excluded"]]
    assert excluded_ids == ["T4", "T5", "T6", "T7", "T8", "T9", "T1", "T10"]


def test_valid_sales_view_only_contains_valid_rows(sample_csv, db_path):
    build_database(sample_csv, db_path)
    with get_connection(db_path) as conn:
        ids = [r["transaction_id"] for r in conn.execute(
            "SELECT transaction_id FROM valid_sales ORDER BY transaction_id")]
    assert ids == ["T1", "T2", "T3"]


def test_revenue_is_quantity_times_price_minus_fixed_discount(sample_csv, db_path):
    build_database(sample_csv, db_path)
    with get_connection(db_path) as conn:
        revenue = {r["transaction_id"]: r["revenue"] for r in conn.execute(
            "SELECT transaction_id, revenue FROM valid_sales")}
        total = conn.execute("SELECT SUM(revenue) FROM valid_sales").fetchone()[0]
    assert revenue == {"T1": 200, "T2": 130, "T3": 90}  # 2*100-0, 3*50-20, 1*100-10
    assert total == 420


def test_order_month_is_derived_from_iso_date(sample_csv, db_path):
    build_database(sample_csv, db_path)
    with get_connection(db_path) as conn:
        months = [r[0] for r in conn.execute(
            "SELECT order_month FROM valid_sales ORDER BY order_date")]
    assert months == ["2026-01", "2026-02", "2026-03"]


def test_missing_price_stored_as_null_not_zero(sample_csv, db_path):
    build_database(sample_csv, db_path)
    with get_connection(db_path) as conn:
        price = conn.execute(
            "SELECT unit_price FROM sales WHERE transaction_id = 'T6'").fetchone()[0]
    assert price is None


def test_rebuilding_does_not_duplicate_rows(sample_csv, db_path):
    build_database(sample_csv, db_path)
    summary = build_database(sample_csv, db_path)
    assert summary["total_rows"] == 11


def test_real_csv_loads_into_database(db_path):
    summary = build_database(db_path=db_path)
    assert summary["total_rows"] == 51
    assert summary["valid_rows"] == 48
    assert {r["transaction_id"] for r in summary["excluded"]} == {"TXN0033", "TXN0034", "TXN0051"}
