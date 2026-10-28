"""Create the SQLite database and load the cleaned sales data into it.

Two database objects are created:
  * sales        - a table with EVERY row from the CSV (valid and invalid),
                   so nothing is lost and data-quality problems can be reported.
  * valid_sales  - a view containing only rows that count toward revenue,
                   with revenue = quantity * unit_price - discount_amount.

All analytics queries read from valid_sales, so the business rules live in
one place.

Run `python -m backend.database` to (re)build data/sales.db from data/sales.csv.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from backend.data_cleaning import load_and_clean

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "sales.csv"
DB_PATH = PROJECT_ROOT / "data" / "sales.db"

CREATE_SALES_TABLE = """
CREATE TABLE sales (
    source_row      INTEGER PRIMARY KEY,  -- line number in the CSV
    transaction_id  TEXT,
    order_date_raw  TEXT,                 -- date exactly as written in the CSV
    order_date      TEXT,                 -- ISO 'YYYY-MM-DD', NULL if unreadable
    product         TEXT,
    category        TEXT,
    region          TEXT,
    sales_channel   TEXT,
    quantity        INTEGER,
    unit_price      REAL,                 -- NULL when missing (never filled in)
    discount_amount REAL,                 -- fixed money amount, not a percentage
    status          TEXT,
    is_valid        INTEGER NOT NULL,     -- 1 = counts toward revenue
    invalid_reason  TEXT
)
"""

CREATE_VALID_SALES_VIEW = """
CREATE VIEW valid_sales AS
SELECT
    transaction_id,
    order_date,
    strftime('%Y-%m', order_date) AS order_month,
    product,
    category,
    region,
    sales_channel,
    quantity,
    unit_price,
    discount_amount,
    quantity * unit_price - discount_amount AS revenue
FROM sales
WHERE is_valid = 1
"""

INSERT_SALE = """
INSERT INTO sales (
    source_row, transaction_id, order_date_raw, order_date, product, category,
    region, sales_channel, quantity, unit_price, discount_amount, status,
    is_valid, invalid_reason
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

COLUMNS = [
    "source_row", "transaction_id", "order_date_raw", "order_date", "product",
    "category", "region", "sales_channel", "quantity", "unit_price",
    "discount_amount", "status", "is_valid", "invalid_reason",
]


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open the database; rows can be read like dictionaries (row['product'])."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Drop and recreate the table and view, so reloading never duplicates rows."""
    conn.execute("DROP VIEW IF EXISTS valid_sales")
    conn.execute("DROP TABLE IF EXISTS sales")
    conn.execute(CREATE_SALES_TABLE)
    conn.execute(CREATE_VALID_SALES_VIEW)


def _to_db_value(value):
    """Convert Pandas values to plain Python values SQLite understands."""
    if value is None or pd.isna(value):
        return None  # missing values are stored as NULL, never as 0
    if isinstance(value, bool):
        return int(value)
    if hasattr(value, "item"):  # numpy number -> Python number
        return value.item()
    return value


def insert_sales(conn: sqlite3.Connection, clean: pd.DataFrame) -> None:
    """Insert cleaned rows using parameterised SQL (no string formatting)."""
    rows = [
        tuple(_to_db_value(v) for v in record)
        for record in clean[COLUMNS].itertuples(index=False, name=None)
    ]
    conn.executemany(INSERT_SALE, rows)


def get_data_quality_summary(conn: sqlite3.Connection) -> dict:
    """Report how many rows were loaded and why any were excluded."""
    totals = conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(is_valid), 0) AS valid FROM sales"
    ).fetchone()
    excluded = conn.execute(
        """
        SELECT transaction_id, invalid_reason
        FROM sales
        WHERE is_valid = 0
        ORDER BY source_row
        """
    ).fetchall()
    return {
        "total_rows": totals["total"],
        "valid_rows": totals["valid"],
        "excluded_rows": totals["total"] - totals["valid"],
        "excluded": [dict(row) for row in excluded],
    }


def build_database(csv_path: str | Path = CSV_PATH, db_path: str | Path = DB_PATH) -> dict:
    """Full pipeline: read CSV -> validate -> load into SQLite. Returns a summary."""
    clean = load_and_clean(csv_path)
    conn = get_connection(db_path)
    try:
        with conn:  # commits on success, rolls back on error
            create_schema(conn)
            insert_sales(conn, clean)
        return get_data_quality_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    summary = build_database()
    print(f"Loaded {summary['total_rows']} rows into {DB_PATH}")
    print(f"Valid: {summary['valid_rows']}, excluded: {summary['excluded_rows']}")
    for row in summary["excluded"]:
        print(f"  {row['transaction_id']}: {row['invalid_reason']}")
