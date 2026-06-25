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
        return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=os.getenv("GOOGLE_API_KEY"))
    elif provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
    elif provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        return ChatNVIDIA(model=model, temperature=0, nvidia_api_key=os.getenv("NVIDIA_API_KEY"))
    raise ValueError(f"Unknown provider: {provider}")


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

    return f"""You are AI data analyst. You can query any of the available tables.

## Available Tables
{table_list}

## Schemas
{schema_text}


## Extra context
{agents_md[:1500]}
"""

def _run_deepagents(question: str, llm, focus_tables: list[str] = None) -> dict:
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from backend.db import get_schema_prompt

    tables = focus_tables if focus_tables else get_all_tables()
    db = SQLDatabase(engine,
        sample_rows_in_table_info=2,
        include_tables=tables if tables else None,
    )
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    sql_tools = toolkit.get_tools()

    agent = create_deep_agent(
        model=llm,
        memory=[os.path.join(BASE_DIR, "AGENTS.md")],
        tools=sql_tools,
        subagents=[],
        backend=FilesystemBackend(root_dir=BASE_DIR, virtual_mode=False),
    )

    system_prompt = _build_system_prompt(focus_tables=focus_tables)
    result = agent.invoke({"messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question}
    ]})
    final_msg = result["messages"][-1]

    content = getattr(final_msg, "content", str(final_msg))
    if isinstance(content, list):
        answer = "\n".join([block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"])
    else:
        answer = str(content)

    sql = _extract_sql_from_messages(result["messages"])
    return {"answer": answer, "sql": sql, "tabular": _parse_markdown_table(answer)}

def _run_direct_sql_agent(question: str, llm, focus_tables: list[str] = None) -> dict:
    tables = focus_tables if focus_tables else get_all_tables()
    db = SQLDatabase(engine,
        sample_rows_in_table_info=2,
        include_tables=tables if tables else None,
    )

    system_msg = _build_system_prompt(focus_tables=focus_tables)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)

    agent = create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        verbose=False,
        agent_type="tool-calling",
        system_message=system_msg,
        max_iterations=12,
        handle_parsing_errors=True,
    )
    try:
        result = agent.invoke({"input": question})
        answer = result.get("output", str(result))

        # Extract SQL from intermediate steps
        sql = ""
        for step in reversed(result.get("intermediate_steps", [])):
            if isinstance(step, (list, tuple)) and len(step) >= 1:
                action = step[0]
                if hasattr(action, "tool_input"):
                    ti = action.tool_input
                    query = ti.get("query", "") if isinstance(ti, dict) else str(ti)
                    if query.strip().upper().startswith("SELECT"):
                        sql = query.strip().rstrip(";")
                        break

        return {
            "answer": answer,
            "sql": sql,
            "tabular": _parse_markdown_table(answer)
        }
    except Exception as e:
        print(f"[direct-sql] Agent execution failed: {e}")
        return {
            "answer": f"I encountered an error while analyzing the data: {str(e)}",
            "sql": "",
            "tabular": {"data": [], "columns": []}
        }


_cache: dict = {"provider": None, "model": None}


def reset_agent():
    _cache.update({"provider": None, "model": None})


def run_graph_agent(question: str) -> dict:
    start = time.time()
    load_dotenv(_env_path, override=True)

    if not get_provider_status()["any_configured"]:
        return {
            "status": "no_api_key",
            "sql": "",
            "result": {
                "type": "setup_required",
                "message": "No API key configured. Add GOOGLE_API_KEY or GROQ_API_KEY to your .env file.",
            },
            "attempts": 0, "elapsed": 0.0, "provider": None,
        }

    tables = get_all_tables()
    if not tables:
        return {
            "status": "no_data",
            "sql": "",
            "result": {
                "type": "no_data",
                "message": "No data uploaded yet. Please upload a CSV file first.",
            },
            "attempts": 0, "elapsed": 0.0, "provider": None,
        }

    available_providers = get_available_providers()

    last_error = "Unknown error"

    for provider, model_name in available_providers:
        try:
            _cache.update({"provider": provider, "model": model_name})
            print(f"Attempting with: {provider} ({model_name}) | Tables: {tables}")

            llm = _build_llm(provider, model_name)

            # Use direct SQL agent for all providers to ensure stable parsing
            data = _run_direct_sql_agent(question, llm)

            elapsed = round(time.time() - start, 2)
            tabular = data["tabular"]

            return {
                "status": "success",
                "sql": data["sql"],
                "result": {
                    "type": "answer",
                    "answer": data["answer"],
                    "data": tabular.get("data", []),
                    "columns": tabular.get("columns", []),
                    "row_count": len(tabular.get("data", [])),
                    "chart_type": tabular.get("chart_type"),
                    "numeric_columns": tabular.get("numeric_columns", []),
                    "label_column": tabular.get("label_column"),
                },
                "attempts": 1,
                "elapsed": elapsed,
                "provider": provider,
            }

        except Exception as e:
            err = str(e)
            last_error = err
            print(f"Provider {provider} failed: {err[:200]}")
            continue

    elapsed = round(time.time() - start, 2)
    return {
        "status": "error",
        "sql": "",
        "result": {"type": "error", "message": f"All providers failed. Last error: {last_error}", "data": [], "columns": []},
        "attempts": len(available_providers), "elapsed": elapsed, "message": last_error,
    }


def _extract_sql_from_messages(messages) -> str:
    for msg in reversed(messages):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.get("args", {}) if isinstance(tc, dict) else {}
                q = args.get("query", "")
                if q and q.strip().upper().startswith("SELECT"):
                    return q.strip().rstrip(";")
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        m = re.search(r"```sql\s*\n?(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(";")
    return ""


def _parse_markdown_table(text: str) -> dict:
    """
    Parse a markdown table from LLM output into structured data.

    Key fixes:
    - len(lines) < 2 instead of < 3: single-row result tables are no longer
      silently discarded (header + separator = 2 lines minimum).
    - String values use the original cell text on numeric parse failure,
      so values like "New York, NY" are not mangled to "New York NY".
    """
    empty = {"data": [], "columns": [], "chart_type": None, "numeric_columns": [], "label_column": None}
    if isinstance(text, list):
        text = "\n".join([str(m) for m in text])
    if not isinstance(text, str):
        text = str(text)

    lines = [l for l in text.split("\n") if "|" in l]

    # FIX: was < 3, which dropped every 1-row result.
    # A valid markdown table only needs header + separator (2 lines).
    if len(lines) < 2:
        return empty

    try:
        headers = [h.strip() for h in lines[0].strip("|").split("|") if h.strip()]
        data = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            row = {}
            for i, h in enumerate(headers):
                raw = cells[i].strip()
                # Strip commas/$  only for numeric conversion attempt.
                # On failure, restore the original `raw` string so values like
                # "New York, NY" are not silently corrupted.
                val = raw.replace(",", "").replace("$", "").strip()
                try:
                    row[h] = int(val)
                except ValueError:
                    try:
                        row[h] = round(float(val), 2)
                    except ValueError:
                        row[h] = raw  # preserve original
            data.append(row)

        if not data:
            return empty

        numeric = [c for c in headers if all(isinstance(r.get(c), (int, float)) for r in data)]
        labels  = [c for c in headers if c not in numeric]

        label_col  = labels[0] if labels else (numeric[0] if numeric else None)
        value_cols = [c for c in numeric if c != label_col] if not labels else numeric

        chart = ("doughnut" if len(data) <= 6 else "bar") if label_col and value_cols else None

        return {
            "data": data,
            "columns": headers,
            "chart_type": chart,
            "numeric_columns": value_cols,
            "label_column": label_col,
        }
    except Exception:
        return empty
