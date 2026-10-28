"""Turn API responses into tables, metrics and charts.

These functions only RESHAPE numbers that FastAPI already calculated;
no analytics are recomputed here. Keeping them separate from the Streamlit
page makes them easy to unit-test.

Amounts are shown without a currency symbol because the dataset does not
specify one.
"""

import altair as alt
import pandas as pd

NAVY = "#142B46"
BLUE = "#2563EB"
SLATE = "#64748B"
MUTED = "#BFDBFE"   # non-highlighted bars (light blue)
GRID = "#EEF2F6"
FONT = "Inter, Segoe UI, Helvetica Neue, Arial, sans-serif"

INTENT_TITLES = {
    "total_revenue": "Total revenue",
    "top_product": "Revenue by product",
    "top_region": "Revenue by region",
    "monthly_trend": "Monthly revenue trend",
    "compare_months": "Month comparison",
}


def format_amount(value) -> str:
    return f"{float(value):,.2f}"


# ---------- headline metrics ----------

def headline_metrics(intent: str, data) -> list[tuple[str, str, str | None]]:
    """Return (label, value, delta) tuples for st.metric."""
    if intent == "total_revenue":
        return [
            ("Total revenue", format_amount(data["total_revenue"]), None),
            ("Valid transactions", str(data["transactions"]), None),
        ]
    if intent in ("top_product", "top_region") and data.get("top"):
        label = "Top product" if intent == "top_product" else "Top region"
        return [
            (label, " & ".join(data["top"]), None),
            ("Revenue", format_amount(data["top_revenue"]), None),
        ]
    if intent == "monthly_trend" and data:
        best = max(data, key=lambda m: m["revenue"])
        worst = min(data, key=lambda m: m["revenue"])
        return [
            (f"Best month: {best['label']}", format_amount(best["revenue"]), None),
            (f"Weakest month: {worst['label']}", format_amount(worst["revenue"]), None),
            ("Months covered", str(len(data)), None),
        ]
    if intent == "compare_months":
        first, second = data["months"]
        change = f"{data['difference']:+,.2f}"
        if data["percent_change"] is not None:
            change += f" ({data['percent_change']:+.2f}%)"
        return [
            (first["label"], format_amount(first["revenue"]), None),
            (second["label"], format_amount(second["revenue"]), change),
        ]
    return []


# ---------- supporting figures table ----------

def figures_table(intent: str, data) -> pd.DataFrame | None:
    if intent in ("top_product", "top_region"):
        name = "Product" if intent == "top_product" else "Region"
        return pd.DataFrame(
            [{name: r["name"], "Revenue": format_amount(r["revenue"]),
              "Transactions": r["transactions"]} for r in data["ranking"]]
        )
    if intent == "monthly_trend":
        return pd.DataFrame(
            [{"Month": m["label"], "Revenue": format_amount(m["revenue"]),
              "Transactions": m["transactions"]} for m in data]
        )
    if intent == "compare_months":
        # The change itself is shown in the headline metrics.
        return pd.DataFrame(
            [{"Month": m["label"], "Revenue": format_amount(m["revenue"]),
              "Transactions": m["transactions"]} for m in data["months"]]
        )
    return None  # total revenue is fully shown by the headline metrics


# ---------- charts ----------

def _style(chart: alt.Chart) -> alt.Chart:
    return (
        chart.properties(height=300, padding={"left": 4, "top": 8, "right": 30, "bottom": 4})
        .configure(font=FONT, background="transparent")
        .configure_axis(labelColor=SLATE, titleColor=SLATE, gridColor=GRID,
                        domainColor=GRID, tickColor=GRID, labelFontSize=12,
                        titleFontSize=12, titleFontWeight=500, labelPadding=6)
        .configure_view(strokeWidth=0)
    )


def build_chart(intent: str, data, chart_type: str | None) -> alt.Chart | None:
    """Build the chart suggested by the API's chart_type, or None."""
    revenue_tooltip = alt.Tooltip("revenue:Q", title="Revenue", format=",.2f")

    if chart_type == "line" and intent == "monthly_trend" and data:
        df = pd.DataFrame(data)
        # Short axis labels ("Jan 2026") so every month fits under the chart.
        df["short_label"] = pd.to_datetime(df["month"]).dt.strftime("%b %Y")
        chart = alt.Chart(df).mark_line(color=BLUE, strokeWidth=2.5, point=alt.OverlayMarkDef(
            color=BLUE, size=60, filled=True)).encode(
            x=alt.X("short_label:N", title=None, sort=list(df["short_label"]),
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("revenue:Q", title="Revenue", axis=alt.Axis(format=",.0f")),
            tooltip=[alt.Tooltip("label:N", title="Month"), revenue_tooltip,
                     alt.Tooltip("transactions:Q", title="Transactions")],
        )
        return _style(chart)

    if chart_type == "bar" and intent in ("top_product", "top_region") and data.get("ranking"):
        df = pd.DataFrame(data["ranking"])
        df["is_top"] = df["name"].isin(data["top"])
        chart = alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("name:N", title=None, sort=list(df["name"])),  # API order: highest first
            x=alt.X("revenue:Q", title="Revenue", axis=alt.Axis(format=",.0f")),
            color=alt.condition("datum.is_top", alt.value(BLUE), alt.value(MUTED)),
            tooltip=[alt.Tooltip("name:N", title="Name"), revenue_tooltip,
                     alt.Tooltip("transactions:Q", title="Transactions")],
        )
        return _style(chart)

    if chart_type == "bar" and intent == "compare_months":
        df = pd.DataFrame(data["months"])
        chart = alt.Chart(df).mark_bar(color=BLUE, cornerRadiusEnd=3, size=70).encode(
            x=alt.X("label:N", title=None, sort=list(df["label"]), axis=alt.Axis(labelAngle=0)),
            y=alt.Y("revenue:Q", title="Revenue", axis=alt.Axis(format=",.0f")),
            tooltip=[alt.Tooltip("label:N", title="Month"), revenue_tooltip,
                     alt.Tooltip("transactions:Q", title="Transactions")],
        )
        return _style(chart)

    return None


# ---------- answer transparency ----------

CALCULATION_METHODS = {
    "total_revenue": "Adds up the revenue of every valid transaction.",
    "top_product": "Groups valid transactions by product, sums each product's revenue "
                   "and ranks them from highest to lowest.",
    "top_region": "Groups valid transactions by region, sums each region's revenue "
                  "and ranks them from highest to lowest.",
    "monthly_trend": "Groups valid transactions by order month and sums the revenue for "
                     "each month. A month that has records but no valid sales is shown as 0.",
    "compare_months": "Sums the revenue of valid transactions in each month separately. "
                      "Difference = later month − earlier month; the percentage change is "
                      "relative to the earlier month (undefined if that month is 0).",
}

REVENUE_FORMULA = "Revenue = Quantity × Unit price − Discount amount"
VALIDITY_RULES = ("Status is Completed, quantity is a whole number above 0, unit price is "
                  "present, the date is readable and the discount is not larger than the "
                  "order value.")


def interpreted_as(intent: str, data) -> str:
    """Plain-language description of how the question was understood."""
    title = INTENT_TITLES.get(intent, intent)
    if intent == "compare_months":
        first, second = data["months"]
        return f"{title}: {first['label']} vs {second['label']}"
    return title


def excluded_table(data_quality: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Transaction": r["transaction_id"], "Reason excluded": r["invalid_reason"]}
         for r in data_quality["excluded"]],
        columns=["Transaction", "Reason excluded"],
    )


# ---------- dashboard summary ----------

def _names(leader: dict) -> str:
    return " & ".join(leader["names"]) if leader["names"] else "–"


def kpi_cards(summary: dict) -> list[tuple[str, str, str]]:
    """(label, value, supporting text) for each KPI card, from /summary only."""
    quality = summary["data_quality"]
    product, region = summary["top_product"], summary["top_region"]

    def share(leader):
        if leader["share_pct"] is None:
            return format_amount(leader["revenue"])
        return f"{format_amount(leader['revenue'])} · {leader['share_pct']:.2f}% of revenue"

    return [
        ("Total revenue", format_amount(summary["total_revenue"]),
         f"From {summary['transactions']} valid transactions"),
        ("Valid transactions", str(quality["valid_rows"]),
         f"{quality['excluded_rows']} of {quality['total_rows']} records excluded"),
        ("Highest-revenue product", _names(product), share(product)),
        ("Highest-revenue region", _names(region), share(region)),
    ]


def business_insights(summary: dict) -> list[str]:
    """Factual statements taken directly from /summary figures (no forecasting)."""
    insights = []
    best, weakest = summary["best_month"], summary["weakest_month"]
    if best and weakest:
        insights.append(
            f"{best['label']} had the highest monthly revenue ({format_amount(best['revenue'])}); "
            f"{weakest['label']} had the lowest ({format_amount(weakest['revenue'])})."
        )
    for leader, what in ((summary["top_product"], "product"), (summary["top_region"], "region")):
        if leader["names"] and leader["share_pct"] is not None:
            insights.append(
                f"{_names(leader)} is the top {what}, contributing "
                f"{leader['share_pct']:.2f}% of total revenue."
            )
    quality = summary["data_quality"]
    if quality["excluded"]:
        ids = [r["transaction_id"] for r in quality["excluded"]]
        listed = ", ".join(ids[:-1]) + f" and {ids[-1]}" if len(ids) > 1 else ids[0]
        insights.append(
            f"{quality['excluded_rows']} of {quality['total_rows']} records ({listed}) are "
            "excluded from every figure because they fail the validity rules."
        )
    return insights


# ---------- analytics page ----------

def ranking_chart(ranking: list[dict], top_names: list[str], horizontal: bool = True,
                  height: int = 300) -> alt.Chart | None:
    """Bar chart of an API ranking with exact value labels; leaders in blue."""
    if not ranking:
        return None
    df = pd.DataFrame(ranking)
    df["is_top"] = df["name"].isin(top_names)
    df["value_label"] = df["revenue"].map(format_amount)
    order = list(df["name"])  # API order: highest first
    tooltip = [alt.Tooltip("name:N", title="Name"),
               alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
               alt.Tooltip("transactions:Q", title="Transactions")]
    color = alt.condition("datum.is_top", alt.value(BLUE), alt.value(MUTED))

    base = alt.Chart(df)
    if horizontal:
        name = alt.Y("name:N", title=None, sort=order, axis=alt.Axis(labelLimit=140))
        value = alt.X("revenue:Q", title=None, axis=alt.Axis(format=",.0f", tickCount=4),
                      scale=alt.Scale(domainMax=float(df["revenue"].max()) * 1.3))
        bars = base.mark_bar(cornerRadiusEnd=3, height=18).encode(
            y=name, x=value, color=color, tooltip=tooltip)
        labels = base.mark_text(align="left", dx=6, color=NAVY, fontSize=12).encode(
            y=name, x="revenue:Q", text="value_label:N")
    else:
        name = alt.X("name:N", title=None, sort=order, axis=alt.Axis(labelAngle=0))
        value = alt.Y("revenue:Q", title=None, axis=alt.Axis(format=",.0f", tickCount=4),
                      scale=alt.Scale(domainMax=float(df["revenue"].max()) * 1.15))
        bars = base.mark_bar(cornerRadiusEnd=3, size=44).encode(
            x=name, y=value, color=color, tooltip=tooltip)
        labels = base.mark_text(dy=-8, color=NAVY, fontSize=12).encode(
            x=name, y="revenue:Q", text="value_label:N")
    return _style((bars + labels).properties(height=height))


def monthly_table(trend: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Month": m["label"], "Revenue": format_amount(m["revenue"]),
          "Transactions": m["transactions"]} for m in trend],
        columns=["Month", "Revenue", "Transactions"],
    )


def business_highlights(summary: dict) -> list[tuple[str, str, str]]:
    """(label, value, detail) rows, all taken from /summary."""
    rows = []
    best, weakest = summary["best_month"], summary["weakest_month"]
    if best:
        rows.append(("Highest-revenue month", best["label"], format_amount(best["revenue"])))
    if weakest:
        rows.append(("Lowest-revenue month", weakest["label"], format_amount(weakest["revenue"])))
    for leader, label in ((summary["top_product"], "Best-performing product"),
                          (summary["top_region"], "Best-performing region")):
        if leader["names"]:
            detail = format_amount(leader["revenue"])
            if leader["share_pct"] is not None:
                detail += f" · {leader['share_pct']:.2f}% of revenue"
            rows.append((label, _names(leader), detail))
    return rows


# ---------- data explorer ----------

EXPLORER_COLUMNS = ["Transaction ID", "Order Date", "Product", "Category", "Region",
                    "Sales Channel", "Quantity", "Unit Price", "Discount", "Status",
                    "Revenue", "Data Quality"]


def quality_label(row: dict) -> str:
    return "Valid" if row["is_valid"] else f"Excluded: {row['invalid_reason']}"


def transactions_frame(rows: list[dict]) -> pd.DataFrame:
    """API rows -> table columns. Values are shown exactly as stored (no recalculation)."""
    return pd.DataFrame(
        [{
            "Transaction ID": r["transaction_id"],
            "Order Date": r["order_date_raw"],          # original text from the CSV
            "Product": r["product"],
            "Category": r["category"],
            "Region": r["region"],
            "Sales Channel": r["sales_channel"],
            "Quantity": r["quantity"],
            "Unit Price": r["unit_price"],              # None when missing
            "Discount": r["discount_amount"],
            "Status": r["status"],
            "Revenue": r["revenue"],                    # None when not counted
            "Data Quality": quality_label(r),
        } for r in rows],
        columns=EXPLORER_COLUMNS,
    )


def style_transactions(df: pd.DataFrame):
    """Number formatting, 'Missing' prices and highlighted excluded rows."""
    def highlight(row):
        excluded = str(row["Data Quality"]).startswith("Excluded")
        return ["background-color: #FEF2F2" if excluded else "" for _ in row]

    # Transaction ID becomes the row label, so no meaningless 0, 1, 2 index is shown.
    return (
        df.set_index("Transaction ID").style
        .format("{:,.0f}", subset=["Quantity"], na_rep="Missing")
        .format("{:,.2f}", subset=["Unit Price"], na_rep="Missing")
        .format("{:,.2f}", subset=["Discount"], na_rep="Missing")
        .format("{:,.2f}", subset=["Revenue"], na_rep="Not counted")
        .apply(highlight, axis=1)
    )


def transactions_csv(rows: list[dict]) -> bytes:
    """CSV of the given (already filtered) rows. Missing values stay blank."""
    df = pd.DataFrame(
        [{
            "transaction_id": r["transaction_id"],
            "order_date": r["order_date_raw"],
            "product": r["product"],
            "category": r["category"],
            "region": r["region"],
            "sales_channel": r["sales_channel"],
            "quantity": r["quantity"],
            "unit_price": r["unit_price"],
            "discount_amount": r["discount_amount"],
            "status": r["status"],
            "revenue": r["revenue"],
            "data_quality": "Valid" if r["is_valid"] else "Excluded",
            "exclusion_reason": r["invalid_reason"] or "",
        } for r in rows],
        columns=["transaction_id", "order_date", "product", "category", "region",
                 "sales_channel", "quantity", "unit_price", "discount_amount", "status",
                 "revenue", "data_quality", "exclusion_reason"],
    )
    return df.to_csv(index=False).encode("utf-8")
