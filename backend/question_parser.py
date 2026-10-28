"""Turn a natural-language question into one of five supported intents.

HONEST NOTE: this is deterministic, rule-based language understanding, not a
generative LLM. It uses keyword/synonym lists, regular expressions for months
and years, and Python's built-in `difflib` to forgive small typos
("revnue" -> "revenue"). Same question in -> same answer out, every time.

Safety: this module only returns an intent name plus validated parameters
(e.g. months as 'YYYY-MM'). It never produces SQL. Each intent maps to one
fixed query in analytics.py.
"""

import re
from calendar import month_abbr, month_name
from dataclasses import dataclass, field
from difflib import get_close_matches

TOTAL_REVENUE = "total_revenue"
TOP_PRODUCT = "top_product"
MONTHLY_TREND = "monthly_trend"
TOP_REGION = "top_region"
COMPARE_MONTHS = "compare_months"

SUPPORTED_QUESTIONS = [
    "What is the total revenue?",
    "Which product generated the highest revenue?",
    "Show the monthly revenue trend.",
    "Which region has the highest sales?",
    "Compare revenue between March 2026 and April 2026.",
]

# ---------- vocabulary (all lowercase) ----------
REVENUE_WORDS = ["revenue", "revenues", "sales", "sale", "sold", "income", "earnings",
                 "earned", "earn", "turnover", "money", "made", "generated", "selling"]
TOTAL_WORDS = ["total", "overall", "sum", "entire", "whole", "altogether", "how much",
               "all time"]
HIGHEST_WORDS = ["highest", "top", "best", "most", "maximum", "max", "largest",
                 "biggest", "leading", "greatest", "number one", "peak"]
LOWEST_WORDS = ["lowest", "least", "worst", "minimum", "min", "smallest", "bottom",
                "fewest", "weakest"]
PRODUCT_WORDS = ["product", "products", "item", "items"]
REGION_WORDS = ["region", "regions", "area", "areas", "zone", "zones", "territory",
                "territories", "location", "locations"]
MONTH_WORDS = ["month", "months"]
TREND_WORDS = ["trend", "trends", "monthly", "month wise", "month-wise", "by month",
               "per month", "each month", "every month", "month by month",
               "month on month", "month-on-month", "over time", "over the months"]
COMPARE_WORDS = ["compare", "compared", "comparing", "comparison", "vs", "versus",
                 "between", "difference", "different", "change", "against", "than",
                 "growth", "increase", "decrease", "differ"]

FULL_MONTHS = [m.lower() for m in month_name if m]          # 'january', ...
SHORT_MONTHS = [m.lower() for m in month_abbr if m]         # 'jan', ...
MONTH_NUMBERS = {name: i + 1 for i, name in enumerate(FULL_MONTHS)}
MONTH_NUMBERS.update({name: i + 1 for i, name in enumerate(SHORT_MONTHS)})
MONTH_NUMBERS["sept"] = 9

# Single words used for typo correction.
VOCABULARY = sorted({
    word
    for group in (REVENUE_WORDS, TOTAL_WORDS, HIGHEST_WORDS, LOWEST_WORDS, PRODUCT_WORDS,
                  REGION_WORDS, MONTH_WORDS, TREND_WORDS, COMPARE_WORDS, FULL_MONTHS)
    for phrase in group
    for word in phrase.split()
})


@dataclass
class ParsedQuestion:
    intent: str | None                       # None when the question is not understood
    months: list[str] = field(default_factory=list)  # 'YYYY-MM' values
    error: str | None = None


# ---------- helpers ----------

def correct_typos(text: str) -> str:
    """Replace unknown words with a very close vocabulary word, e.g. 'revnue'."""
    def fix(match: re.Match) -> str:
        word = match.group(0)
        if len(word) < 4 or word in VOCABULARY:
            return word
        close = get_close_matches(word, VOCABULARY, n=1, cutoff=0.8)
        return close[0] if close else word

    return re.sub(r"[a-z]+", fix, text)


def has_any(text: str, phrases: list[str]) -> bool:
    """True if any phrase appears in the text as whole words."""
    return any(re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", text) for p in phrases)


def extract_months(text: str, default_year: int | None) -> tuple[list[str], str | None]:
    """Find months like 'March 2026', 'mar', '2026-03' or '03/2026'.

    Returns (months as 'YYYY-MM' in order of appearance, error message or None).
    """
    found: list[tuple[int, int | None, int]] = []  # (position, year, month)

    # Numeric forms: 2026-03  /  03/2026 or 03-2026
    for m in re.finditer(r"\b(\d{4})[-/](\d{1,2})\b", text):
        found.append((m.start(), int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r"\b(\d{1,2})[-/](\d{4})\b", text):
        found.append((m.start(), int(m.group(2)), int(m.group(1))))

    # Month names, optionally followed by a year: "march", "mar 2026", "march, 2026"
    names = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
    for m in re.finditer(rf"\b({names})\b(?:\s*,?\s*(\d{{4}}))?", text):
        if m.group(1) == "may" and m.start() == 0:
            continue  # "May I know ..." is a polite request, not the month
        year = int(m.group(2)) if m.group(2) else None
        found.append((m.start(), year, MONTH_NUMBERS[m.group(1)]))

    # "March and April 2026": if the question names exactly one year,
    # months written without a year belong to that year.
    written_years = {year for _, year, _ in found if year is not None}
    if len(written_years) == 1:
        default_year = written_years.pop()

    months = []
    for _, year, month in sorted(found):
        if not 1 <= month <= 12:
            return [], f"'{month}' is not a valid month number."
        if year is None:
            if default_year is None:
                return [], "Please include the year for each month, e.g. 'March 2026'."
            year = default_year
        value = f"{year:04d}-{month:02d}"
        if value not in months:
            months.append(value)
    return months, None


def _error(message: str) -> ParsedQuestion:
    return ParsedQuestion(intent=None, error=message)


# ---------- main entry point ----------

def parse_question(question: str, default_year: int | None = None) -> ParsedQuestion:
    """Map a question to an intent.

    `default_year` is used when a month is written without a year (e.g. "March").
    The API passes it only when the dataset covers a single year.
    """
    text = " ".join((question or "").lower().split())
    if not text:
        return _error("Please type a question.")
    text = correct_typos(text)

    months, month_error = extract_months(text, default_year)

    mentions_compare = has_any(text, COMPARE_WORDS)
    mentions_trend = has_any(text, TREND_WORDS)
    mentions_highest = has_any(text, HIGHEST_WORDS)
    mentions_lowest = has_any(text, LOWEST_WORDS)
    mentions_revenue = has_any(text, REVENUE_WORDS)
    mentions_product = has_any(text, PRODUCT_WORDS)
    mentions_region = has_any(text, REGION_WORDS)
    mentions_month = has_any(text, MONTH_WORDS)

    # 1. Monthly trend ("show monthly revenue", "which month had the most sales")
    if (mentions_trend or (mentions_month and (mentions_highest or mentions_lowest))) \
            and not (mentions_compare and months):
        return ParsedQuestion(intent=MONTHLY_TREND)

    # 2. Comparison between two specific months
    if month_error:
        return _error(month_error)
    if months:
        if len(months) == 2:
            return ParsedQuestion(intent=COMPARE_MONTHS, months=months)
        if len(months) == 1:
            return _error(
                "I can compare two months, e.g. 'Compare March 2026 and April 2026'. "
                "Please mention a second month, or ask for the monthly revenue trend."
            )
        return _error("Please mention exactly two months to compare.")

    if mentions_lowest:
        return _error("I can only answer 'highest' questions for products and regions, "
                      "not lowest/least.")

    # 3. Highest product / region
    wants_product = mentions_product and (mentions_highest or mentions_revenue)
    wants_region = mentions_region and (mentions_highest or mentions_revenue)
    if wants_product and wants_region:
        return _error("Please ask about products and regions separately.")
    if wants_product:
        return ParsedQuestion(intent=TOP_PRODUCT)
    if wants_region:
        return ParsedQuestion(intent=TOP_REGION)

    # 4. "Compare" without two months
    if mentions_compare:
        return _error("Which two months should I compare? "
                      "e.g. 'Compare March 2026 and April 2026'.")

    # 5. Total revenue
    if mentions_revenue or has_any(text, TOTAL_WORDS):
        return ParsedQuestion(intent=TOTAL_REVENUE)

    return _error("Sorry, I don't understand that question yet.")
