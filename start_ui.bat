@echo off
REM Start the Streamlit front end on http://localhost:8501
cd /d "%~dp0"
python -m streamlit run ui\streamlit_app.py
