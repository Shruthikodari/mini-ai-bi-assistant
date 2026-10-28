"""Tests for backend/question_parser.py."""

import pytest

from backend.question_parser import (
    COMPARE_MONTHS,
    MONTHLY_TREND,
    TOP_PRODUCT,
    TOP_REGION,
    TOTAL_REVENUE,
    parse_question,
)


@pytest.mark.parametrize(
    "question, intent",
    [
        # total revenue
        ("What is the total revenue?", TOTAL_REVENUE),
        ("How much money did we make overall?", TOTAL_REVENUE),
        ("total sales", TOTAL_REVENUE),
        ("What were our earnings?", TOTAL_REVENUE),
        # top product
        ("Which product generated the highest revenue?", TOP_PRODUCT),
        ("What is our best-selling product?", TOP_PRODUCT),
        ("Top item by sales", TOP_PRODUCT),
        ("Show revenue by product", TOP_PRODUCT),
        # top region
        ("Which region has the highest sales?", TOP_REGION),
        ("Which area sold the most?", TOP_REGION),
        ("Revenue per region", TOP_REGION),
        # monthly trend
        ("Show the monthly revenue trend", MONTHLY_TREND),
        ("How did revenue change over time?", MONTHLY_TREND),
        ("Give me month-wise sales", MONTHLY_TREND),
        ("Which month had the highest revenue?", MONTHLY_TREND),
        ("Revenue trend from January to June 2026", MONTHLY_TREND),
        # compare months
        ("Compare revenue between March 2026 and April 2026", COMPARE_MONTHS),
        ("March 2026 vs April 2026", COMPARE_MONTHS),
        ("Was April 2026 revenue higher than March 2026?", COMPARE_MONTHS),
        ("compare 2026-03 with 2026-04", COMPARE_MONTHS),
    ],
)
def test_intents(question, intent):
    parsed = parse_question(question)
    assert parsed.error is None
    assert parsed.intent == intent


def test_typos_are_tolerated():
    assert parse_question("whats the totl revnue").intent == TOTAL_REVENUE
    assert parse_question("which prodcut has highest revenue").intent == TOP_PRODUCT


def test_case_and_spacing_do_not_matter():
    assert parse_question("   WHICH   REGION   HAS THE HIGHEST SALES  ").intent == TOP_REGION


@pytest.mark.parametrize(
    "question, months",
    [
        ("Compare March 2026 and April 2026", ["2026-03", "2026-04"]),
        ("compare mar 2026 vs apr 2026", ["2026-03", "2026-04"]),
        ("April 2026 versus March 2026", ["2026-04", "2026-03"]),  # order as written
        ("compare 2026-03 and 04/2026", ["2026-03", "2026-04"]),
        ("compare December 2025 and January 2026", ["2025-12", "2026-01"]),
    ],
)
def test_month_extraction(question, months):
    assert parse_question(question).months == months


def test_month_without_year_uses_default_year():
    parsed = parse_question("Compare March and April", default_year=2026)
    assert parsed.intent == COMPARE_MONTHS
    assert parsed.months == ["2026-03", "2026-04"]


def test_month_without_year_and_no_default_is_an_error():
    parsed = parse_question("Compare March and April")
    assert parsed.intent is None
    assert "year" in parsed.error


def test_polite_may_is_not_a_month():
    assert parse_question("May I know the total revenue?").intent == TOTAL_REVENUE


@pytest.mark.parametrize(
    "question, error_contains",
    [
        ("", "type a question"),
        ("   ", "type a question"),
        ("What is the weather today?", "don't understand"),
        ("Which product has the lowest revenue?", "lowest"),
        ("Compare March 2026", "second month"),
        ("Compare revenue", "Which two months"),
        ("Compare Jan 2026, Feb 2026 and Mar 2026", "exactly two months"),
        ("Which product and region have the highest revenue?", "separately"),
        ("Compare 13/2026 and 01/2026", "not a valid month"),
    ],
)
def test_unsupported_or_ambiguous_questions(question, error_contains):
    parsed = parse_question(question, default_year=2026)
    assert parsed.intent is None
    assert error_contains in parsed.error


def test_months_without_year_borrow_the_written_year():
    parsed = parse_question("Compare March and April 2026")
    assert parsed.months == ["2026-03", "2026-04"]


def test_sql_text_can_only_become_a_whitelisted_intent():
    # The word "sales" matches total revenue; the SQL text itself is ignored.
    parsed = parse_question("'; DROP TABLE sales; --")
    assert parsed.intent in {None, TOTAL_REVENUE, TOP_PRODUCT, TOP_REGION,
                             MONTHLY_TREND, COMPARE_MONTHS}
    assert parsed.months == []
