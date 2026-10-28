"""Analytics dashboard: KPIs, monthly trend, product and region rankings,
highlights and data quality. Every figure comes from the /summary endpoint."""

import streamlit as st

from ui import api_client
from ui.components import card_title, data_quality_card, kpi_grid, page_header, stat_rows
from ui.presentation import (
    build_chart,
    business_highlights,
    kpi_cards,
    monthly_table,
    ranking_chart,
)


def render() -> None:
    page_header("Analytics", "Revenue performance across months, products and regions.")
    summary = api_client.get_summary()
    if not summary.ok:
        st.error(summary.error)
        return
    data = summary.data

    kpi_grid(kpi_cards(data))

    # A. Monthly revenue trend with its supporting table
    with st.container(border=True, key="an_trend"):
        card_title("Monthly revenue trend", "Revenue of valid transactions per month")
        col_chart, col_table = st.columns([3, 2], gap="large")
        chart = build_chart("monthly_trend", data["monthly_trend"], "line")
        if chart is not None:
            col_chart.altair_chart(chart, use_container_width=True)
        col_table.dataframe(monthly_table(data["monthly_trend"]), hide_index=True,
                            use_container_width=True)

    # B. Products and C. Regions
    col_products, col_regions = st.columns([3, 2], gap="medium")
    with col_products.container(border=True, key="an_products"):
        card_title("Revenue by product", "All products ranked; the highest is highlighted")
        chart = ranking_chart(data["product_ranking"], data["top_product"]["names"],
                              horizontal=True, height=300)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
    with col_regions.container(border=True, key="an_regions"):
        card_title("Revenue by region", "Exact revenue for each region")
        chart = ranking_chart(data["region_ranking"], data["top_region"]["names"],
                              horizontal=False, height=300)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)

    # D. Highlights and E. Data quality
    col_highlights, col_quality = st.columns(2, gap="medium")
    with col_highlights.container(border=True, key="an_highlights"):
        card_title("Business highlights", "Taken directly from the SQL results")
        stat_rows(business_highlights(data))
    with col_quality.container(border=True, key="an_quality"):
        card_title("Data quality summary")
        data_quality_card(data["data_quality"])
