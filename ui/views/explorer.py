"""Data Explorer: search, filter, sort, page through and export every transaction.

Filtering, sorting and paging happen in the backend (/transactions) with
parameterised SQL. This page only builds the request and displays the rows.
"""

import math
from calendar import month_name

import streamlit as st

from ui import api_client
from ui.components import data_quality_card, html_block, page_header
from ui.presentation import format_amount, style_transactions, transactions_csv, transactions_frame

ALL = "All"
SORT_OPTIONS = {
    "Order date": "order_date",
    "Transaction ID": "transaction_id",
    "Product": "product",
    "Region": "region",
    "Quantity": "quantity",
    "Unit price": "unit_price",
    "Revenue": "revenue",
    "Status": "status",
}
PAGE_SIZES = [10, 25, 50]
EXPORT_LIMIT = 500  # the API's maximum page size; the dataset has 51 rows

DEFAULTS = {
    "f_search": "",
    "f_region": ALL,
    "f_product": ALL,
    "f_status": ALL,
    "f_month": ALL,
    "f_sort": "Order date",
    "f_order": "Ascending",
    "f_page_size": 25,
    "f_page": 1,
}


def reset_filters() -> None:
    for key, value in DEFAULTS.items():
        st.session_state[key] = value


def back_to_first_page() -> None:
    st.session_state.f_page = 1


def month_option_label(value: str) -> str:
    if value == ALL:
        return "All months"
    year, month = value.split("-")
    return f"{month_name[int(month)]} {year}"


def current_filters() -> dict:
    """Request parameters built from the widgets ('All' means no filter)."""
    state = st.session_state
    return {
        "search": state.f_search.strip() or None,
        "region": None if state.f_region == ALL else state.f_region,
        "product": None if state.f_product == ALL else state.f_product,
        "status": None if state.f_status == ALL else state.f_status,
        "month": None if state.f_month == ALL else state.f_month,
        "sort": SORT_OPTIONS[state.f_sort],
        "order": "asc" if state.f_order == "Ascending" else "desc",
    }


def filter_toolbar(options: dict) -> None:
    with st.container(border=True, key="filters"):
        cols = st.columns([2.2, 1, 1, 1, 1, 0.9], vertical_alignment="bottom")
        cols[0].text_input("Search", key="f_search", placeholder="Transaction ID or product",
                           on_change=back_to_first_page)
        cols[1].selectbox("Region", [ALL, *options["regions"]], key="f_region",
                          on_change=back_to_first_page)
        cols[2].selectbox("Product", [ALL, *options["products"]], key="f_product",
                          on_change=back_to_first_page)
        cols[3].selectbox("Status", [ALL, *options["statuses"]], key="f_status",
                          on_change=back_to_first_page)
        cols[4].selectbox("Month", [ALL, *options["months"]], key="f_month",
                          format_func=month_option_label, on_change=back_to_first_page)
        cols[5].button("Reset filters", key="reset_filters", on_click=reset_filters,
                       use_container_width=True)


def render() -> None:
    page_header("Data Explorer", "Search, filter and inspect your sales transactions.")
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)

    options = api_client.get_filter_options()
    if not options.ok:
        st.error(options.error)
        return
    filter_toolbar(options.data)

    filters = current_filters()
    page_size = st.session_state.f_page_size
    page = st.session_state.f_page
    result = api_client.get_transactions(
        {**filters, "limit": page_size, "offset": (page - 1) * page_size})
    if not result.ok:
        st.error(result.error)
        return
    data = result.data
    matching = data["matching"]

    # If the filters shrank the result, jump back to a page that exists.
    pages = max(1, math.ceil(matching / page_size))
    if page > pages:
        st.session_state.f_page = 1
        st.rerun()

    # Result summary, sorting and export
    with st.container(key="results_bar"):
        col_info, col_sort, col_order, col_export = st.columns(
            [3, 1.2, 1.1, 1], vertical_alignment="bottom")
        col_info.markdown(
            f'<div class="result-count"><b>{matching}</b> matching transactions · '
            f'{data["matching_valid"]} counted toward revenue · '
            f'{data["matching_excluded"]} excluded<br>'
            f'<span>Revenue of matching valid transactions: '
            f'{format_amount(data["matching_revenue"])}</span></div>',
            unsafe_allow_html=True,
        )
        col_sort.selectbox("Sort by", list(SORT_OPTIONS), key="f_sort", on_change=back_to_first_page)
        col_order.selectbox("Order", ["Ascending", "Descending"], key="f_order",
                            on_change=back_to_first_page)
        export = api_client.get_transactions({**filters, "limit": EXPORT_LIMIT, "offset": 0})
        col_export.download_button(
            "Export CSV",
            data=transactions_csv(export.data["transactions"]) if export.ok else b"",
            file_name="filtered_transactions.csv",
            mime="text/csv",
            key="export_csv",
            disabled=not export.ok or matching == 0,
            use_container_width=True,
        )

    if matching == 0:
        html_block('<div class="empty-state">No transactions match these filters.</div>')
    else:
        # st.table (static HTML) keeps the "Missing" / "Not counted" labels and
        # wraps long exclusion reasons; sorting and paging are done by the API.
        with st.container(key="tx_table"):
            html_block('<div class="scroll-hint">Scroll the table sideways to see all columns.</div>')
            st.table(style_transactions(transactions_frame(data["transactions"])))

        # Pagination
        first = (page - 1) * page_size + 1
        last = min(page * page_size, matching)
        col_range, col_size, col_page = st.columns([4, 1, 1], vertical_alignment="bottom")
        col_range.caption(f"Showing {first}–{last} of {matching}")
        col_size.selectbox("Rows per page", PAGE_SIZES, key="f_page_size",
                           on_change=back_to_first_page)
        col_page.selectbox("Page", list(range(1, pages + 1)), key="f_page",
                           format_func=lambda p: f"{p} of {pages}")

    with st.expander("Data quality details"):
        quality = api_client.get_data_quality()
        if quality.ok:
            data_quality_card(quality.data)
        else:
            st.warning(quality.error)
