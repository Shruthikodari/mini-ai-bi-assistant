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
from ui.presentation import build_chart, figures_table, format_amount, headline_metrics

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

        def fake_request(method, url, json=None, timeout=None):
            return client.request(method, url.replace(api_client.API_URL, ""), json=json)

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
    assert [at.button(key=f"suggestion_{i}").label for i in range(5)] == [
        "What is the total revenue?",
        "Which product generated the highest revenue?",
        "Show the monthly revenue trend",
        "Which region has the highest sales?",
        "Compare revenue between March 2026 and April 2026",
    ]
    metrics = {m.label: m.value for m in at.sidebar.metric}
    assert metrics == {"Total records": "51", "Valid": "48", "Excluded": "3"}
    assert "Revenue = Quantity × Unit price − Discount amount" in page_text(at)


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
    assert len(at.get("arrow_vega_lite_chart")) == 1
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
    assert any("Cannot reach the analytics server" in w.value for w in at.sidebar.warning)
    click_suggestion(at, 0)
    assert any("Cannot reach the analytics server" in e.value for e in at.error)
