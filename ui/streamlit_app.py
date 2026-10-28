"""Sales Intelligence: Streamlit entry point.

Sets up the page, loads the stylesheet and registers the three sections
with Streamlit's built-in navigation. Each section lives in ui/views/.
The UI only talks to FastAPI over HTTP (see api_client.py); nothing is
calculated or hard-coded here.

Run with:  python -m streamlit run ui/streamlit_app.py
"""

import sys
from pathlib import Path

# Allow `from ui import ...` when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from ui.components import html_block, init_state  # noqa: E402
from ui.views import analytics, ask, explorer  # noqa: E402

STYLES_FILE = Path(__file__).with_name("styles.css")


def main() -> None:
    st.set_page_config(page_title="Sales Intelligence", page_icon=":material/insights:",
                       layout="wide")
    html_block(f"<style>{STYLES_FILE.read_text(encoding='utf-8')}</style>")
    init_state()

    pages = [
        st.Page(ask.render, title="Ask AI", url_path="ask", default=True),
        st.Page(analytics.render, title="Analytics", url_path="analytics"),
        st.Page(explorer.render, title="Data Explorer", url_path="explorer"),
    ]
    st.navigation(pages, position="top").run()


try:
    main()
except Exception:  # last line of defence: never show a traceback to users
    st.error("Something unexpected went wrong. Please refresh the page and try again.")
