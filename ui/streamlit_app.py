"""Sales Intelligence: Streamlit front end.

The page only talks to FastAPI over HTTP (see api_client.py). All numbers
come from the API response; nothing is hard-coded or recalculated here.

Run with:  python -m streamlit run ui/streamlit_app.py
"""

import html
import sys
from pathlib import Path

# Allow `from ui import ...` when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from ui import api_client  # noqa: E402
from ui.presentation import (  # noqa: E402
    INTENT_TITLES,
    build_chart,
    figures_table,
    format_amount,
    headline_metrics,
)

SUGGESTED_QUESTIONS = [
    "What is the total revenue?",
    "Which product generated the highest revenue?",
    "Show the monthly revenue trend",
    "Which region has the highest sales?",
    "Compare revenue between March 2026 and April 2026",
]

CSS = """
<style>
.block-container {padding-top: 2.5rem; padding-bottom: 3rem; max-width: 1150px;}
h1 {font-weight: 700; letter-spacing: -0.02em; margin-bottom: 0;}
.subtitle {color: #64748B; font-size: 1.05rem; margin-top: 0.25rem; margin-bottom: 1.75rem;}
.intent-label {color: #0F766E; font-size: 0.78rem; font-weight: 600;
               text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.35rem;}
.answer {font-size: 1.3rem; font-weight: 500; line-height: 1.5; color: #1E293B;
         margin-bottom: 1rem;}
.question-echo {color: #64748B; font-size: 0.9rem; margin-bottom: 0.25rem;}
.formula {background: #F4F6F9; border-left: 3px solid #0F766E; padding: 0.6rem 0.8rem;
          border-radius: 4px; font-size: 0.88rem; color: #1E293B;}
[data-testid="stMetricValue"] {font-size: 1.45rem;}
</style>
"""


# ---------- session state & callbacks ----------

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


# ---------- page sections ----------

def render_sidebar() -> None:
    with st.sidebar:
        st.subheader("Data overview")
        quality = api_client.get_data_quality()
        if not quality.ok:
            st.warning(quality.error)
        else:
            q = quality.data
            st.metric("Total records", q["total_rows"])
            col1, col2 = st.columns(2)
            col1.metric("Valid", q["valid_rows"])
            col2.metric("Excluded", q["excluded_rows"])

            with st.expander(f"Data quality: {q['excluded_rows']} excluded"):
                if q["excluded"]:
                    st.dataframe(
                        [{"Transaction": r["transaction_id"], "Reason": r["invalid_reason"]}
                         for r in q["excluded"]],
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.write("No transactions were excluded.")

        st.markdown("##### How revenue is calculated")
        st.markdown(
            '<div class="formula">Revenue = Quantity × Unit price − Discount amount</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Only completed transactions count. Returned orders, zero quantities and "
            "missing prices are excluded. The discount is a fixed amount, not a "
            "percentage. Amounts have no currency symbol because the dataset does "
            "not specify one."
        )


def render_question_box() -> None:
    with st.form("ask_form", border=False):
        col_input, col_button = st.columns([5, 1], vertical_alignment="bottom")
        col_input.text_input(
            "Your question",
            key="question_input",
            placeholder="e.g. Which region has the highest sales?",
            max_chars=500,
        )
        col_button.form_submit_button(
            "Analyze", type="primary", use_container_width=True, on_click=submit_typed_question
        )

    st.caption("Suggested questions")
    columns = st.columns(len(SUGGESTED_QUESTIONS))
    for i, (column, question) in enumerate(zip(columns, SUGGESTED_QUESTIONS)):
        column.button(
            question,
            key=f"suggestion_{i}",
            use_container_width=True,
            on_click=submit_suggestion,
            args=(question,),
        )


def render_result(entry: dict) -> None:
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

    st.markdown(f'<div class="intent-label">{INTENT_TITLES.get(intent, intent)}</div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="answer">{html.escape(response["answer"])}</div>', unsafe_allow_html=True)

    metrics = headline_metrics(intent, data)
    if metrics:
        for column, (label, value, delta) in zip(st.columns(len(metrics)), metrics):
            column.metric(label, value, delta)

    chart = build_chart(intent, data, response["chart_type"])
    table = figures_table(intent, data)
    if chart is not None and table is not None:
        col_chart, col_table = st.columns([3, 2], gap="large")
        col_chart.altair_chart(chart, use_container_width=True)
        col_table.markdown("**Supporting figures**")
        col_table.dataframe(table, hide_index=True, use_container_width=True)
    elif table is not None:
        st.dataframe(table, hide_index=True, use_container_width=True)

    quality = response["data_quality"]
    st.caption(
        f"Based on {quality['valid_rows']} valid of {quality['total_rows']} records. "
        f"{quality['excluded_rows']} excluded (see Data quality in the sidebar)."
    )


def render_history() -> None:
    history = st.session_state.history
    if not history:
        st.info("Ask a question above, or pick one of the suggestions to get started.")
        return

    latest = history[0]
    with st.container(border=True):
        st.markdown(f'<div class="question-echo">You asked: “{html.escape(latest["question"])}”</div>',
                    unsafe_allow_html=True)
        render_result(latest)

    if len(history) > 1:
        st.markdown("#### Earlier questions")
        for entry in history[1:]:
            with st.expander(entry["question"]):
                render_result(entry)


def main() -> None:
    st.set_page_config(page_title="Sales Intelligence", page_icon=":material/insights:",
                       layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    if st.session_state.pending is not None:
        process_pending_question()

    st.title("Sales Intelligence")
    st.markdown('<p class="subtitle">Ask questions about your business data in natural '
                "language.</p>", unsafe_allow_html=True)

    render_sidebar()
    render_question_box()
    st.divider()
    render_history()


try:
    main()
except Exception:  # last line of defence: never show a traceback to users
    st.error("Something unexpected went wrong. Please refresh the page and try again.")
