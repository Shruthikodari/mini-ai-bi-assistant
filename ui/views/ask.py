"""Ask AI (home): search-first page with answers, KPIs and a monthly overview."""

import streamlit as st

from ui import api_client
from ui.components import (
    answer_area,
    html_block,
    insight_list,
    kpi_grid,
    page_header,
    process_pending_question,
    question_box,
    section_label,
)
from ui.presentation import build_chart, business_insights, kpi_cards


def overview() -> None:
    summary = api_client.get_summary()
    section_label("Overview")
    if not summary.ok:
        st.warning(summary.error)
        return
    data = summary.data
    kpi_grid(kpi_cards(data))

    col_chart, col_insights = st.columns([3, 2], gap="medium")
    with col_chart.container(border=True, key="overview_chart"):
        html_block('<div class="card-title">Monthly revenue</div>')
        chart = build_chart("monthly_trend", data["monthly_trend"], "line")
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            st.caption("No dated sales data available.")
    with col_insights.container(border=True, key="overview_insights"):
        html_block('<div class="card-title">Business insights</div>')
        insight_list(business_insights(data))
        st.caption("Facts taken directly from the SQL results. No forecasting or AI-generated text.")


def render() -> None:
    if st.session_state.pending is not None:
        process_pending_question()

    page_header("Sales Intelligence", "Ask questions about your business data in natural language.")
    question_box()
    answer_area()
    overview()
