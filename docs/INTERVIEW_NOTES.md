# Interview Notes

Plain-language notes for explaining this project and the related AI concepts in an interview.

## 1. The project in one minute

> "I built a small business-intelligence assistant. You type a question like *'Which region has the highest sales?'* and it answers using the company's sales CSV.
>
> First, Pandas reads the CSV and checks every row. Returned orders, zero quantities and missing prices are flagged, but never deleted or changed. The rows go into a SQLite database, where a view called `valid_sales` holds only the rows that count, with revenue = quantity × price − discount.
>
> When a question comes in, a rule-based interpreter works out which of five supported questions it is, for example 'top region'. It then runs one fixed, pre-written SQL query. It never writes or runs SQL from the user or an AI.
>
> FastAPI serves the answers as JSON, and Streamlit shows them with charts and a data-quality panel. There are 142 automated tests, and I cross-checked the real figures with an independent Pandas calculation."

Key numbers: 51 rows, 48 valid, 3 excluded. Total revenue is 1,439,200.00. The top product is Monitor, the top region is South, the best month is May 2026, and April was 7.50% higher than March.

## 2. The technologies

### FastAPI

A Python framework for building web APIs. You write normal Python functions and FastAPI turns them into HTTP endpoints.

- Uses **Pydantic** models to validate input automatically. Here, an empty question is rejected with a 422 error before my code even runs.
- Generates interactive API docs at `/docs`.
- Has **dependency injection**: my `get_db` dependency opens a read-only database connection for each request and always closes it. Tests swap in a test database with `app.dependency_overrides`.

### SQLite

A complete SQL database stored in a single file, built into Python (`import sqlite3`). There is no server to install.

- I used it for real SQL features: `GROUP BY`, a `VIEW`, `strftime` for months, and `?` parameters.
- It is a good fit for small, mostly-read data. For many users writing at the same time, I would use PostgreSQL.

### Pandas

A Python library for working with tables (DataFrames). I used it for the messy part: reading the CSV as text, converting numbers (`pd.to_numeric(errors="coerce")` turns bad values into NaN instead of crashing), parsing dates, and flagging invalid rows.

The rule I followed: Pandas cleans the data, SQL does the analytics.

### Streamlit

A Python library for building web UIs without HTML or JavaScript. The script reruns from top to bottom on every interaction, and `st.session_state` remembers values between reruns, such as the question history.

My Streamlit app never touches the database. It only calls the FastAPI endpoints over HTTP, so the frontend and backend stay separate.

### Pytest

Python's most popular testing framework. Tests are plain functions with `assert`.

- **Fixtures** (in `conftest.py`) set up shared things like a temporary test database.
- `@pytest.mark.parametrize` runs one test with many inputs. I used it to check about 20 phrasings of questions.
- I also used FastAPI's `TestClient` and Streamlit's `AppTest` to test the API and the UI without starting real servers.

## 3. AI concepts

### Generative AI

AI models that **create new content**, such as text, code, images or audio, by learning patterns from huge amounts of data. Large Language Models (LLMs) such as GPT, Claude and Gemini are generative AI for text. They predict the next words very well, but they can also produce confident, plausible-sounding mistakes ("hallucinations").

### Agentic AI

An AI system that does not just answer once. It **works towards a goal in steps**:

- It plans what to do.
- It uses **tools** (search, run code, call an API, read files).
- It looks at the results and decides the next step, in a loop, until the task is done.

Example: the coding assistant used to build this project read files, ran tests, saw failures and fixed them. That is agentic behaviour. Agents need guardrails, because they act, not just talk.

### RAG (Retrieval-Augmented Generation)

A pattern for making an LLM answer from **your own data** instead of only what it memorised in training:

1. **Retrieve:** find the pieces of your documents relevant to the question.
2. **Augment:** add those pieces to the prompt.
3. **Generate:** the LLM writes an answer based on them, ideally with citations.

Classic RAG splits documents into chunks, turns each chunk into a numeric **embedding** (vector), stores the vectors in a **vector database**, and finds chunks by similarity to the question's embedding.

### Vectorless RAG

RAG where the retrieval step does **not use embeddings or a vector database**. Instead, it uses other ways to find the right information:

- Keyword search (for example BM25).
- **SQL queries over structured data.**
- Letting the LLM navigate a document's structure, such as a table of contents or tree index, the way a person would.

It can be simpler, more precise for exact facts and numbers, and easier to explain than similarity search.

**How this relates to my project:** the retrieval part is similar in spirit to vectorless retrieval, because answers come from exact SQL queries rather than similarity search. But there is **no LLM generating text**: the answer sentences come from templates. So, strictly, this project is *not* RAG. A natural extension would be to let an LLM phrase or explain the SQL results, which would make it vectorless RAG.

### LangChain

An open-source framework (Python and JavaScript) for building LLM applications. It provides ready-made building blocks:

- Connectors to many LLM providers.
- Prompt templates.
- Document loaders and retrievers for RAG.
- Tool calling, and ways to chain these steps together.

Its sister project, LangGraph, is for building agents as graphs of steps. It is useful when an app needs many of these parts. For my small app it would have added complexity without benefit.

### Google ADK (Agent Development Kit)

Google's open-source framework for building AI **agents** and **multi-agent systems** in code (Python, plus other languages).

- You define agents, give them tools and instructions, and compose several agents together.
- It includes tools for testing, evaluating and deploying them, for example on Google Cloud.
- It works best with Google's Gemini models but can use others.

### Dify

An open-source **platform** for building LLM apps through a visual, low-code interface.

- You drag and drop workflow steps, connect models, upload documents to build a RAG knowledge base, and publish the result as a chatbot or an API.
- It can be self-hosted or used as a cloud service.

It is good for quickly building and iterating on LLM apps without writing much code.

### Why this app uses rule-based interpretation instead of a live LLM

1. **The challenge rules:** no paid APIs, and never execute LLM-generated SQL. A rule-based interpreter satisfies both completely.
2. **Correctness:** business numbers must be exact. Each fixed SQL query is tested. An LLM could misread a question or quietly change the logic.
3. **Determinism:** the same question always gives the same answer, which makes it testable with Pytest. LLM output can vary from run to run.
4. **Small scope:** only five question types are needed. Keyword rules plus typo tolerance cover them reliably.
5. **Cost and setup:** no API key, no internet connection, no GPU and no per-question cost.
6. **Honesty:** I describe it as "AI-assisted, rule-based interpretation", not as an LLM.

**How I would add an LLM safely:** use a local model only to **classify** the question into one of the five intents and extract the months, as JSON. Then validate that output against the same whitelist before running the same fixed queries. The LLM would never write SQL.

## 4. Likely interview questions

**1. Walk me through what happens when a user asks a question.**
Streamlit sends `POST /ask` with the question. Pydantic validates it. FastAPI opens the SQLite database read-only, and the parser maps the question to an intent (plus months, for comparisons). The matching analytics function runs a fixed SQL query on the `valid_sales` view. FastAPI returns the answer sentence, the supporting data, a chart type and the data-quality summary, and Streamlit displays them.

**2. How did you handle returned orders, zero quantities and missing prices?**
Each row is checked in Pandas and gets `is_valid` and `invalid_reason`. Only valid rows appear in the `valid_sales` view. The invalid rows stay in the `sales` table, so I can report them. Nothing is deleted, and missing prices are stored as NULL, never guessed.

**3. Why not just drop the bad rows?**
The brief said not to modify sales records. Keeping them also makes the result transparent: the UI shows exactly which three transactions were excluded and why.

**4. How do you prevent SQL injection?**
User text never becomes SQL. The parser only outputs an intent name and validated `YYYY-MM` months. Months are passed as `?` parameters. The only variable column name comes from a hard-coded whitelist. The API also opens the database in read-only mode, and a test sends `'; DROP TABLE sales; --` and confirms the data is still there.

**5. Why is the database opened read-only?**
It is defence in depth: even if there were a bug, the API could not change the data. It also means a missing database file returns a clear 503 error instead of SQLite quietly creating an empty file.

**6. How did you handle different date formats?**
`parse_date` tries a fixed list of formats (`DD-MM-YYYY`, `DD/MM/YYYY`, `YYYY-MM-DD`, `DD.MM.YYYY`) and stores dates as ISO `YYYY-MM-DD`, so SQLite can group them by month. Impossible dates such as 31-02-2026 are flagged as invalid. I assumed day-first dates because the real file is clearly day-first (for example 25-01-2026).

**7. What happens if a month has no sales?**
In the trend, every month between the first and last record is shown, and a month with no valid sales shows 0. In a comparison, a month with records but zero valid revenue gives a difference, but the percentage change is "not defined", to avoid dividing by zero. A month that isn't in the data at all returns a 404 error.

**8. How did you make sure the numbers are correct?**
Three ways:

- Unit tests on a small hand-written dataset with hand-calculated answers.
- An independent Pandas calculation on the raw CSV that matched the SQL results exactly.
- Regression tests that lock in the real figures.

**9. What is the difference between a unit test and an integration test in your project?**
`test_analytics.py` tests individual functions against a test database (unit level). `test_api.py` sends HTTP requests through FastAPI to SQLite. The `AppTest` tests drive the Streamlit page all the way to the database (integration level).

**10. Why did you separate Streamlit and FastAPI instead of one Streamlit app?**
Separation of concerns. The backend can be tested and used by other clients (curl, another frontend) without the UI, and the UI cannot accidentally duplicate or change calculations. It also mirrors how real systems are built.

**11. What is a SQL view and why did you use one?**
A view is a saved query that behaves like a table. `valid_sales` holds the revenue formula and the "valid rows only" rule in one place, so all five queries automatically use the same rules.

**12. What happens if the API is down when someone uses the UI?**
`api_client.py` catches the connection error and returns a friendly message ("Cannot reach the analytics server… start it with start_api.bat"). The Streamlit config also hides Python tracebacks from users. This is covered by a test.

**13. How does the interpreter handle typos and different phrasings?**
It has synonym lists for each concept (for example "region", "area", "zone"). Unknown words of 4+ letters are matched to the closest vocabulary word with Python's `difflib` at 80% similarity, so "revnue" becomes "revenue". A fixed order of rules decides the intent, and unclear questions get a helpful error instead of a guess.

**14. What are the limitations, and what would you do next?**
It only understands five question types, and keyword matching can be fooled by unrelated text containing "sales". It is single-user and local, and the database must be rebuilt manually when the CSV changes. Next, I would add an optional local LLM that only classifies intents, behind the same whitelist. I would also add more question types (single month, lowest, by category), a reload endpoint, CI with GitHub Actions, and testing on real mobile devices.

**15. How did you use AI to build this, and how do you know the code is right?**
I used Claude Code in VS Code, with stage-by-stage prompts that I planned with ChatGPT's help. The AI wrote the code, but I checked it through tests, independent cross-checks of the figures, running the real servers, and screenshots. For example, the AI's first plan wrongly assumed discounts were percentages; I corrected that from the data specification. The screenshots also revealed UI problems that passing tests had missed. I am responsible for understanding and being able to explain every part.
