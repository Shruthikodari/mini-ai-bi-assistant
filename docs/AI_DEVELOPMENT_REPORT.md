# AI Development Report

This report explains how AI tools were used to build this project, which problems came up and how they were fixed, and what has and has not been verified.

## Tools used

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic), running inside VS Code | Inspecting the project folder and CSV, writing all application and test code, running the tests, debugging, checking the running app, and drafting this documentation |
| **ChatGPT** | Planning and writing the stage-by-stage prompts given to Claude Code (as reported by the developer; that work happened outside the Claude Code session) |

No AI model is used **inside** the application at run time. The question interpreter is rule-based (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## How the work was organised

The developer split the project into small stages. Each stage was a separate prompt, and Claude Code stopped at the end of each one so the developer could review it.

| Stage | Scope | Result at the end of the stage |
|---|---|---|
| 0 | Inspect the empty folder, propose a structure and plan | Plan only; no code |
| 1 | Dependencies, CSV cleaning, SQLite loading, tests | 29 tests passing |
| 2 | Analytics, question interpreter, FastAPI, tests | 107 tests passing |
| 3 | Streamlit frontend, tests | 142 tests passing |
| 4 | Documentation (this stage) | – |

Throughout, the developer gave the key requirements: "do not invent sales data", "never execute LLM-generated SQL", "keep it beginner-friendly", the revenue formula, the UI design direction, and a request to stop after each stage.

## How AI helped

### Architecture

- Proposed the CSV → Pandas → SQLite → fixed SQL → FastAPI → Streamlit pipeline. It also suggested keeping all rows in a `sales` table and putting the business rules into a single `valid_sales` view.
- Proposed mapping each question to one of a fixed set of intents instead of generating SQL. This was the developer's own safety requirement, and the AI turned it into a concrete design.
- Pointed out, before writing any code, that the dataset was needed first, because the cleaning rules depend on the real columns and formats.

### Implementation

- Inspected the real CSV before writing cleaning code. It found 51 rows, all dates in `DD-MM-YYYY` format, and exactly three invalid rows (one returned, one with quantity 0, one with a missing price).
- Wrote all modules in `backend/` and `ui/`, the `.bat` start scripts and the Streamlit theme.
- Added defensive checks the dataset does not currently need, such as duplicate IDs, impossible dates, negative quantities, and discounts larger than the order value. Each one is covered by a test.

### Testing

- Wrote 142 Pytest tests. They use a small hand-written fixture dataset with hand-worked expected values, plus real-data regression tests.
- Cross-checked the real figures (total, per product, per region, per month) with a **separate Pandas calculation on the raw CSV**, independent of the project's SQL. The two agreed exactly before the figures were written into tests.
- Used FastAPI's `TestClient` for API tests and Streamlit's `AppTest` for UI tests.

### Debugging and verification

- Ran the real servers (Uvicorn and Streamlit), sent the five example questions over HTTP, and checked the server logs for errors and warnings.
- Drove a headless Chrome browser through the Chrome DevTools protocol to click the suggested questions and take screenshots. This visual check found the presentation problems described below.

## Problems encountered and how they were resolved

All of these happened during this project's development session.

### 1. Wrong first assumption that discounts were percentages

- **What happened:** the first plan (Stage 0, before the dataset was available) said discounts would be "converted to a fraction from 0 to 1" and revenue calculated as `qty × price × (1 − discount)`. That was a guess about an unseen column.
- **How it was caught:** with the Stage 1 prompt, the developer specified that `Discount_amount` is a **fixed monetary amount** and that revenue = `Quantity × Unit_price − Discount_amount`.
- **Resolution:** the percentage approach was dropped before any code was written. The formula lives in the `valid_sales` view. `test_revenue_is_quantity_times_price_minus_fixed_discount` checks it with hand-worked values (for example `3 × 50 − 20 = 130`). A validation rule also flags any discount larger than the order value.
- **Lesson:** the AI's first plan contained a confident-sounding assumption about data it had not seen. Human domain knowledge corrected it.

### 2. Month/year interpretation

- **What happened:** in Stage 2, the test question "Revenue trend from January to June 2026" failed. The parser asked "Please include the year" because "January" had no year attached. It checked months before it checked for a trend question.
- **Resolution:**
  - Months without a year now take the year written elsewhere in the question, if exactly one year is written ("March and April 2026").
  - Month errors are only reported after the trend check, because a trend question does not need specific months.
- **Related design decisions:**
  - A month with no year at all ("Compare March and April") is accepted only because the dataset covers a single year. The API passes a default year only in that case.
  - "May" at the start of a sentence ("May I know…") is not treated as a month.
- **Tests:** `test_months_without_year_borrow_the_written_year`, `test_month_without_year_uses_default_year`, `test_month_without_year_and_no_default_is_an_error`, `test_polite_may_is_not_a_month`.

### 3. The SQL injection test expectation

- **What happened:** a test expected the input `'; DROP TABLE sales; --` to be rejected as an unknown question. It failed: the parser returned `total_revenue`, because the text contains the keyword "sales".
- **Analysis:** this was a wrong expectation in the test, not a security hole. The interpreter only ever outputs an intent name, and the text itself never reaches SQL. The real safety property is "no SQL from the user is ever executed", not "the parser rejects SQL-looking text".
- **Resolution:**
  - The parser test now checks that the result is one of the whitelisted intents and that no months were extracted.
  - A new API test, `test_sql_in_question_is_never_executed`, sends the text to `/ask` and confirms the `sales` table still has all its rows.
- **Honest side effect:** keyword matching means nonsense that contains a revenue word can still receive the total-revenue answer. This is listed as a known limitation.

### 4. Streamlit chart labels and table presentation

All Stage 3 tests passed, but the screenshots showed problems that the tests did not catch:

| Problem seen in screenshot | Fix |
|---|---|
| The trend's "Best month" and "Weakest month" cards both had a green ↑ arrow, because the revenue was passed as Streamlit's `delta`. That made the weakest month look like an improvement. | The month name moved into the label and the revenue became the value, with no delta. Test: `test_trend_metrics_have_no_misleading_arrows`. |
| The comparison table had a "Change" row that put the percentage change in the "Transactions" column. | Removed the row; the change is shown once, in the headline figure. |
| The last x-axis label ("500,000") on the product bar chart was cut off at the right edge. | Added right padding to the charts. |
| After the padding change, the trend chart dropped every other month label because the full names ("February 2026") no longer fitted. | Used short axis labels ("Feb 2026"). The table keeps the full names. |

**Lesson:** passing tests do not prove the interface looks right. The visual check found real usability problems.

### Smaller issues

- **A test selected the wrong table.** A UI test used `at.dataframe[-1]` and got the sidebar's data-quality table instead of the trend table (`KeyError: 'Month'`). It now selects the table that has a "Month" column.
- **Stale UI module.** After `ui/presentation.py` was edited, the running Streamlit server kept serving the old module, so the first screenshots still showed the old version. Restarting Streamlit fixed this.
- **Screenshot timing.** A one-shot headless screenshot only captured Streamlit's loading skeleton, and early clicks sometimes happened before the page was ready. The screenshot script now waits until the answer is actually shown before capturing. This affected only the verification script, not the application.

## AI-generated code vs. verified functionality

**AI-generated.** All source code in `backend/`, `ui/` and `tests/`, the `.bat` scripts, `.streamlit/config.toml` and the first drafts of the documentation were written by Claude Code, following the developer's prompts. Generated code is not automatically correct, so the following was checked separately.

**Verified (with evidence):**

| Claim | Evidence |
|---|---|
| Cleaning flags exactly TXN0033, TXN0034 and TXN0051 in the real CSV | `test_real_csv_profile`; build script output |
| Real figures (1,439,200 total; Monitor 473,000; South 411,200; monthly values; March→April +16,800 / +7.50%) | Independent Pandas calculation on the raw CSV matched the SQL results; fixed in `test_real_*` tests |
| Revenue formula with fixed discounts | Hand-worked fixture values in `test_database.py` |
| Interpreter handles the listed phrasings and errors | 41 tests in `test_question_parser.py` |
| API status codes (200/400/404/422/503) and response shape | 19 tests in `test_api.py`; live HTTP calls against a running Uvicorn server |
| User text is never executed as SQL; the API cannot create or write the database | `test_sql_in_question_is_never_executed`, `test_missing_database_is_503`, read-only URI |
| UI shows correct answers for all five suggested questions | `AppTest` tests against the real data; screenshots of the running app |
| Friendly UI errors when the API is down or misbehaves | `test_frontend.py` failure-mode tests |

**Not verified:**

- The mobile layout and browsers other than Chrome.
- Behaviour with datasets covering several years, or much larger datasets. Only small test fixtures cover multiple years.
- Performance under load, and running several users at once.
- A formal accessibility review.
- Python versions other than 3.11.8.

## The developer's responsibility

Using AI does not move responsibility away from the developer. For this project, that means:

- **Understanding the code well enough to explain and change it.** The code was deliberately kept small (about 1,300 lines across eight Python modules) and commented for that reason.
- **Checking AI assumptions against the real requirements and data.** The discount correction (problem 1) is the clearest example: the AI's plan was plausible but wrong, and the developer's knowledge of the data fixed it.
- **Not trusting "tests pass" on its own.** Tests only check what they were written to check, as problems 3 and 4 show. Reviewing the test expectations and looking at the running app both matter.
- **Being honest about what the system is.** The interpreter is rule-based, not a generative LLM, and the documentation says so.
- **Not inventing data.** All reported figures come from the provided CSV through the application's own SQL, and were cross-checked independently.

## What would be improved with another day

1. **Optional local LLM for interpretation, still without generated SQL.** Add a fallback that uses a free local model (for example through Ollama) when the rule-based parser cannot understand a question. The model would only choose one of the five intents and extract months, as JSON. That output would be validated against the same whitelist before any fixed query runs. The rule-based parser would remain the default and the safety net.
2. **More question types:** revenue for a single month, lowest performers, category and sales-channel breakdowns, and custom date ranges. Each would be a new fixed SQL function plus parser rules and tests.
3. **Clearer interpreter feedback:** show users how their question was understood ("Interpreted as: compare March 2026 vs April 2026"), and add stricter matching so nonsense containing "sales" is not answered.
4. **Data reload:** an endpoint or UI button to rebuild the database after the CSV changes, plus a CSV upload with the same validation.
5. **Engineering:** GitHub Actions to run the tests on every push, structured logging, caching the data-quality call, and a Dockerfile.
6. **UI polish:** check and fix the mobile layout, make the suggestion buttons equal height, and add an accessibility review.
7. **Configurable currency:** let the user set the currency instead of showing plain numbers.
