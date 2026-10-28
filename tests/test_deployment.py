"""Deployment-related tests: database initialisation on startup, the Render
blueprint and the configurable backend URL used by Streamlit."""

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import backend.main as main_module
from backend import database
from backend.database import CSV_PATH, DatabaseInitError, database_is_ready, ensure_database
from ui import api_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------- ensure_database ----------

def test_builds_database_when_missing(tmp_path):
    db = tmp_path / "sub" / "sales.db"          # parent folder does not exist yet
    summary = ensure_database(CSV_PATH, db)
    assert summary["total_rows"] == 51 and summary["valid_rows"] == 48
    assert database_is_ready(db)


def test_does_not_rebuild_a_ready_database(tmp_path):
    db = tmp_path / "sales.db"
    ensure_database(CSV_PATH, db)
    assert ensure_database(CSV_PATH, db) is None


def test_rebuilds_an_empty_or_broken_database_file(tmp_path):
    db = tmp_path / "sales.db"
    db.write_bytes(b"")                          # exists, but has no tables
    assert not database_is_ready(db)
    assert ensure_database(CSV_PATH, db)["total_rows"] == 51


def test_missing_csv_fails_clearly(tmp_path):
    with pytest.raises(DatabaseInitError, match="CSV not found"):
        ensure_database(tmp_path / "missing.csv", tmp_path / "sales.db")


def test_invalid_csv_fails_clearly(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Transaction_Id,Order_date\nT1,01-01-2026\n")
    with pytest.raises(DatabaseInitError, match="missing required columns"):
        ensure_database(bad, tmp_path / "sales.db")


# ---------- FastAPI startup (lifespan) ----------

@pytest.fixture
def fresh_paths(tmp_path, monkeypatch):
    """Point the app at a database file that does not exist yet."""
    db = tmp_path / "startup.db"
    monkeypatch.setattr(main_module, "DB_PATH", db)
    main_module.app.dependency_overrides[main_module.get_db_path] = lambda: db
    yield db
    main_module.app.dependency_overrides.clear()


def test_startup_builds_database_before_serving(fresh_paths):
    assert not fresh_paths.exists()
    with TestClient(main_module.app) as client:   # `with` runs the startup code
        assert fresh_paths.exists()
        assert client.get("/health").json() == {"status": "ok"}
        ask = client.post("/ask", json={"question": "What is the total revenue?"}).json()
        assert ask["data"]["total_revenue"] == 1439200.0
        summary = client.get("/summary").json()
        assert summary["top_product"]["names"] == ["Monitor"]
        assert summary["top_region"]["names"] == ["South"]
        tx = client.get("/transactions", params={"status": "Returned"}).json()
        assert [t["transaction_id"] for t in tx["transactions"]] == ["TXN0033"]


def test_startup_fails_clearly_without_csv(fresh_paths, tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "CSV_PATH", tmp_path / "missing.csv")
    with pytest.raises(DatabaseInitError, match="CSV not found"):
        with TestClient(main_module.app):
            pass


# ---------- command line: python -m backend.database ----------

def test_cli_builds_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "cli.db")
    assert database.main() == 0
    assert database_is_ready(tmp_path / "cli.db")
    assert "Valid: 48, excluded: 3" in capsys.readouterr().out


def test_cli_exits_with_error_when_csv_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(database, "CSV_PATH", tmp_path / "missing.csv")
    assert database.main() == 1
    assert "Database initialisation failed: CSV not found" in capsys.readouterr().err


# ---------- Render blueprint ----------

def test_render_blueprint():
    blueprint = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = blueprint["services"][0]
    assert service["type"] == "web"
    assert service["runtime"] == "python"
    assert service["plan"] == "free"
    assert service["buildCommand"] == "pip install -r requirements.txt"
    assert service["startCommand"] == (
        "python -m backend.database && "
        "uvicorn backend.main:app --host 0.0.0.0 --port $PORT")
    assert service["healthCheckPath"] == "/health"
    # No secrets or API keys are required.
    assert [v["key"] for v in service.get("envVars", [])] == ["PYTHON_VERSION"]


def test_paths_work_on_case_sensitive_linux():
    # Linux file systems are case-sensitive: the exact names must exist.
    assert "sales.csv" in os.listdir(PROJECT_ROOT / "data")
    assert CSV_PATH == PROJECT_ROOT / "data" / "sales.csv"
    assert "backend" in os.listdir(PROJECT_ROOT) and "main.py" in os.listdir(PROJECT_ROOT / "backend")
    assert "\\" not in (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")


# ---------- Streamlit -> backend URL ----------

def test_api_url_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("BI_API_URL", raising=False)
    assert api_client.configured_api_url() == "http://127.0.0.1:8000"


def test_api_url_from_environment(monkeypatch):
    monkeypatch.setenv("BI_API_URL", "  https://sales-intelligence-api.onrender.com/  ")
    assert api_client.configured_api_url() == "https://sales-intelligence-api.onrender.com"
