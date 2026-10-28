"""Small HTTP client for the FastAPI backend.

The Streamlit app never touches the database or calculates anything itself;
it only calls these functions. Every failure is turned into a friendly
message, so users never see a Python traceback.
"""

import os
from dataclasses import dataclass, field

import requests

API_URL = os.environ.get("BI_API_URL", "http://127.0.0.1:8000")
TIMEOUT_SECONDS = 15

ASK_FIELDS = {"question", "intent", "answer", "data", "chart_type", "data_quality"}
DATA_QUALITY_FIELDS = {"total_rows", "valid_rows", "excluded_rows", "excluded"}


@dataclass
class ApiResult:
    ok: bool
    data: dict | None = None
    error: str | None = None
    suggestions: list[str] = field(default_factory=list)  # shown for unsupported questions


def _call(method: str, path: str, base_url: str, payload: dict | None = None) -> ApiResult:
    """Send one request and translate every kind of failure into an ApiResult."""
    try:
        response = requests.request(
            method, f"{base_url}{path}", json=payload, timeout=TIMEOUT_SECONDS
        )
    except requests.ConnectionError:
        return ApiResult(
            ok=False,
            error=f"Cannot reach the analytics server at {base_url}. "
                  "Please start it with start_api.bat and try again.",
        )
    except requests.Timeout:
        return ApiResult(ok=False, error="The analytics server took too long to respond.")
    except requests.RequestException:
        return ApiResult(ok=False, error="Could not contact the analytics server.")

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 200:
        if not isinstance(body, dict):
            return ApiResult(ok=False, error="The server returned an empty or unreadable response.")
        return ApiResult(ok=True, data=body)

    detail = body.get("detail") if isinstance(body, dict) else None
    if response.status_code == 400 and isinstance(detail, dict):
        return ApiResult(
            ok=False,
            error=detail.get("message") or "That question is not supported yet.",
            suggestions=detail.get("supported_questions", []),
        )
    if response.status_code == 422:
        return ApiResult(ok=False, error="Please type a question (up to 500 characters).")
    if response.status_code in (404, 503) and isinstance(detail, str):
        return ApiResult(ok=False, error=detail)
    return ApiResult(
        ok=False,
        error=f"Something went wrong on the server (status {response.status_code}). Please try again.",
    )


def _require_fields(result: ApiResult, fields: set[str]) -> ApiResult:
    """Treat a 200 response that is missing expected fields as an error."""
    if result.ok and not fields.issubset(result.data):
        return ApiResult(ok=False, error="The server returned an incomplete response.")
    return result


def ask_question(question: str, base_url: str = API_URL) -> ApiResult:
    question = (question or "").strip()
    if not question:
        return ApiResult(ok=False, error="Please type a question.")
    result = _call("POST", "/ask", base_url, {"question": question})
    return _require_fields(result, ASK_FIELDS)


def get_data_quality(base_url: str = API_URL) -> ApiResult:
    return _require_fields(_call("GET", "/data-quality", base_url), DATA_QUALITY_FIELDS)
