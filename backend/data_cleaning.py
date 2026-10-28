"""Load the raw sales CSV and validate every row with Pandas.

Key rule: we never delete, invent or change a sales record.
We only:
  * convert text to proper types (numbers, ISO dates), and
  * flag each row as valid or invalid, with a reason.

A row is VALID (counts toward revenue) only if:
  * Status is "Completed"            -> returned orders are excluded
  * Quantity is a whole number > 0   -> zero / negative quantities are excluded
  * Unit_price is present and >= 0   -> missing prices are excluded (never guessed)
  * Discount_amount is present, >= 0 and not larger than Quantity x Unit_price
  * Order_date matches a known date format
  * Transaction_Id is present and not a duplicate

Revenue (calculated later in SQL) = Quantity x Unit_price - Discount_amount.
Discount_amount is a fixed money amount, not a percentage.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = [
    "Transaction_Id",
    "Order_date",
    "Product",
    "Category",
    "Region",
    "Sales_channel",
    "Quantity",
    "Unit_price",
    "Discount_amount",
    "Status",
]

# The source file uses day-first dates (e.g. 25-01-2026), so every
# format here is day-first or unambiguous ISO. Order matters: first match wins.
DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"]

VALID_STATUS = "completed"


def load_csv(csv_path: str | Path) -> pd.DataFrame:
    """Read the CSV as plain text so Pandas does not silently guess types."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    return df


def parse_date(value) -> str | None:
    """Return the date as 'YYYY-MM-DD', or None if no known format matches."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_number(series: pd.Series) -> pd.Series:
    """Convert text to numbers; blanks and non-numeric text become NaN (missing)."""
    return pd.to_numeric(series.str.strip().replace("", None), errors="coerce")


def find_problems(row) -> list[str]:
    """Return a list of reasons why this row cannot count toward revenue."""
    problems = []

    if not row["transaction_id"]:
        problems.append("missing transaction id")
    if row["order_date"] is None:
        problems.append(f"unrecognised date '{row['order_date_raw']}'")
    if row["status"].lower() != VALID_STATUS:
        problems.append(f"status is '{row['status']}', not Completed")

    quantity = row["quantity"]
    if pd.isna(quantity):
        problems.append("missing or non-numeric quantity")
    elif quantity <= 0:
        problems.append("quantity is zero or negative")
    elif quantity != int(quantity):
        problems.append("quantity is not a whole number")

    price = row["unit_price"]
    if pd.isna(price):
        problems.append("missing or non-numeric unit price")
    elif price < 0:
        problems.append("negative unit price")

    discount = row["discount_amount"]
    if pd.isna(discount):
        problems.append("missing or non-numeric discount amount")
    elif discount < 0:
        problems.append("negative discount amount")
    elif not pd.isna(quantity) and not pd.isna(price) and discount > quantity * price:
        problems.append("discount is larger than the order value")

    return problems


def clean_sales_data(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the raw text DataFrame into typed, validated rows.

    The output has exactly one row per input row, in the same order.
    """
    clean = pd.DataFrame()
    # Row number in the CSV (header is line 1), so any row can be traced back.
    clean["source_row"] = raw.index + 2
    clean["transaction_id"] = raw["Transaction_Id"].str.strip()
    clean["order_date_raw"] = raw["Order_date"]
    clean["order_date"] = raw["Order_date"].apply(parse_date)
    clean["product"] = raw["Product"].str.strip()
    clean["category"] = raw["Category"].str.strip()
    clean["region"] = raw["Region"].str.strip()
    clean["sales_channel"] = raw["Sales_channel"].str.strip()
    clean["quantity"] = to_number(raw["Quantity"])
    clean["unit_price"] = to_number(raw["Unit_price"])
    clean["discount_amount"] = to_number(raw["Discount_amount"])
    clean["status"] = raw["Status"].str.strip()

    problems = clean.apply(find_problems, axis=1)

    # Only the first occurrence of a transaction id is kept as valid.
    duplicated = clean["transaction_id"].duplicated(keep="first") & (clean["transaction_id"] != "")
    for i in clean.index[duplicated]:
        problems[i] = problems[i] + ["duplicate transaction id"]

    clean["is_valid"] = problems.apply(lambda p: len(p) == 0)
    clean["invalid_reason"] = problems.apply(lambda p: "; ".join(p) if p else None)
    return clean


def load_and_clean(csv_path: str | Path) -> pd.DataFrame:
    """Convenience helper: read the CSV and validate it in one step."""
    return clean_sales_data(load_csv(csv_path))
