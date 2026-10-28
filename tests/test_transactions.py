"""Tests for backend/transactions.py and the /transactions endpoints.

Sample data (see conftest.py): 11 rows. Valid: T1 (200), T2 (130), T3 (90).
"""

import sqlite3

import pytest

from backend import transactions
from backend.database import CSV_PATH, build_database


@pytest.fixture
def conn(sample_db, connect):
    return connect(sample_db)


def ids(result):
    return [t["transaction_id"] for t in result["transactions"]]


# ---------- module ----------

def test_all_rows_returned_including_invalid(conn):
    result = transactions.search_transactions(conn, limit=100)
    assert result["matching"] == 11
    assert result["matching_valid"] == 3
    assert result["matching_excluded"] == 8
    assert result["matching_revenue"] == 420.0


def test_invalid_rows_have_no_revenue_and_keep_their_reason(conn):
    rows = {t["source_row"]: t for t in transactions.search_transactions(conn, limit=100)["transactions"]}
    returned = next(t for t in rows.values() if t["transaction_id"] == "T4")
    assert returned["is_valid"] is False
    assert returned["revenue"] is None
    assert "Returned" in returned["invalid_reason"]
    missing_price = next(t for t in rows.values() if t["transaction_id"] == "T6")
    assert missing_price["unit_price"] is None  # never shown as 0
    valid = next(t for t in rows.values() if t["transaction_id"] == "T2")
    assert valid["revenue"] == 130.0 and valid["is_valid"] is True


def test_original_values_are_returned_unchanged(conn):
    row = next(t for t in transactions.search_transactions(conn, limit=100)["transactions"]
               if t["transaction_id"] == "T2")
    assert row["order_date_raw"] == "15/02/2026"  # original text, not reformatted
    assert row["order_date"] == "2026-02-15"


@pytest.mark.parametrize(
    "filters, expected",
    [
        ({"region": "South"}, ["T2", "T10"]),
        ({"product": "Chair"}, ["T5", "T6", "T10", "T2"]),
        ({"status": "Returned"}, ["T4"]),
        ({"month": "2026-03"}, ["T3"]),
        ({"search": "t1"}, ["T1", "T1", "T10"]),          # case-insensitive ID match
        ({"search": "chair"}, ["T5", "T6", "T10", "T2"]),  # product match
        ({"search": "desk", "region": "North", "status": "Completed"},
         ["T1", "T8", "T9", "T1", "T7"]),
    ],
)
def test_filters_and_search(conn, filters, expected):
    result = transactions.search_transactions(conn, **filters, limit=100)
    assert sorted(ids(result)) == sorted(expected)
    assert result["matching"] == len(expected)


def test_filters_combine_with_and(conn):
    result = transactions.search_transactions(conn, product="Desk", month="2026-01",
                                              status="Completed", limit=100)
    # Desk + January + Completed: T1, T8, T9 and the duplicate T1 (T7 has an unreadable date)
    assert sorted(ids(result)) == ["T1", "T1", "T8", "T9"]
    assert result["matching_valid"] == 1
    assert result["matching_revenue"] == 200.0


def test_like_wildcards_in_search_are_literal(conn):
    assert transactions.search_transactions(conn, search="%")["matching"] == 0
    assert transactions.search_transactions(conn, search="_")["matching"] == 0


def test_sql_text_in_filters_is_just_a_value(conn):
    result = transactions.search_transactions(conn, search="'; DROP TABLE sales; --",
                                              region="North' OR '1'='1")
    assert result["matching"] == 0
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 11


def test_sorting_and_missing_values_last(conn):
    asc = transactions.search_transactions(conn, sort="unit_price", order="asc", limit=100)
    desc = transactions.search_transactions(conn, sort="unit_price", order="desc", limit=100)
    assert asc["transactions"][-1]["unit_price"] is None
    assert desc["transactions"][-1]["unit_price"] is None
    assert desc["transactions"][0]["unit_price"] == 100.0
    by_revenue = transactions.search_transactions(conn, sort="revenue", order="desc", limit=3)
    assert ids(by_revenue) == ["T1", "T2", "T3"]


def test_unknown_sort_is_rejected(conn):
    with pytest.raises(ValueError):
        transactions.search_transactions(conn, sort="unit_price; DROP TABLE sales")
    with pytest.raises(ValueError):
        transactions.search_transactions(conn, order="sideways")


def test_pagination(conn):
    first = transactions.search_transactions(conn, sort="transaction_id", limit=4, offset=0)
    second = transactions.search_transactions(conn, sort="transaction_id", limit=4, offset=4)
    assert len(first["transactions"]) == 4 and len(second["transactions"]) == 4
    assert not set(t["source_row"] for t in first["transactions"]) & \
        set(t["source_row"] for t in second["transactions"])
    assert first["matching"] == second["matching"] == 11


def test_filter_options(conn):
    options = transactions.filter_options(conn)
    assert options["regions"] == ["East", "North", "South", "West"]
    assert options["products"] == ["Chair", "Desk"]
    assert options["statuses"] == ["Completed", "Returned"]
    assert options["months"] == ["2026-01", "2026-02", "2026-03"]


# ---------- API ----------

@pytest.fixture
def client(sample_db):
    from fastapi.testclient import TestClient

    from backend.main import app, get_db_path
    app.dependency_overrides[get_db_path] = lambda: sample_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_transactions_with_filters(client):
    body = client.get("/transactions", params={"region": "South", "status": "Completed"}).json()
    assert sorted(t["transaction_id"] for t in body["transactions"]) == ["T10", "T2"]
    assert body["matching_valid"] == 1


def test_api_blank_filters_are_ignored(client):
    assert client.get("/transactions", params={"region": "", "search": "  "}).json()["matching"] == 11


@pytest.mark.parametrize(
    "params",
    [{"sort": "bogus"}, {"order": "up"}, {"month": "2026-3"}, {"month": "March"},
     {"limit": 0}, {"limit": 501}, {"offset": -1}, {"search": "x" * 51}],
)
def test_api_rejects_invalid_parameters(client, params):
    assert client.get("/transactions", params=params).status_code == 422


def test_api_filter_options(client):
    assert client.get("/transactions/filters").json()["products"] == ["Chair", "Desk"]


def test_api_transactions_missing_database_is_503(tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app, get_db_path
    app.dependency_overrides[get_db_path] = lambda: tmp_path / "missing.db"
    try:
        assert TestClient(app).get("/transactions").status_code == 503
    finally:
        app.dependency_overrides.clear()


# ---------- real data ----------

def test_real_data_explorer_figures(db_path, connect):
    build_database(CSV_PATH, db_path)
    conn = connect(db_path)
    everything = transactions.search_transactions(conn, limit=500)
    assert everything["matching"] == 51
    assert everything["matching_valid"] == 48
    assert everything["matching_revenue"] == 1439200.0
    excluded = {t["transaction_id"]: t for t in everything["transactions"] if not t["is_valid"]}
    assert set(excluded) == {"TXN0033", "TXN0034", "TXN0051"}
    assert all(t["revenue"] is None for t in excluded.values())
    assert excluded["TXN0051"]["unit_price"] is None

    # Revenue per row equals the view's revenue (no second formula).
    direct = dict(sqlite3.connect(db_path).execute(
        "SELECT transaction_id, revenue FROM valid_sales").fetchall())
    for t in everything["transactions"]:
        if t["is_valid"]:
            assert t["revenue"] == direct[t["transaction_id"]]

    west_returned = transactions.search_transactions(conn, region="West", status="Returned")
    assert ids(west_returned) == ["TXN0033"]
    april_keyboard = transactions.search_transactions(conn, month="2026-04", product="Keyboard")
    assert ids(april_keyboard) == ["TXN0029", "TXN0034"]
    assert april_keyboard["matching_revenue"] == 18900.0
