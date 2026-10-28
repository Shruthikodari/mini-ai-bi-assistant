"""Reusable Streamlit building blocks shared by the pages in ui/views/.

Nothing here calculates analytics: values come from FastAPI responses and
are only formatted (see presentation.py).
"""

import html

import streamlit as st

from ui import api_client
from ui.presentation import (
    CALCULATION_METHODS,
    INTENT_TITLES,
    REVENUE_FORMULA,
    VALIDITY_RULES,
    build_chart,
    excluded_table,
    figures_table,
    headline_metrics,
    interpreted_as,
)

# (short button label, full question sent to the API)
SUGGESTED_QUESTIONS = [
    ("Total revenue", "What is the total revenue?"),
    ("Top product", "Which product generated the highest revenue?"),
    ("Monthly trend", "Show the monthly revenue trend"),
    ("Top region", "Which region has the highest sales?"),
    ("March vs April 2026", "Compare revenue between March 2026 and April 2026"),
]


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def section_label(text: str) -> None:
    html_block(f'<div class="section-label">{html.escape(text)}</div>')


def page_header(title: str, subtitle: str) -> None:
    st.title(title)
    html_block(f'<p class="subtitle">{html.escape(subtitle)}</p>')


# ---------- session state & question flow ----------

def init_state() -> None:
    st.session_state.setdefault("history", [])       # newest first
    st.session_state.setdefault("question_input", "")
    st.session_state.setdefault("pending", None)      # question waiting to be sent
    st.session_state.setdefault("next_id", 0)


def submit_typed_question() -> None:
    st.session_state.pending = st.session_state.question_input


def submit_suggestion(question: str) -> None:
    st.session_state.question_input = question
    st.session_state.pending = question


def process_pending_question() -> None:
    question = (st.session_state.pending or "").strip()
    st.session_state.pending = None
    if not question:
        st.toast("Please type a question first.")
        return
    with st.spinner("Analyzing..."):
        result = api_client.ask_question(question)
    st.session_state.history.insert(
        0, {"id": st.session_state.next_id, "question": question, "result": result}
    )
    st.session_state.next_id += 1


# ---------- search card ----------

def question_box() -> None:
    with st.container(border=True, key="ask_card"):
        with st.form("ask_form", border=False):
            col_input, col_button = st.columns([6, 1], vertical_alignment="bottom")
            col_input.text_input(
                "Ask a question about your sales data",
                key="question_input",
                placeholder="e.g. Which region has the highest sales?",
                max_chars=500,
            )
            col_button.form_submit_button(
                "Analyze", type="primary", use_container_width=True,
                on_click=submit_typed_question,
            )

        with st.container(key="suggestions"):
            for i, (column, (label, question)) in enumerate(
                    zip(st.columns(len(SUGGESTED_QUESTIONS)), SUGGESTED_QUESTIONS)):
                column.button(
                    label,
                    key=f"suggestion_{i}",
                    help=question,
                    use_container_width=True,
                    on_click=submit_suggestion,
                    args=(question,),
                )
        st.caption(
            "Questions are matched to five supported analyses using rule-based language "
            "rules (not a generative AI model). Every answer comes from a fixed SQL query."
        )


# ---------- answers ----------

def calculation_details(response: dict) -> None:
    """Body of the 'How this answer was calculated' section."""
    intent, quality = response["intent"], response["data_quality"]
    st.markdown(
        f"**Interpreted as:** {interpreted_as(intent, response['data'])}  \n"
        f"**Method:** {CALCULATION_METHODS.get(intent, '')}"
    )
    html_block(f'<div class="formula">{REVENUE_FORMULA}</div>')
    st.markdown(
        f"**Included:** {quality['valid_rows']} valid transactions. {VALIDITY_RULES} "
        "The discount is a fixed amount, not a percentage."
    )
    if quality["excluded"]:
        st.markdown(f"**Excluded:** {quality['excluded_rows']} of {quality['total_rows']} "
                    "records, for these reasons:")
        st.dataframe(excluded_table(quality), hide_index=True, use_container_width=True)


def render_result(entry: dict, show_calculation: bool = True) -> None:
    result = entry["result"]
    if not result.ok:
        if result.suggestions:
            st.warning(result.error)
            st.markdown("Try one of these:\n" + "\n".join(f"- {q}" for q in result.suggestions))
        else:
            st.error(result.error)
        return

    response = result.data
    intent, data = response["intent"], response["data"]

    html_block(
        f'<div class="intent-label">{html.escape(INTENT_TITLES.get(intent, intent))}</div>'
        f'<div class="answer">{html.escape(response["answer"])}</div>'
    )

    metrics = headline_metrics(intent, data)
    if metrics:
        for column, (label, value, delta) in zip(st.columns(len(metrics)), metrics):
            column.metric(label, value, delta)

    chart = build_chart(intent, data, response["chart_type"])
    table = figures_table(intent, data)
    if chart is not None and table is not None:
        with st.container(key=f"figures_{entry['id']}"):
            col_chart, col_table = st.columns([3, 2], gap="large")
            col_chart.altair_chart(chart, use_container_width=True)
            with col_table:
                section_label("Supporting figures")
                st.dataframe(table, hide_index=True, use_container_width=True)
    elif table is not None:
        section_label("Supporting figures")
        st.dataframe(table, hide_index=True, use_container_width=True)

    if show_calculation:
        with st.expander("How this answer was calculated"):
            calculation_details(response)


def answer_area() -> None:
    history = st.session_state.history
    if not history:
        return

    latest = history[0]
    with st.container(border=True, key="latest_result"):
        html_block(f'<div class="question-echo">You asked: “{html.escape(latest["question"])}”</div>')
        render_result(latest)

    if len(history) > 1:
        section_label("Earlier questions")
        for entry in history[1:]:
            # Streamlit does not allow an expander inside an expander,
            # so earlier answers omit the calculation section.
            with st.expander(entry["question"]):
                render_result(entry, show_calculation=False)


# ---------- dashboard pieces ----------

def kpi_grid(cards: list[tuple[str, str, str]]) -> None:
    """Equal-height KPI cards rendered as one CSS grid."""
    items = "".join(
        f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
        f'<div class="kpi-value">{html.escape(value)}</div>'
        f'<div class="kpi-sub">{html.escape(sub)}</div></div>'
        for label, value, sub in cards
    )
    html_block(f'<div class="kpi-grid">{items}</div>')


def insight_list(insights: list[str]) -> None:
    items = "".join(f"<li>{html.escape(text)}</li>" for text in insights)
    html_block(f'<ul class="insights">{items}</ul>')


def card_title(title: str, subtitle: str | None = None) -> None:
    sub = f'<div class="card-subtitle">{html.escape(subtitle)}</div>' if subtitle else ""
    html_block(f'<div class="card-title">{html.escape(title)}</div>{sub}')


def stat_rows(rows: list[tuple[str, str, str]]) -> None:
    """Label / value / detail rows, e.g. business highlights."""
    items = "".join(
        f'<div class="stat-row"><div class="stat-label">{html.escape(label)}</div>'
        f'<div class="stat-value">{html.escape(value)}</div>'
        f'<div class="stat-detail">{html.escape(detail)}</div></div>'
        for label, value, detail in rows
    )
    html_block(f'<div class="stat-rows">{items}</div>')


def data_quality_card(quality: dict) -> None:
    """Totals, the validity rules and every excluded transaction with its reason."""
    stat_rows([
        ("Total records", str(quality["total_rows"]), "Rows in the original CSV"),
        ("Valid records", str(quality["valid_rows"]), "Counted toward revenue"),
        ("Excluded records", str(quality["excluded_rows"]), "Not counted toward revenue"),
    ])
    st.caption(f"A record counts only if: {VALIDITY_RULES} Excluded records are kept "
               "for transparency but never added to revenue.")
    if quality["excluded"]:
        st.dataframe(excluded_table(quality), hide_index=True, use_container_width=True)
