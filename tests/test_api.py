"""Tests for backend/main.py (FastAPI endpoints)."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.database import CSV_PATH, build_database
from backend.main import app, get_db_path


@pytest.fixture
def client_for():
    """Return a TestClient whose API reads the given database file."""
    def _client(path):
        app.dependency_overrides[get_db_path] = lambda: path
        return TestClient(app)

    yield _client
    app.dependency_overrides.clear()


@pytest.fixture
def client(client_for, sample_db):
    return client_for(sample_db)


def ask(client, question):
    return client.post("/ask", json={"question": question})


# ---------- basic endpoints ----------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_data_quality(client):
    body = client.get("/data-quality").json()
    assert body["total_rows"] == 11
    assert body["valid_rows"] == 3
    assert body["excluded_rows"] == 8


# ---------- /ask: each intent ----------

def test_ask_total_revenue(client):
    response = ask(client, "What is the total revenue?")
    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "What is the total revenue?"
    assert body["intent"] == "total_revenue"
    assert body["answer"] == "Total revenue is 420.00 from 3 valid completed transactions."
    assert body["data"] == {"total_revenue": 420.0, "transactions": 3}
    assert body["chart_type"] is None
    assert body["data_quality"]["excluded_rows"] == 8


def test_ask_top_product(client):
    body = ask(client, "Which product generated the highest revenue?").json()
    assert body["intent"] == "top_product"
    assert "Desk" in body["answer"] and "290.00" in body["answer"]
    assert body["chart_type"] == "bar"


def test_ask_top_region(client):
    body = ask(client, "Which region has the highest sales?").json()
    assert body["intent"] == "top_region"
    assert body["data"]["top"] == ["North"]


def test_ask_monthly_trend(client):
    body = ask(client, "Show the monthly revenue trend").json()
    assert body["intent"] == "monthly_trend"
    assert body["chart_type"] == "line"
    assert [m["revenue"] for m in body["data"]] == [200.0, 130.0, 90.0]


def test_ask_compare_months_without_year(client):
    # Sample data covers only 2026, so "January" means January 2026.
    body = ask(client, "Compare January and March").json()
    assert body["intent"] == "compare_months"
    assert body["answer"] == (
        "March 2026 revenue (90.00) was 110.00 lower than January 2026 (200.00). "
        "That is a -55.00% change.")


def test_ask_compare_zero_revenue_baseline(client_for, make_db):
    client = client_for(make_db([
        "A1,10-02-2026,Desk,Furniture,North,Online,1,100,0,Returned",
        "A2,10-03-2026,Desk,Furniture,North,Online,2,100,0,Completed",
    ]))
    body = ask(client, "Compare Feb 2026 and Mar 2026").json()
    assert body["data"]["percent_change"] is None
    assert "zero revenue" in body["answer"]


# ---------- /ask: errors ----------

@pytest.mark.parametrize("payload", [{"question": ""}, {"question": "    "}, {}, {"question": None}])
def test_empty_or_missing_question_is_422(client, payload):
    assert client.post("/ask", json=payload).status_code == 422


def test_too_long_question_is_422(client):
    assert ask(client, "revenue " * 100).status_code == 422


def test_unsupported_question_is_400_with_help(client):
    response = ask(client, "What is the weather today?")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "don't understand" in detail["message"]
    assert len(detail["supported_questions"]) == 5


def test_comparison_month_not_in_data_is_404(client):
    response = ask(client, "Compare January 2025 and March 2026")
    assert response.status_code == 404
    assert "January 2025" in response.json()["detail"]


def test_sql_in_question_is_never_executed(client, sample_db):
    ask(client, "'; DROP TABLE sales; --")
    conn = sqlite3.connect(sample_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 11
    finally:
        conn.close()


def test_missing_database_is_503(client_for, tmp_path):
    missing = tmp_path / "does_not_exist.db"
    response = ask(client_for(missing), "What is the total revenue?")
    assert response.status_code == 503
    assert not missing.exists()  # the API must not create an empty database


def test_database_without_tables_is_503(client_for, tmp_path):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert client_for(empty).get("/data-quality").status_code == 503


# ---------- the real data ----------

def test_real_data_examples(client_for, db_path):
    build_database(CSV_PATH, db_path)
    client = client_for(db_path)
    assert ask(client, "What is the total revenue?").json()["data"]["total_revenue"] == 1439200.0
    assert ask(client, "Which product generated the highest revenue?").json()["data"]["top"] == ["Monitor"]
    assert ask(client, "Which region has the highest sales?").json()["data"]["top"] == ["South"]
    assert ask(client, "Compare March and April").json()["data"]["difference"] == 16800.0


# ---------- /summary ----------

def test_summary_endpoint(client):
    body = client.get("/summary").json()
    assert body["total_revenue"] == 420.0
    assert body["transactions"] == 3
    assert body["top_product"] == {"names": ["Desk"], "revenue": 290.0, "share_pct": 69.05}
    assert body["top_region"] == {"names": ["North"], "revenue": 200.0, "share_pct": 47.62}
    assert body["best_month"]["month"] == "2026-01"
    assert body["weakest_month"]["month"] == "2026-03"
    assert [m["revenue"] for m in body["monthly_trend"]] == [200.0, 130.0, 90.0]
    assert body["data_quality"]["excluded_rows"] == 8


def test_summary_with_missing_database_is_503(client_for, tmp_path):
    assert client_for(tmp_path / "missing.db").get("/summary").status_code == 503


def test_summary_real_data_matches_direct_sql(client_for, db_path):
    build_database(CSV_PATH, db_path)
    body = client_for(db_path).get("/summary").json()

    conn = sqlite3.connect(db_path)
    try:
        total, count = conn.execute("SELECT SUM(revenue), COUNT(*) FROM valid_sales").fetchone()
        product = conn.execute("SELECT product, SUM(revenue) FROM valid_sales "
                               "GROUP BY product ORDER BY 2 DESC LIMIT 1").fetchone()
        region = conn.execute("SELECT region, SUM(revenue) FROM valid_sales "
                              "GROUP BY region ORDER BY 2 DESC LIMIT 1").fetchone()
    finally:
        conn.close()

    assert (body["total_revenue"], body["transactions"]) == (total, count) == (1439200.0, 48)
    assert (body["top_product"]["names"], body["top_product"]["revenue"]) == ([product[0]], product[1])
    assert (body["top_region"]["names"], body["top_region"]["revenue"]) == ([region[0]], region[1])
    assert body["top_product"]["share_pct"] == round(product[1] / total * 100, 2) == 32.87
    assert body["top_region"]["share_pct"] == round(region[1] / total * 100, 2) == 28.57
    assert body["best_month"]["label"] == "May 2026"
    assert body["data_quality"]["valid_rows"] == 48



def test_summary_rankings_match_direct_sql(client_for, db_path):
    build_database(CSV_PATH, db_path)
    body = client_for(db_path).get("/summary").json()
    conn = sqlite3.connect(db_path)
    try:
        products = conn.execute("SELECT product, SUM(revenue), COUNT(*) FROM valid_sales "
                                "GROUP BY product ORDER BY 2 DESC, 1").fetchall()
        regions = conn.execute("SELECT region, SUM(revenue), COUNT(*) FROM valid_sales "
                               "GROUP BY region ORDER BY 2 DESC, 1").fetchall()
    finally:
        conn.close()
    assert [(r["name"], r["revenue"], r["transactions"]) for r in body["product_ranking"]] == products
    assert [(r["name"], r["revenue"], r["transactions"]) for r in body["region_ranking"]] == regions
    assert len(body["product_ranking"]) == 7
    assert [r["name"] for r in body["region_ranking"]] == ["South", "North", "East", "West"]
