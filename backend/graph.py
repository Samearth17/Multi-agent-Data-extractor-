import os
import re
import time
import logging
from dotenv import load_dotenv

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit, create_sql_agent
from backend.db import DB_PATH, get_all_tables, get_schema_prompt, engine

logging.getLogger("langchain").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(_env_path)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------

def get_available_providers() -> list[tuple[str, str]]:
    providers = []
    if os.getenv("GOOGLE_API_KEY"):
        providers.append(("google", "gemini-2.0-flash"))
        providers.append(("google", "gemini-1.5-flash"))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("groq", "llama-3.3-70b-versatile"))
        providers.append(("groq", "llama-3.1-70b-versatile"))
    if os.getenv("NVIDIA_API_KEY"):
        providers.append(("nvidia", "meta/llama-3.3-70b-instruct"))
        providers.append(("nvidia", "deepseek-ai/deepseek-v3"))
    return providers


def detect_provider() -> tuple[str, str]:
    available = get_available_providers()
    if not available:
        raise RuntimeError("No API key found. Set GOOGLE_API_KEY or GROQ_API_KEY in .env")
    return available[0]


def get_provider_status() -> dict:
    load_dotenv(_env_path, override=True)
    return {
        "google": bool(os.getenv("GOOGLE_API_KEY")),
        "groq":   bool(os.getenv("GROQ_API_KEY")),
        "nvidia": bool(os.getenv("NVIDIA_API_KEY")),
        "any_configured": any([
            os.getenv("GOOGLE_API_KEY"),
            os.getenv("GROQ_API_KEY"),
            os.getenv("NVIDIA_API_KEY"),
        ])
    }


def _build_llm(provider: str, model: str):
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model, temperature=0,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
    elif provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
    elif provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        return ChatNVIDIA(
            model=model, temperature=0,
            nvidia_api_key=os.getenv("NVIDIA_API_KEY")
        )
    raise ValueError(f"Unknown provider: {provider}")


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(focus_tables: list[str] = None) -> str:
    tables = focus_tables if focus_tables else get_all_tables()
    schema_text = get_schema_prompt(tables_list=tables)

    agents_md = ""
    agents_path = os.path.join(BASE_DIR, "AGENTS.md")
    if os.path.exists(agents_path):
        with open(agents_path) as f:
            agents_md = f.read()

    if not tables:
        return (
            "You are an AI data analyst. No data has been uploaded yet. "
            "Tell the user they need to upload a CSV file first."
        )

    table_list = ", ".join(f"`{t}`" for t in tables)

    return f"""You are an AI data analyst. You can query any of the available tables.

## Available Tables
{table_list}

## Schemas
{schema_text}

## Extra context
{agents_md[:1500]}
"""


# ---------------------------------------------------------------------------
# Markdown table parser  (used by agents.py too)
# ---------------------------------------------------------------------------

def _parse_markdown_table(text: str) -> dict:
    """Parse a markdown table in *text* and return {columns, data, ...}."""
    if not text:
        return {"data": [], "columns": [], "chart_type": None,
                "numeric_columns": [], "label_column": None}

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-\|]+\|$", lines[i + 1]):
            header_idx = i
            break

    if header_idx is None:
        return {"data": [], "columns": [], "chart_type": None,
                "numeric_columns": [], "label_column": None}

    headers = [h.strip() for h in lines[header_idx].strip("|").split("|")]
    data_rows = []
    for line in lines[header_idx + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            data_rows.append(dict(zip(headers, cells)))

    numeric_cols = []
    for col in headers:
        vals = []
        for row in data_rows:
            v = row.get(col, "")
            try:
                float(str(v).replace(",", ""))
                vals.append(True)
            except ValueError:
                vals.append(False)
        if vals and all(vals):
            numeric_cols.append(col)

    label_col = next((h for h in headers if h not in numeric_cols), None)
    chart_type = "bar" if numeric_cols else None

    return {
        "data": data_rows,
        "columns": headers,
        "chart_type": chart_type,
        "numeric_columns": numeric_cols,
        "label_column": label_col,
    }


# ---------------------------------------------------------------------------
# Main agent – SQL agent via LangChain
# ---------------------------------------------------------------------------

_agent_cache: dict = {}


def reset_agent():
    """Invalidate the cached SQL agent so the next call re-builds it."""
    global _agent_cache
    _agent_cache = {}


def _get_or_build_agent(provider: str, model: str, focus_tables: list[str] = None):
    cache_key = (provider, model, tuple(sorted(focus_tables or [])))
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    llm = _build_llm(provider, model)
    db  = SQLDatabase(engine)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    system_message = _build_system_prompt(focus_tables)
    agent = create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        agent_type="openai-tools",
        verbose=False,
        system_message=system_message,
        handle_parsing_errors=True,
    )
    _agent_cache[cache_key] = agent
    return agent


def run_graph_agent(question: str, focus_tables: list[str] = None) -> dict:
    """
    Run a natural-language question against the database using LangChain SQL agent.
    Returns a standardised result dict.
    """
    load_dotenv(_env_path, override=True)
    start = time.time()

    tables = focus_tables if focus_tables else get_all_tables()
    if not tables:
        return {
            "status": "no_data",
            "sql": "",
            "result": {
                "type": "message",
                "message": "No data uploaded yet. Please upload a file first.",
            },
            "elapsed": 0.0,
        }

    available = get_available_providers()
    if not available:
        return {
            "status": "no_api_key",
            "sql": "",
            "result": {
                "type": "message",
                "message": (
                    "No API key configured. "
                    "Please add a GOOGLE_API_KEY or GROQ_API_KEY in the settings panel."
                ),
            },
            "elapsed": 0.0,
        }

    last_error = ""
    for provider, model in available:
        try:
            agent = _get_or_build_agent(provider, model, focus_tables)
            result = agent.invoke({"input": question})
            answer = result.get("output", str(result))

            # Extract SQL from intermediate steps
            sql = ""
            for step in reversed(result.get("intermediate_steps", [])):
                if isinstance(step, (list, tuple)) and len(step) >= 1:
                    action = step[0]
                    if hasattr(action, "tool_input"):
                        ti = action.tool_input
                        q  = ti.get("query", "") if isinstance(ti, dict) else str(ti)
                        if q.strip().upper().startswith("SELECT"):
                            sql = q.strip().rstrip(";")
                            break

            tabular = _parse_markdown_table(answer)
            elapsed = round(time.time() - start, 2)

            return {
                "status": "success",
                "sql": sql,
                "result": {
                    "type": "answer",
                    "answer": answer,
                    "data": tabular.get("data", []),
                    "columns": tabular.get("columns", []),
                    "row_count": len(tabular.get("data", [])),
                    "chart_type": tabular.get("chart_type"),
                    "numeric_columns": tabular.get("numeric_columns", []),
                    "label_column": tabular.get("label_column"),
                },
                "elapsed": elapsed,
                "provider": provider,
            }

        except Exception as e:
            last_error = str(e)
            print(f"[graph] Provider {provider}/{model} failed: {last_error[:200]}")
            # Invalidate cache for this provider on failure
            cache_key = (provider, model, tuple(sorted(focus_tables or [])))
            _agent_cache.pop(cache_key, None)
            continue

    elapsed = round(time.time() - start, 2)
    return {
        "status": "error",
        "sql": "",
        "result": {
            "type": "message",
            "message": _friendly_error(last_error),
        },
        "elapsed": elapsed,
    }


def _friendly_error(err: str) -> str:
    e = err.lower()
    if "429" in err or "quota" in e or "resource_exhausted" in e:
        return (
            "Rate limit reached on the AI provider. "
            "Wait 30–60 seconds and try again, or switch to a different provider."
        )
    if "api key" in e or "authentication" in e or "invalid" in e:
        return "Invalid or missing API key. Please update your key in the settings panel."
    if "no such table" in e:
        return "The requested table does not exist. Try re-uploading your file."
    if "timeout" in e:
        return "The request timed out. Try a simpler question or a smaller dataset."
    return f"Agent error: {err[:300]}"
