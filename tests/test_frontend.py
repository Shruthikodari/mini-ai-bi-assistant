"""Tests for the Streamlit front end (ui/).

Instead of starting real servers, HTTP calls from api_client are routed to
FastAPI's TestClient. So these tests exercise the real path:
Streamlit page -> api_client -> FastAPI -> SQLite.
"""

from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.database import CSV_PATH, build_database
from backend.main import app, get_db_path
from ui import api_client
from ui.presentation import (
    build_chart,
    business_highlights,
    monthly_table,
    ranking_chart,
    transactions_csv,
    transactions_frame,
    business_insights,
    excluded_table,
    figures_table,
    format_amount,
    headline_metrics,
    interpreted_as,
    kpi_cards,
)

APP_FILE = str(Path(__file__).resolve().parent.parent / "ui" / "streamlit_app.py")


class FakeResponse:
    def __init__(self, status_code, body=None, invalid_json=False):
        self.status_code = status_code
        self._body = body
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def route_api_to(monkeypatch):
    """Send api_client's HTTP calls to the FastAPI app reading `db_path`."""
    def _route(db_path):
        app.dependency_overrides[get_db_path] = lambda: db_path
        client = TestClient(app)

        def fake_request(method, url, json=None, timeout=None, params=None):
            return client.request(method, url.replace(api_client.API_URL, ""), json=json,
                                  params=params)

        monkeypatch.setattr(api_client.requests, "request", fake_request)

    yield _route
    app.dependency_overrides.clear()


@pytest.fixture
def api_returns(monkeypatch):
    """Make every HTTP call return the given fake response (or raise an exception)."""
    def _set(response_or_exception):
        def fake_request(*args, **kwargs):
            if isinstance(response_or_exception, Exception):
                raise response_or_exception
            return response_or_exception
        monkeypatch.setattr(api_client.requests, "request", fake_request)
    return _set


@pytest.fixture
def real_db(db_path):
    build_database(CSV_PATH, db_path)
    return db_path


def run_app() -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    return at


def page_text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.value for e in at.error] + [w.value for w in at.warning]
    parts += [str(m.value) for m in at.metric]
    return "\n".join(parts)


def click_suggestion(at: AppTest, index: int) -> AppTest:
    at.button(key=f"suggestion_{index}").click().run()
    return at


def ask_typed(at: AppTest, question: str) -> AppTest:
    at.text_input(key="question_input").input(question)
    next(b for b in at.button if b.label == "Analyze").click().run()
    return at


# ---------- api_client ----------

def test_client_success(route_api_to, sample_db):
    route_api_to(sample_db)
    result = api_client.ask_question("What is the total revenue?")
    assert result.ok
    assert result.data["data"]["total_revenue"] == 420.0


def test_client_unsupported_question_returns_suggestions(route_api_to, sample_db):
    route_api_to(sample_db)
    result = api_client.ask_question("What is the weather?")
    assert not result.ok
    assert "don't understand" in result.error
    assert len(result.suggestions) == 5


def test_client_missing_month_message(route_api_to, sample_db):
    route_api_to(sample_db)
    result = api_client.ask_question("Compare January 2025 and March 2026")
    assert result.error == "There are no sales records for January 2025 in the dataset."


def test_client_empty_question_is_not_sent(api_returns):
    api_returns(AssertionError("no request should be made"))
    assert api_client.ask_question("   ").error == "Please type a question."


@pytest.mark.parametrize(
    "failure, expected",
    [
        (requests.ConnectionError(), "Cannot reach the analytics server"),
        (requests.Timeout(), "took too long"),
        (FakeResponse(500, invalid_json=True), "status 500"),
        (FakeResponse(200, invalid_json=True), "empty or unreadable"),
        (FakeResponse(200, body=None), "empty or unreadable"),
        (FakeResponse(200, body={"answer": "x"}), "incomplete"),
        (FakeResponse(422, body={"detail": []}), "Please type a question"),
        (FakeResponse(503, body={"detail": "Sales database not found."}), "Sales database not found."),
    ],
)
def test_client_failures_become_friendly_messages(api_returns, failure, expected):
    api_returns(failure)
    result = api_client.ask_question("What is the total revenue?")
    assert not result.ok
    assert expected in result.error


# ---------- presentation helpers ----------

TREND = [
    {"month": "2026-01", "label": "January 2026", "revenue": 200.0, "transactions": 1},
    {"month": "2026-02", "label": "February 2026", "revenue": 0.0, "transactions": 0},
]
RANKING = {"top": ["Desk"], "top_revenue": 290.0, "ranking": [
    {"name": "Desk", "revenue": 290.0, "transactions": 2},
    {"name": "Chair", "revenue": 130.0, "transactions": 1}]}
COMPARISON = {"months": [
    {"month": "2026-01", "label": "January 2026", "revenue": 200.0, "transactions": 1},
    {"month": "2026-03", "label": "March 2026", "revenue": 90.0, "transactions": 1}],
    "difference": -110.0, "percent_change": -55.0}


def test_format_amount_has_no_currency_symbol():
    assert format_amount(1439200) == "1,439,200.00"


@pytest.mark.parametrize(
    "intent, data, chart_type, mark",
    [
        ("monthly_trend", TREND, "line", "line"),
        ("top_product", RANKING, "bar", "bar"),
        ("top_region", RANKING, "bar", "bar"),
        ("compare_months", COMPARISON, "bar", "bar"),
    ],
)
def test_chart_types(intent, data, chart_type, mark):
    spec = build_chart(intent, data, chart_type).to_dict()
    assert spec["mark"]["type"] == mark


def test_total_revenue_has_no_chart():
    assert build_chart("total_revenue", {"total_revenue": 1, "transactions": 1}, None) is None


def test_bar_chart_keeps_api_ranking_order():
    spec = build_chart("top_product", RANKING, "bar").to_dict()
    assert spec["encoding"]["y"]["sort"] == ["Desk", "Chair"]


def test_trend_chart_keeps_month_order_and_zero_months():
    spec = build_chart("monthly_trend", TREND, "line").to_dict()
    assert spec["encoding"]["x"]["sort"] == ["Jan 2026", "Feb 2026"]


def test_figures_table_for_comparison():
    table = figures_table("compare_months", COMPARISON)
    assert list(table["Month"]) == ["January 2026", "March 2026"]
    assert list(table["Revenue"]) == ["200.00", "90.00"]


def test_comparison_change_metric():
    assert headline_metrics("compare_months", COMPARISON)[1][2] == "-110.00 (-55.00%)"
    undefined = {**COMPARISON, "percent_change": None}
    assert headline_metrics("compare_months", undefined)[1][2] == "-110.00"


def test_trend_metrics_have_no_misleading_arrows():
    metrics = headline_metrics("monthly_trend", TREND)
    assert metrics[0] == ("Best month: January 2026", "200.00", None)
    assert all(delta is None for _, _, delta in metrics)


def test_headline_metrics_for_tie():
    data = {"top": ["Chair", "Desk"], "top_revenue": 100.0, "ranking": []}
    assert headline_metrics("top_product", data)[0] == ("Top product", "Chair & Desk", None)


# ---------- Streamlit page (AppTest) ----------

def test_page_layout(route_api_to, real_db):
    route_api_to(real_db)
    at = run_app()
    assert not at.exception
    assert at.title[0].value == "Sales Intelligence"
    assert "Ask questions about your business data in natural language." in page_text(at)
    buttons = [at.button(key=f"suggestion_{i}") for i in range(5)]
    assert [b.label for b in buttons] == [
        "Total revenue", "Top product", "Monthly trend", "Top region", "March vs April 2026"]
    assert [b.help for b in buttons] == [
        "What is the total revenue?",
        "Which product generated the highest revenue?",
        "Show the monthly revenue trend",
        "Which region has the highest sales?",
        "Compare revenue between March 2026 and April 2026",
    ]
    assert "rule-based language rules (not a generative AI model)" in page_text(at)


@pytest.mark.parametrize(
    "index, expected",
    [
        (0, "Total revenue is 1,439,200.00 from 48 valid completed transactions."),
        (1, "The product with the highest revenue is Monitor, with 473,000.00."),
        (2, "highest in May 2026 (318,500.00), lowest in January 2026 (210,250.00)"),
        (3, "The region with the highest revenue is South, with 411,200.00."),
        (4, "April 2026 revenue (240,700.00) was 16,800.00 higher than March 2026 "
            "(223,900.00). That is a +7.50% change."),
    ],
)
def test_five_suggested_questions_with_real_data(route_api_to, real_db, index, expected):
    route_api_to(real_db)
    at = click_suggestion(run_app(), index)
    assert not at.exception
    assert expected in page_text(at)


def test_charts_and_tables_are_rendered(route_api_to, real_db):
    route_api_to(real_db)
    at = click_suggestion(run_app(), 2)  # monthly trend
    # One chart in the answer, one in the overview below it.
    assert len(at.get("arrow_vega_lite_chart")) == 2
    table = next(d.value for d in at.main.get("arrow_data_frame") if "Month" in d.value.columns)
    assert list(table["Month"]) == ["January 2026", "February 2026", "March 2026",
                                    "April 2026", "May 2026", "June 2026"]


def test_typed_question_and_history(route_api_to, sample_db):
    route_api_to(sample_db)
    at = run_app()
    ask_typed(at, "Which region has the highest sales?")
    ask_typed(at, "What is the total revenue?")
    assert [h["question"] for h in at.session_state["history"]] == [
        "What is the total revenue?", "Which region has the highest sales?"]
    assert [e.label for e in at.expander if e.label.startswith("Which region")]


def test_unsupported_question_shows_friendly_warning(route_api_to, sample_db):
    route_api_to(sample_db)
    at = ask_typed(run_app(), "What is the weather?")
    assert not at.exception
    assert any("don't understand" in w.value for w in at.warning)
    assert "Try one of these" in page_text(at)


def test_empty_question_is_not_added_to_history(route_api_to, sample_db):
    route_api_to(sample_db)
    at = ask_typed(run_app(), "   ")
    assert at.session_state["history"] == []


def test_api_unavailable_shows_friendly_error(api_returns):
    api_returns(requests.ConnectionError())
    at = run_app()
    assert not at.exception
    assert any("Cannot reach the analytics server" in w.value for w in at.warning)
    click_suggestion(at, 0)
    assert any("Cannot reach the analytics server" in e.value for e in at.error)


def test_suggestion_puts_full_question_in_input(route_api_to, sample_db):
    route_api_to(sample_db)
    at = click_suggestion(run_app(), 4)
    question = "Compare revenue between March 2026 and April 2026"
    assert at.text_input(key="question_input").value == question
    assert at.session_state["history"][0]["question"] == question


def test_home_kpis_and_insights_match_real_data(route_api_to, real_db):
    route_api_to(real_db)
    at = run_app()
    assert not at.exception
    text = page_text(at)
    for expected in [
        "1,439,200.00", "From 48 valid transactions", "3 of 51 records excluded",
        "Monitor", "473,000.00 · 32.87% of revenue", "South", "411,200.00 · 28.57% of revenue",
        "May 2026 had the highest monthly revenue (318,500.00); "
        "January 2026 had the lowest (210,250.00).",
        "TXN0033, TXN0034 and TXN0051",
    ]:
        assert expected in text


def test_answer_has_calculation_section(route_api_to, real_db):
    route_api_to(real_db)
    at = click_suggestion(run_app(), 3)  # top region
    expander = next(e for e in at.expander if e.label == "How this answer was calculated")
    inner = "\n".join(m.value for m in expander.markdown)
    assert "Revenue by region" in inner
    assert "Groups valid transactions by region" in inner
    assert "Revenue = Quantity × Unit price − Discount amount" in inner
    assert "48 valid transactions" in inner
    reasons = next(d.value for d in expander.get("arrow_data_frame"))
    assert list(reasons["Transaction"]) == ["TXN0033", "TXN0034", "TXN0051"]


def test_earlier_answers_have_no_nested_expander(route_api_to, sample_db):
    route_api_to(sample_db)
    at = run_app()
    ask_typed(at, "What is the total revenue?")
    ask_typed(at, "Which region has the highest sales?")
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert labels.count("How this answer was calculated") == 1


# ---------- dashboard helpers ----------

SUMMARY = {
    "total_revenue": 420.0, "transactions": 3,
    "top_product": {"names": ["Desk"], "revenue": 290.0, "share_pct": 69.05},
    "top_region": {"names": ["North"], "revenue": 200.0, "share_pct": 47.62},
    "best_month": {"label": "January 2026", "revenue": 200.0},
    "weakest_month": {"label": "March 2026", "revenue": 90.0},
    "monthly_trend": [],
    "data_quality": {"total_rows": 11, "valid_rows": 3, "excluded_rows": 1, "excluded": [
        {"transaction_id": "T4", "invalid_reason": "status is 'Returned', not Completed"}]},
}


def test_kpi_cards_from_summary():
    assert kpi_cards(SUMMARY) == [
        ("Total revenue", "420.00", "From 3 valid transactions"),
        ("Valid transactions", "3", "1 of 11 records excluded"),
        ("Highest-revenue product", "Desk", "290.00 · 69.05% of revenue"),
        ("Highest-revenue region", "North", "200.00 · 47.62% of revenue"),
    ]


def test_business_insights_only_restate_summary_figures():
    assert business_insights(SUMMARY) == [
        "January 2026 had the highest monthly revenue (200.00); March 2026 had the lowest (90.00).",
        "Desk is the top product, contributing 69.05% of total revenue.",
        "North is the top region, contributing 47.62% of total revenue.",
        "1 of 11 records (T4) are excluded from every figure because they fail the validity rules.",
    ]


def test_dashboard_helpers_with_no_valid_sales():
    empty = {**SUMMARY, "total_revenue": 0.0, "transactions": 0,
             "top_product": {"names": [], "revenue": 0.0, "share_pct": None},
             "top_region": {"names": [], "revenue": 0.0, "share_pct": None},
             "best_month": None, "weakest_month": None,
             "data_quality": {"total_rows": 0, "valid_rows": 0, "excluded_rows": 0, "excluded": []}}
    assert kpi_cards(empty)[2] == ("Highest-revenue product", "–", "0.00")
    assert business_insights(empty) == []


def test_interpreted_as_and_excluded_table():
    assert interpreted_as("compare_months", COMPARISON) == \
        "Month comparison: January 2026 vs March 2026"
    assert interpreted_as("top_region", {}) == "Revenue by region"
    table = excluded_table(SUMMARY["data_quality"])
    assert list(table.columns) == ["Transaction", "Reason excluded"]
    assert list(table["Transaction"]) == ["T4"]


# ---------- Analytics and Data Explorer pages ----------

ROOT = str(Path(__file__).resolve().parent.parent)


def run_view(view: str) -> AppTest:
    """Render one page function on its own (the pages are plain functions)."""
    script = (
        "import sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "from ui.components import init_state\n"
        f"from ui.views import {view}\n"
        "init_state()\n"
        f"{view}.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=30)
    at.run()
    return at


def test_analytics_page_shows_real_figures(route_api_to, real_db):
    route_api_to(real_db)
    at = run_view("analytics")
    assert not at.exception
    text = page_text(at)
    for expected in [
        "1,439,200.00", "From 48 valid transactions",
        "Highest-revenue product", "Monitor", "473,000.00 · 32.87% of revenue",
        "Highest-revenue region", "South", "411,200.00 · 28.57% of revenue",
        "Highest-revenue month", "May 2026", "318,500.00",
        "Lowest-revenue month", "January 2026", "210,250.00",
        "Total records", "Valid records", "Excluded records",
    ]:
        assert expected in text, expected
    # trend + product + region charts
    assert len(at.get("arrow_vega_lite_chart")) == 3
    monthly = next(d.value for d in at.get("arrow_data_frame") if "Month" in d.value.columns)
    assert list(monthly["Revenue"]) == ["210,250.00", "234,600.00", "223,900.00",
                                        "240,700.00", "318,500.00", "211,250.00"]
    excluded = next(d.value for d in at.get("arrow_data_frame")
                    if "Reason excluded" in d.value.columns)
    assert list(excluded["Transaction"]) == ["TXN0033", "TXN0034", "TXN0051"]


def test_analytics_page_api_down(api_returns):
    api_returns(requests.ConnectionError())
    at = run_view("analytics")
    assert not at.exception
    assert any("Cannot reach the analytics server" in e.value for e in at.error)


def explorer_table(at: AppTest):
    table = next(t.value for t in at.table if t.value.index.name == "Transaction ID")
    return table.reset_index()


def test_explorer_shows_all_51_transactions(route_api_to, real_db):
    route_api_to(real_db)
    at = run_view("explorer")
    assert not at.exception
    text = page_text(at)
    assert "<b>51</b> matching transactions · 48 counted toward revenue · 3 excluded" in text
    assert "Revenue of matching valid transactions: 1,439,200.00" in text
    assert len(explorer_table(at)) == 25  # first page
    assert "Showing 1–25 of 51" in text


def test_explorer_filters_and_search_work_together(route_api_to, real_db):
    route_api_to(real_db)
    at = run_view("explorer")
    at.selectbox(key="f_month").select("2026-04")
    at.selectbox(key="f_product").select("Keyboard")
    at.run()
    table = explorer_table(at)
    assert list(table["Transaction ID"]) == ["TXN0029", "TXN0034"]
    assert table.loc[1, "Data Quality"] == "Excluded: quantity is zero or negative"
    assert table.loc[1, "Revenue"] is None or table["Revenue"].isna()[1]

    at.text_input(key="f_search").input("txn0029").run()
    assert list(explorer_table(at)["Transaction ID"]) == ["TXN0029"]


def test_explorer_missing_price_and_reset(route_api_to, real_db):
    route_api_to(real_db)
    at = run_view("explorer")
    at.text_input(key="f_search").input("TXN0051").run()
    table = explorer_table(at)
    assert table["Unit Price"].isna()[0]          # displayed as "Missing" by the styler
    assert table.loc[0, "Data Quality"] == "Excluded: missing or non-numeric unit price"

    at.button(key="reset_filters").click().run()
    assert at.text_input(key="f_search").value == ""
    assert "<b>51</b> matching transactions" in page_text(at)


def test_explorer_pagination_and_sorting(route_api_to, real_db):
    route_api_to(real_db)
    at = run_view("explorer")
    at.selectbox(key="f_page").select(3).run()
    table = explorer_table(at)
    assert list(table["Transaction ID"]) == ["TXN0051"]
    assert "Showing 51–51 of 51" in page_text(at)

    at.selectbox(key="f_sort").select("Revenue")
    at.selectbox(key="f_order").select("Descending")
    at.run()
    table = explorer_table(at)
    assert table.loc[0, "Transaction ID"] == "TXN0038"   # 9 × 9,500 − 0 = 85,500
    assert table.loc[0, "Revenue"] == 85500.0


def test_explorer_no_matches(route_api_to, real_db):
    route_api_to(real_db)
    at = run_view("explorer")
    at.text_input(key="f_search").input("no such product").run()
    assert not at.exception
    assert "No transactions match these filters." in page_text(at)


def test_csv_export_contains_only_filtered_records(route_api_to, real_db):
    import csv
    import io

    route_api_to(real_db)
    result = api_client.get_transactions({"region": "West", "status": "Returned", "limit": 500})
    rows = list(csv.DictReader(io.StringIO(transactions_csv(result.data["transactions"]).decode())))
    assert [r["transaction_id"] for r in rows] == ["TXN0033"]
    assert rows[0]["revenue"] == ""            # not counted
    assert rows[0]["data_quality"] == "Excluded"
    assert rows[0]["exclusion_reason"] == "status is 'Returned', not Completed"

    result = api_client.get_transactions({"search": "TXN0051", "limit": 500})
    row = next(csv.DictReader(io.StringIO(transactions_csv(result.data["transactions"]).decode())))
    assert row["unit_price"] == ""             # missing stays blank, never 0


def test_transactions_frame_and_highlights():
    rows = [{"transaction_id": "X1", "order_date_raw": "03-01-2026", "product": "Desk",
             "category": "Furniture", "region": "North", "sales_channel": "Online",
             "quantity": 0, "unit_price": None, "discount_amount": 0.0, "status": "Completed",
             "is_valid": False, "invalid_reason": "quantity is zero or negative",
             "revenue": None}]
    frame = transactions_frame(rows)
    assert frame.loc[0, "Order Date"] == "03-01-2026"
    assert frame.loc[0, "Data Quality"] == "Excluded: quantity is zero or negative"
    assert business_highlights(SUMMARY) == [
        ("Highest-revenue month", "January 2026", "200.00"),
        ("Lowest-revenue month", "March 2026", "90.00"),
        ("Best-performing product", "Desk", "290.00 · 69.05% of revenue"),
        ("Best-performing region", "North", "200.00 · 47.62% of revenue"),
    ]
    assert list(monthly_table([])["Month"]) == []


def test_ranking_chart_highlights_leader_and_labels_values():
    ranking = [{"name": "Desk", "revenue": 290.0, "transactions": 2},
               {"name": "Chair", "revenue": 130.0, "transactions": 1}]
    spec = ranking_chart(ranking, ["Desk"]).to_dict()
    marks = [layer["mark"]["type"] for layer in spec["layer"]]
    assert marks == ["bar", "text"]
    data = next(iter(spec["datasets"].values()))
    assert [(d["name"], d["value_label"], d["is_top"]) for d in data] == [
        ("Desk", "290.00", True), ("Chair", "130.00", False)]
    assert ranking_chart([], []) is None
