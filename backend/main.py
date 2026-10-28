"""FastAPI application.

Flow for POST /ask:
    question -> question_parser (intent + months) -> analytics (fixed SQL) -> answer

Run with:  uvicorn backend.main:app --reload

On startup the SQLite database is built from data/sales.csv if it is missing,
so a fresh server (e.g. on Render) is ready before it accepts requests.
"""

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, StringConstraints

from backend import analytics, transactions
from backend.database import CSV_PATH, DB_PATH, ensure_database, get_data_quality_summary
from backend.question_parser import (
    COMPARE_MONTHS,
    MONTHLY_TREND,
    SUPPORTED_QUESTIONS,
    TOP_PRODUCT,
    TOP_REGION,
    TOTAL_REVENUE,
    parse_question,
)

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Build the database before serving requests if it does not exist yet.

    If building fails, the exception stops the server from starting, with
    a clear message in the log, instead of serving 503 errors forever.
    """
    summary = ensure_database(CSV_PATH, DB_PATH)
    if summary is None:
        logger.info("Using existing database at %s", DB_PATH)
    else:
        logger.info("Built database at %s: %s rows, %s valid, %s excluded", DB_PATH,
                    summary["total_rows"], summary["valid_rows"], summary["excluded_rows"])
    yield


app = FastAPI(
    title="Mini AI Business Intelligence Assistant",
    description="Ask questions about sales data. Answers come from fixed SQL queries.",
    lifespan=lifespan,
)


# ---------- request / response models ----------

class AskRequest(BaseModel):
    # Leading/trailing spaces are stripped, so "   " is rejected as empty (HTTP 422).
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class AskResponse(BaseModel):
    question: str
    intent: str
    answer: str
    data: Any
    chart_type: str | None   # "line", "bar" or None
    data_quality: dict


# ---------- database dependency ----------

def get_db_path() -> Path:
    """Separate function so tests can point the API at a test database."""
    return DB_PATH


def get_db(db_path: Path = Depends(get_db_path)):
    """Open the database read-only for one request, then close it.

    Read-only mode means the API can never change the data, and a missing
    database file is reported instead of being silently created empty.
    """
    if not Path(db_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Sales database not found. Run `python -m backend.database` first.",
        )
    conn = None
    try:
        conn = sqlite3.connect(
            f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM valid_sales LIMIT 1")  # schema check
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        raise HTTPException(status_code=503, detail=f"Sales database unavailable: {exc}")
    try:
        yield conn
    finally:
        conn.close()


# ---------- answer formatting ----------

def money(value: float) -> str:
    # The CSV has no currency column, so no currency symbol is assumed.
    return f"{value:,.2f}"


def answer_total_revenue(conn) -> tuple[str, dict, str | None]:
    result = analytics.total_revenue(conn)
    answer = (f"Total revenue is {money(result['total_revenue'])} "
              f"from {result['transactions']} valid completed transactions.")
    return answer, result, None


def answer_top(conn, what: str) -> tuple[str, dict, str | None]:
    result = analytics.top_product(conn) if what == "product" else analytics.top_region(conn)
    if not result["top"]:
        return f"There are no valid sales to rank by {what}.", result, None
    leaders = " and ".join(result["top"])
    tie = " (tie)" if len(result["top"]) > 1 else ""
    answer = (f"The {what} with the highest revenue is {leaders}{tie}, "
              f"with {money(result['top_revenue'])}.")
    return answer, result, "bar"


def answer_monthly_trend(conn) -> tuple[str, list, str | None]:
    trend = analytics.monthly_revenue_trend(conn)
    if not trend:
        return "There is no dated sales data to show a trend.", trend, None
    best = max(trend, key=lambda m: m["revenue"])
    worst = min(trend, key=lambda m: m["revenue"])
    answer = (f"Monthly revenue from {trend[0]['label']} to {trend[-1]['label']}: "
              f"highest in {best['label']} ({money(best['revenue'])}), "
              f"lowest in {worst['label']} ({money(worst['revenue'])}).")
    zero_months = [m["label"] for m in trend if m["revenue"] == 0]
    if zero_months:
        answer += f" No valid revenue in: {', '.join(zero_months)}."
    return answer, trend, "line"


def answer_compare_months(conn, months: list[str]) -> tuple[str, dict, str | None]:
    try:
        result = analytics.compare_months(conn, months[0], months[1])
    except analytics.NoDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    first, second = result["months"]
    diff = result["difference"]
    if diff == 0:
        movement = "the same as"
    else:
        movement = f"{money(abs(diff))} {'higher' if diff > 0 else 'lower'} than"
    answer = (f"{second['label']} revenue ({money(second['revenue'])}) was {movement} "
              f"{first['label']} ({money(first['revenue'])}).")
    if result["percent_change"] is not None:
        answer += f" That is a {result['percent_change']:+.2f}% change."
    else:
        answer += f" Percentage change is not defined because {first['label']} had zero revenue."
    return answer, result, "bar"


# ---------- endpoints ----------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/data-quality")
def data_quality(conn: sqlite3.Connection = Depends(get_db)):
    return get_data_quality_summary(conn)


@app.get("/summary")
def summary(conn: sqlite3.Connection = Depends(get_db)):
    """Dashboard headline figures (read-only; reuses the analytics queries)."""
    return {**analytics.dashboard_summary(conn), "data_quality": get_data_quality_summary(conn)}


def _clean(value: str | None) -> str | None:
    """Treat blank filter values as 'no filter'."""
    value = (value or "").strip()
    return value or None


FilterText = Annotated[str | None, Query(max_length=50)]


@app.get("/transactions")
def list_transactions(
    search: FilterText = None,
    region: FilterText = None,
    product: FilterText = None,
    status: FilterText = None,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    sort: Literal[tuple(transactions.SORT_COLUMNS)] = "order_date",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=500)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Browse every transaction (valid and invalid) with optional filters (read-only)."""
    return transactions.search_transactions(
        conn, search=_clean(search), region=_clean(region), product=_clean(product),
        status=_clean(status), month=month, sort=sort, order=order,
        limit=limit, offset=offset,
    )


@app.get("/transactions/filters")
def transaction_filters(conn: sqlite3.Connection = Depends(get_db)):
    """Values available for the Data Explorer dropdowns."""
    return transactions.filter_options(conn)


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, conn: sqlite3.Connection = Depends(get_db)):
    # Allow "March" without a year only when the data covers a single year.
    years = analytics.available_years(conn)
    default_year = years[0] if len(years) == 1 else None

    parsed = parse_question(request.question, default_year=default_year)
    if parsed.intent is None:
        raise HTTPException(
            status_code=400,
            detail={"message": parsed.error, "supported_questions": SUPPORTED_QUESTIONS},
        )

    if parsed.intent == TOTAL_REVENUE:
        answer, data, chart = answer_total_revenue(conn)
    elif parsed.intent == TOP_PRODUCT:
        answer, data, chart = answer_top(conn, "product")
    elif parsed.intent == TOP_REGION:
        answer, data, chart = answer_top(conn, "region")
    elif parsed.intent == MONTHLY_TREND:
        answer, data, chart = answer_monthly_trend(conn)
    elif parsed.intent == COMPARE_MONTHS:
        answer, data, chart = answer_compare_months(conn, parsed.months)
    else:  # defensive: parser returned something unexpected
        raise HTTPException(status_code=500, detail="Unknown intent.")

    return AskResponse(
        question=request.question,
        intent=parsed.intent,
        answer=answer,
        data=data,
        chart_type=chart,
        data_quality=get_data_quality_summary(conn),
    )
