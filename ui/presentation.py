"""Turn API responses into tables, metrics and charts.

These functions only RESHAPE numbers that FastAPI already calculated;
no analytics are recomputed here. Keeping them separate from the Streamlit
page makes them easy to unit-test.

Amounts are shown without a currency symbol because the dataset does not
specify one.
"""

import altair as alt
import pandas as pd

NAVY = "#1E293B"
TEAL = "#0F766E"
MUTED = "#CBD5E1"
GRID = "#E2E8F0"

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
        chart.properties(height=320, padding={"left": 5, "top": 5, "right": 30, "bottom": 5})
        .configure_axis(labelColor=NAVY, titleColor=NAVY, gridColor=GRID,
                        domainColor=GRID, tickColor=GRID, labelFontSize=12)
        .configure_view(strokeWidth=0)
    )


def build_chart(intent: str, data, chart_type: str | None) -> alt.Chart | None:
    """Build the chart suggested by the API's chart_type, or None."""
    revenue_tooltip = alt.Tooltip("revenue:Q", title="Revenue", format=",.2f")

    if chart_type == "line" and intent == "monthly_trend" and data:
        df = pd.DataFrame(data)
        # Short axis labels ("Jan 2026") so every month fits under the chart.
        df["short_label"] = pd.to_datetime(df["month"]).dt.strftime("%b %Y")
        chart = alt.Chart(df).mark_line(color=TEAL, strokeWidth=2.5, point=alt.OverlayMarkDef(
            color=TEAL, size=60, filled=True)).encode(
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
            color=alt.condition("datum.is_top", alt.value(TEAL), alt.value(MUTED)),
            tooltip=[alt.Tooltip("name:N", title="Name"), revenue_tooltip,
                     alt.Tooltip("transactions:Q", title="Transactions")],
        )
        return _style(chart)

    if chart_type == "bar" and intent == "compare_months":
        df = pd.DataFrame(data["months"])
        chart = alt.Chart(df).mark_bar(color=TEAL, cornerRadiusEnd=3, size=70).encode(
            x=alt.X("label:N", title=None, sort=list(df["label"]), axis=alt.Axis(labelAngle=0)),
            y=alt.Y("revenue:Q", title="Revenue", axis=alt.Axis(format=",.0f")),
            tooltip=[alt.Tooltip("label:N", title="Month"), revenue_tooltip,
                     alt.Tooltip("transactions:Q", title="Transactions")],
        )
        return _style(chart)

    return None
