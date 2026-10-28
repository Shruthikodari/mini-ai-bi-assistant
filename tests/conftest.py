"""Shared test fixtures.

SAMPLE_CSV is small, hand-written TEST data (not real sales). Each row
exercises one rule so expected results can be checked by hand.
"""

import pytest

from backend.database import build_database, get_connection

SAMPLE_CSV = """Transaction_Id,Order_date,Product,Category,Region,Sales_channel,Quantity,Unit_price,Discount_amount,Status
T1,03-01-2026,Desk,Furniture,North,Online,2,100,0,Completed
T2,15/02/2026,Chair,Furniture,South,Retail,3,50,20,Completed
T3,2026-03-10,Desk,Furniture,East,Online,1,100,10,Completed
T4,04-01-2026,Desk,Furniture,West,Online,5,100,0,Returned
T5,05-01-2026,Chair,Furniture,North,Retail,0,50,0,Completed
T6,06-01-2026,Chair,Furniture,North,Retail,4,,0,Completed
T7,31-02-2026,Desk,Furniture,North,Online,1,100,0,Completed
T8,07-01-2026,Desk,Furniture,North,Online,1,100,500,Completed
T9,08-01-2026,Desk,Furniture,North,Online,-2,100,0,Completed
T1,09-01-2026,Desk,Furniture,North,Online,1,100,0,Completed
T10,10-01-2026,Chair,Furniture,South,Online,1,abc,0,Completed
"""
# Expected valid rows: T1 (200), T2 (130), T3 (90)  -> total revenue 420
# Invalid: T4 returned, T5 zero qty, T6 missing price, T7 impossible date,
#          T8 discount > order value, T9 negative qty, second T1 duplicate,
#          T10 non-numeric price


HEADER = SAMPLE_CSV.splitlines()[0]


@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "sample_sales.csv"
    path.write_text(SAMPLE_CSV)
    return path


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_sales.db"


@pytest.fixture
def sample_db(sample_csv, db_path):
    """A database built from SAMPLE_CSV."""
    build_database(sample_csv, db_path)
    return db_path


@pytest.fixture
def make_db(tmp_path):
    """Build a test database from a list of CSV data lines (without header)."""
    counter = {"n": 0}

    def _make(lines: list[str]):
        counter["n"] += 1
        csv_path = tmp_path / f"custom_{counter['n']}.csv"
        csv_path.write_text("\n".join([HEADER, *lines]) + "\n")
        path = tmp_path / f"custom_{counter['n']}.db"
        build_database(csv_path, path)
        return path

    return _make


@pytest.fixture
def connect():
    """Open test databases and make sure they are closed afterwards."""
    opened = []

    def _connect(path):
        conn = get_connection(path)
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()
