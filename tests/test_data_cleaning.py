"""Tests for backend/data_cleaning.py."""

import pandas as pd
import pytest

from backend.data_cleaning import clean_sales_data, load_and_clean, load_csv, parse_date
from backend.database import CSV_PATH


def reason_for(clean, transaction_id, occurrence=0):
    rows = clean[clean["transaction_id"] == transaction_id]
    return rows.iloc[occurrence]["invalid_reason"]


# ---------- date parsing ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("03-01-2026", "2026-01-03"),  # DD-MM-YYYY (format used in the real file)
        ("15/02/2026", "2026-02-15"),  # DD/MM/YYYY
        ("2026-03-10", "2026-03-10"),  # ISO
        (" 25-01-2026 ", "2026-01-25"),  # surrounding spaces
    ],
)
def test_parse_date_known_formats(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["31-02-2026", "not a date", "", None])
def test_parse_date_invalid_returns_none(raw):
    assert parse_date(raw) is None


# ---------- row validation ----------

def test_valid_rows_are_kept_and_typed(sample_csv):
    clean = load_and_clean(sample_csv)
    valid = clean[clean["is_valid"]]
    assert list(valid["transaction_id"]) == ["T1", "T2", "T3"]
    assert valid["invalid_reason"].isna().all()
    assert list(valid["order_date"]) == ["2026-01-03", "2026-02-15", "2026-03-10"]


@pytest.mark.parametrize(
    "transaction_id, expected_reason",
    [
        ("T4", "status is 'Returned'"),
        ("T5", "quantity is zero or negative"),
        ("T6", "missing or non-numeric unit price"),
        ("T7", "unrecognised date"),
        ("T8", "discount is larger than the order value"),
        ("T9", "quantity is zero or negative"),
        ("T10", "missing or non-numeric unit price"),
    ],
)
def test_invalid_rows_are_flagged_with_reason(sample_csv, transaction_id, expected_reason):
    clean = load_and_clean(sample_csv)
    assert expected_reason in reason_for(clean, transaction_id)


def test_duplicate_transaction_id_keeps_first_only(sample_csv):
    clean = load_and_clean(sample_csv)
    duplicates = clean[clean["transaction_id"] == "T1"]
    assert list(duplicates["is_valid"]) == [True, False]
    assert "duplicate transaction id" in reason_for(clean, "T1", occurrence=1)


def test_missing_price_is_not_filled_in(sample_csv):
    clean = load_and_clean(sample_csv)
    assert pd.isna(clean.loc[clean["transaction_id"] == "T6", "unit_price"].iloc[0])


def test_cleaning_never_drops_or_reorders_rows(sample_csv):
    raw = load_csv(sample_csv)
    clean = clean_sales_data(raw)
    assert len(clean) == len(raw)
    assert list(clean["transaction_id"]) == list(raw["Transaction_Id"])
    assert list(clean["order_date_raw"]) == list(raw["Order_date"])


def test_status_check_ignores_case_and_spaces():
    raw = pd.DataFrame([{
        "Transaction_Id": "X1", "Order_date": "01-01-2026", "Product": "Desk",
        "Category": "Furniture", "Region": "North", "Sales_channel": "Online",
        "Quantity": "1", "Unit_price": "100", "Discount_amount": "0",
        "Status": " completed ",
    }])
    assert clean_sales_data(raw)["is_valid"].iloc[0]


def test_missing_column_raises_clear_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Transaction_Id,Order_date\nT1,01-01-2026\n")
    with pytest.raises(ValueError, match="missing required columns"):
        load_csv(path)


# ---------- the real data/sales.csv ----------

def test_real_csv_profile():
    clean = load_and_clean(CSV_PATH)
    assert len(clean) == 51
    assert clean["order_date"].notna().all()  # every date was understood
    invalid = clean[~clean["is_valid"]].set_index("transaction_id")["invalid_reason"]
    assert set(invalid.index) == {"TXN0033", "TXN0034", "TXN0051"}
    assert "Returned" in invalid["TXN0033"]
    assert "quantity is zero" in invalid["TXN0034"]
    assert "unit price" in invalid["TXN0051"]
