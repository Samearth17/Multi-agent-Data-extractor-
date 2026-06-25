import os
import io
import re
import time
from dotenv import load_dotenv

from backend.db import DB_PATH, get_all_tables, get_schema_prompt, get_sample_data, engine
from backend.graph import _build_llm, get_available_providers, _parse_markdown_table

_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

AGENT_REGISTRY = {
    "data_extractor": {
        "id": "data_extractor",
        "name": "Data Extractor",
        "description": "Top-level orchestrator. Routes tasks to Structured or Unstructured sub-agents.",
        "type": "orchestrator",
        "color": "#2dd4bf",
        "icon": "fiu",
        "children": ["structured_data", "unstructured_data"],
        "position": {"x": 400, "y": 60},
        "accepts": [".csv", ".xlsx", ".xls", ".pdf", ".txt", ".log", ".md"],
        "accept_label": "Any file",
    },
    "structured_data": {
        "id": "structured_data",
        "name": "Structured Data Agent",
        "description": "Handles tabular data files (CSV, Excel). Delegates to CSV or XLS specialists.",
        "type": "manager",
        "color": "#34d399",
        "icon": "tac",
        "parent": "data_extractor",
        "children": ["csv_agent", "xls_agent"],
        "position": {"x": 200, "y": 250},
        "accepts": [".csv", ".xlsx", ".xls"],
        "accept_label": "CSV / Excel",
    },
    "unstructured_data": {
        "id": "unstructured_data",
        "name": "Unstructured Data Agent",
        "description": "Handles documents and text files. Delegates to PDF or Text specialists.",
        "type": "manager",
        "color": "#fbbf24",
        "icon": "des",
        "parent": "data_extractor",
        "children": ["pdf_agent", "text_agent"],
        "position": {"x": 600, "y": 250},
        "accepts": [".pdf", ".txt", ".log", ".md"],
        "accept_label": "PDF / Text",
    },
    "csv_agent": {
        "id": "csv_agent",
        "name": "CSV Agent",
        "description": "Specialist for parsing and querying CSV files using SQL.",
        "type": "specialist",
        "color": "#34d399",
        "icon": "csv",
        "parent": "structured_data",
        "children": [],
        "position": {"x": 100, "y": 450},
        "accepts": [".csv"],
        "accept_label": "CSV files",
    },
    "xls_agent": {
        "id": "xls_agent",
        "name": "XLS Agent",
        "description": "Specialist for reading and analyzing Excel spreadsheets.",
        "type": "specialist",
        "color": "#2dd4bf",
        "icon": "exc",
        "parent": "structured_data",
        "children": [],
        "position": {"x": 300, "y": 450},
        "accepts": [".xlsx", ".xls"],
        "accept_label": "Excel files",
    },
    "pdf_agent": {
        "id": "pdf_agent",
        "name": "PDF Agent",
        "description": "Specialist for extracting text and tables from PDF documents.",
        "type": "specialist",
        "color": "#f87171",
        "icon": "pdf",
        "parent": "unstructured_data",
        "children": [],
        "position": {"x": 500, "y": 450},
        "accepts": [".pdf"],
        "accept_label": "PDF files",
    },
    "text_agent": {
        "id": "text_agent",
        "name": "Text Agent",
        "description": "Specialist for analyzing raw text and log files.",
        "type": "specialist",
        "color": "#a78bfa",
        "icon": "text",
        "parent": "unstructured_data",
        "children": [],
        "position": {"x": 700, "y": 450},
        "accepts": [".txt", ".log", ".md"],
        "accept_label": "Text files",
    },
}


def get_all_agents() -> list[dict]:
    return list(AGENT_REGISTRY.values())


def get_agent_connections() -> list[dict]:
    connections = []
    for agent in AGENT_REGISTRY.values():
        for child_id in agent.get("children", []):
            connections.append({"from": agent["id"], "to": child_id})
    return connections


def get_tables_for_agent(agent_id: str) -> list[str]:
    from backend.db import get_all_tables, DATA_DIR
    import os
    tables = get_all_tables()
    if agent_id == "data_extractor":
        return tables

    agent_tables = []
    for t in tables:
        csv_path = os.path.join(DATA_DIR, f"{t}.csv")
        xls_path = os.path.join(DATA_DIR, f"{t}.xlsx")
        pdf_path = os.path.join(DATA_DIR, f"{t}.pdf")
        txt_path = os.path.join(DATA_DIR, f"{t}.txt")
        md_path  = os.path.join(DATA_DIR, f"{t}.md")
        log_path = os.path.join(DATA_DIR, f"{t}.log")

        if agent_id in ("csv_agent", "structured_data") and os.path.exists(csv_path):
            agent_tables.append(t)
        elif agent_id in ("xls_agent", "structured_data") and os.path.exists(xls_path):
            agent_tables.append(t)
        elif agent_id in ("pdf_agent", "unstructured_data") and os.path.exists(pdf_path):
            agent_tables.append(t)
        elif agent_id in ("text_agent", "unstructured_data") and (
            os.path.exists(txt_path) or os.path.exists(md_path) or os.path.exists(log_path)
        ):
            agent_tables.append(t)

    # Fallback: if csv_agent and no file tags found, give it all tables
    if agent_id in ("csv_agent", "structured_data") and not agent_tables:
        for t in tables:
            if not any(
                os.path.exists(os.path.join(DATA_DIR, f"{t}{ext}"))
                for ext in [".csv", ".xlsx", ".pdf", ".txt", ".md", ".log"]
            ):
                agent_tables.append(t)

    return agent_tables


# ---------------------------------------------------------------------------
# AGENT PROMPT — schema cap raised from 2 000 to 6 000 chars
# This was the root cause of extraction failures on real datasets.
# ---------------------------------------------------------------------------

def _build_agent_prompt(agent_id: str, question: str, focus_tables: list[str] = None) -> str:
    agent  = AGENT_REGISTRY[agent_id]
    tables = focus_tables if focus_tables is not None else get_all_tables()
    schema_text = get_schema_prompt(tables_list=tables)
    table_list  = ", ".join(f"`{t}`" for t in tables) if tables else "No tables uploaded"

    role = _get_role_prompt(agent_id)

    # Raised from 2 000 to 6 000 — small models can handle this; truncation was
    # silently cutting schemas mid-table, causing column-name hallucinations.
    if len(schema_text) > 6000:
        schema_text = schema_text[:6000] + "\n... (schema truncated)"

    return f"""You are the **{agent['name']}** — {agent['description']}

## Role
{role}

## Available Tables
{table_list}

## Schema
{schema_text}

## Rules
- ALWAYS query the database to answer the question; do NOT guess or say "I don't know".
- If data exists, run a SQL query and return real results.
- Format tabular results as a proper Markdown table:
  | Col1 | Col2 |
  |------|------|
  | val  | val  |
- After the table, add a brief plain-language summary.
- NEVER output raw Python, import statements, or JSON blobs.
- If the query returns 0 rows, say so explicitly — do NOT say "I don't know".
"""


def _get_role_prompt(agent_id: str) -> str:
    prompts = {
        "data_extractor": (
            "You are the top-level Data Extractor. Query the SQL database directly. "
            "Analyze the question and return data, statistics, and insights as markdown tables."
        ),
        "structured_data": (
            "You specialize in structured/tabular data. Run SQL against uploaded CSV and Excel tables. "
            "Focus on column relationships and statistical summaries."
        ),
        "unstructured_data": (
            "You specialize in document and text data stored in SQL tables. "
            "Query the database and explain findings in plain language."
        ),
        "csv_agent": (
            "You are a CSV data specialist. Query CSV-sourced tables with SQL and extract insights."
        ),
        "xls_agent": (
            "You are an Excel specialist. Query Excel-sourced tables with SQL. "
            "Provide pivot-style summaries and formatted output."
        ),
        "pdf_agent": (
            "You are a PDF document specialist. Query PDF-sourced tables with SQL "
            "and summarize document-related data."
        ),
        "text_agent": (
            "You are a Text/Log file specialist. Query text-sourced tables with SQL. "
            "Excel at pattern recognition, keyword extraction, and log summarization."
        ),
    }
    return prompts.get(agent_id, "Analyze the data and provide insights.")


# ---------------------------------------------------------------------------
# CORE AGENT RUNNER — with improved error handling
# ---------------------------------------------------------------------------

def run_agent_query(agent_id: str, question: str, focus_tables: list[str] = None) -> dict:
    if agent_id not in AGENT_REGISTRY:
        return {
            "status": "error",
            "agent_id": agent_id,
            "result": {"message": f"Unknown agent: {agent_id}"},
        }

    load_dotenv(_env_path, override=True)
    start = time.time()

    available = get_available_providers()
    if not available:
        return {
            "status": "no_api_key",
            "agent_id": agent_id,
            "result": {"message": "No API key configured. Please add your API key."},
            "elapsed": 0.0,
        }

    tables = get_tables_for_agent(agent_id)
    if focus_tables:
        tables = [t for t in tables if t in focus_tables]

    if not tables:
        return {
            "status": "success",
            "agent_id": agent_id,
            "agent_name": AGENT_REGISTRY[agent_id].get("name", agent_id),
            "sql": "",
            "result": {
                "type": "answer",
                "answer": f"No relevant data tables found for the **{AGENT_REGISTRY[agent_id].get('name', agent_id)}**. Upload a file first.",
                "data": [], "columns": [], "row_count": 0,
            },
            "elapsed": round(time.time() - start, 2),
        }

    last_error = "Unknown error"

    for provider, model_name in available:
        try:
            print(f"[{agent_id}] Trying {provider} ({model_name}) | Tables: {tables}")
            llm = _build_llm(provider, model_name)
            system_prompt = _build_agent_prompt(agent_id, question, focus_tables=tables)

            from langchain_community.utilities import SQLDatabase
            from langchain_community.agent_toolkits import create_sql_agent
            from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit

            db = SQLDatabase(engine, sample_rows_in_table_info=2, include_tables=tables)
            toolkit = SQLDatabaseToolkit(db=db, llm=llm)

            agent = create_sql_agent(
                llm=llm,
                toolkit=toolkit,
                verbose=False,
                agent_type="tool-calling",
                system_message=system_prompt,
                max_iterations=10,
                handle_parsing_errors=True,
            )

            try:
                result = agent.invoke({"input": question})
                answer = result.get("output", str(result))
            except Exception as invoke_err:
                err_str = str(invoke_err)
                if "Extra data" in err_str or "JSONDecodeError" in err_str:
                    answer = _salvage_from_error(err_str, tables)
                    result = {"output": answer, "intermediate_steps": []}
                else:
                    raise

            tabular = None

            if isinstance(answer, str) and _is_raw_tool_output(answer):
                answer, tabular = _salvage_from_raw_output(answer, tables, result)

            if isinstance(answer, str) and _is_unhelpful_answer(answer):
                print(f"[{agent_id}] Unhelpful answer detected, running direct SQL fallback")
                answer, tabular = _direct_sql_fallback(question, tables)

            sql = _extract_sql_from_steps(result.get("intermediate_steps", []))

            elapsed = round(time.time() - start, 2)
            if not tabular:
                tabular = _parse_markdown_table(answer)

            # Final safety: if tabular is still empty but we have an answer, run
            # a direct raw fallback so the frontend always has data to display.
            if not tabular.get("data") and tables:
                print(f"[{agent_id}] tabular empty after parse — running direct SQL fallback")
                _, fallback_tabular = _direct_sql_fallback(question, tables)
                if fallback_tabular.get("data"):
                    tabular = fallback_tabular

            return {
                "status": "success",
                "agent_id": agent_id,
                "agent_name": AGENT_REGISTRY[agent_id]["name"],
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
            err_str = str(e)
            last_error = err_str
            print(f"[{agent_id}] Provider {provider} failed: {err_str[:300]}")
            continue

    elapsed = round(time.time() - start, 2)
    friendly = _friendly_error(last_error)
    return {
        "status": "error",
        "agent_id": agent_id,
        "sql": "",
        "result": {"message": friendly},
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _is_raw_tool_output(text: str) -> bool:
    markers = [
        '"sql_db_query"', '<|python_tag|>', '"tool_input"',
        '{"type": "function"', 'import json', 'import pandas', '```python',
    ]
    return any(m in text for m in markers)


def _is_unhelpful_answer(text: str) -> bool:
    t = text.strip().lower()
    refusals = [
        "i don't know", "i do not know", "i cannot", "i can't",
        "unable to", "no information", "no data available",
        "i don't have access", "i'm not able",
    ]
    return len(t) < 300 and any(r in t for r in refusals)


def _direct_sql_fallback(question: str, tables: list[str]) -> tuple[str, dict]:
    """Run a simple SELECT * LIMIT 20 against the first table as a last resort."""
    try:
        from sqlalchemy import text
        from backend.db import engine
        if not tables:
            return "No tables are available to query.", {"data": [], "columns": []}
        t = tables[0]
        with engine.connect() as conn:
            res = conn.execute(text(f'SELECT * FROM "{t}" LIMIT 20'))
            rows = [dict(r._mapping) for r in res]
        if not rows:
            return f"The table `{t}` is empty — no data to extract.", {"data": [], "columns": []}
        cols = list(rows[0].keys())
        md  = "| " + " | ".join(cols) + " |\n"
        md += "|" + "|".join(["---"] * len(cols)) + "|\n"
        for row in rows:
            md += "| " + " | ".join(str(row.get(c, "")) for c in cols) + " |\n"
        answer = f"*(Direct query fallback — showing raw results from `{t}`:)*\n\n{md}"
        tabular = _parse_markdown_table(md)
        if not tabular.get("data"):
            tabular = {"data": rows, "columns": cols}
        return answer, tabular
    except Exception as e:
        return f"Data extraction failed: {e}", {"data": [], "columns": []}


def _salvage_from_error(err_str: str, tables: list[str]) -> str:
    if "quota" in err_str.lower() or "429" in err_str or "rate" in err_str.lower():
        return "The AI provider is rate-limited. Please wait a moment and try again."
    if "api key" in err_str.lower() or "authentication" in err_str.lower():
        return "Invalid or missing API key. Please update your API key in settings."
    return f"The extraction agent encountered an error: {err_str[:200]}"


def _salvage_from_raw_output(answer: str, tables: list[str], result: dict) -> tuple[str, dict | None]:
    sql_match = re.search(
        r'(?i)["\']query["\']\s*:\s*["\']([^"\']*(?:SELECT|WITH)[^"\']+)["\']', answer
    )
    if not sql_match:
        sql_match = re.search(
            r'(?i)(?:SELECT|WITH)\s+.*?(?:FROM|LIMIT).*?(?:["\']|\n|;|$)', answer, re.DOTALL
        )

    if sql_match:
        extracted_sql = (sql_match.group(1) if sql_match.lastindex else sql_match.group(0))
        extracted_sql = extracted_sql.replace('\\"', '"').strip('"\n;')
        try:
            from sqlalchemy import text
            from backend.db import engine
            with engine.connect() as conn:
                res  = conn.execute(text(extracted_sql))
                rows = [dict(r._mapping) for r in res]
            if rows:
                cols = list(rows[0].keys())
                md   = "| " + " | ".join(cols) + " |\n"
                md  += "|" + "|".join(["---"] * len(cols)) + "|\n"
                for r in rows[:15]:
                    md += "| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n"
                tabular = _parse_markdown_table(md)
                if not tabular.get("data"):
                    tabular = {"data": rows, "columns": cols}
                return md, tabular
            else:
                return "The SQL query executed but returned 0 rows.", None
        except Exception as e:
            return f"Could not execute extracted SQL: {e}", None

    if "sql_db_schema" in answer or "sql_db_list_tables" in answer:
        return (
            "The AI model got stuck inspecting the schema instead of answering. "
            "Try rephrasing as a more specific SQL question (e.g. 'Show me all rows from the table').",
            None,
        )
    return (
        "The AI returned raw tool-call output instead of a natural language answer. "
        "Please try a simpler question.",
        None,
    )


def _extract_sql_from_steps(steps: list) -> str:
    for step in reversed(steps):
        if isinstance(step, (list, tuple)) and len(step) >= 1:
            action = step[0]
            if hasattr(action, "tool_input"):
                ti    = action.tool_input
                query = ti.get("query", "") if isinstance(ti, dict) else str(ti)
                if query.strip().upper().startswith("SELECT"):
                    return query.strip().rstrip(";")
    return ""


def _friendly_error(err: str) -> str:
    e = err.lower()
    if "429" in err or "quota" in e or "resource_exhausted" in e:
        return (
            "Rate limit reached on the AI provider. "
            "Wait 30–60 seconds then try again, or switch to a different provider."
        )
    if "401" in err or "api key" in e or "authentication" in e:
        return "Invalid API key. Please update your key in settings."
    if "timeout" in e:
        return "The request timed out. The data may be too large — try a more specific question."
    if "connection" in e or "network" in e:
        return "Network error. Check your internet connection and try again."
    return f"Extraction failed: {err[:250]}"


# ---------------------------------------------------------------------------
# WORKFLOW / PARALLEL RUNNERS
# ---------------------------------------------------------------------------

def run_workflow(question: str) -> dict:
    start  = time.time()
    result = run_agent_query("data_extractor", question)

    activated = ["data_extractor"]
    q = question.lower()

    if any(k in q for k in ["csv", "table", "column", "row", "sql", "data", "price", "count", "sum", "average", "mean", "total", "min", "max", "list", "show", "top", "bottom", "group", "sort", "filter", "where"]):
        activated += ["structured_data", "csv_agent"]
    if any(k in q for k in ["excel", "xls", "spreadsheet", "sheet"]):
        activated += ["structured_data", "xls_agent"]
    if any(k in q for k in ["pdf", "document", "report", "page"]):
        activated += ["unstructured_data", "pdf_agent"]
    if any(k in q for k in ["text", "log", "file", "content", "read"]):
        activated += ["unstructured_data", "text_agent"]

    # Smart fallback: use actual loaded file types instead of blindly defaulting to csv
    if len(activated) == 1:
        detected = _detect_active_agents()
        if detected:
            for a in detected:
                activated.append(a)
                info = AGENT_REGISTRY.get(a, {})
                parent = info.get("parent")
                if parent:
                    activated.append(parent)
        else:
            activated += ["structured_data", "csv_agent"]

    result["activated_agents"]  = list(set(activated))
    result["workflow_elapsed"] = round(time.time() - start, 2)
    return result


def _detect_active_agents() -> list[str]:
    from backend.db import get_all_tables, DATA_DIR
    tables = get_all_tables()
    if not tables:
        return []

    active = []
    for t in tables:
        csv_path = os.path.join(DATA_DIR, f"{t}.csv")
        xls_path = os.path.join(DATA_DIR, f"{t}.xlsx")
        pdf_path = os.path.join(DATA_DIR, f"{t}.pdf")
        txt_path = os.path.join(DATA_DIR, f"{t}.txt")
        md_path  = os.path.join(DATA_DIR, f"{t}.md")
        log_path = os.path.join(DATA_DIR, f"{t}.log")

        if os.path.exists(csv_path)  and "csv_agent"  not in active: active.append("csv_agent")
        elif os.path.exists(xls_path) and "xls_agent" not in active: active.append("xls_agent")
        elif os.path.exists(pdf_path) and "pdf_agent" not in active: active.append("pdf_agent")
        elif (os.path.exists(txt_path) or os.path.exists(md_path) or os.path.exists(log_path)) \
                and "text_agent" not in active: active.append("text_agent")
        else:
            if "csv_agent" not in active: active.append("csv_agent")

    return active


def categorize_file_type(filename: str) -> str:
    fname = filename.lower()
    if fname.endswith(".csv"): return "csv"
    if fname.endswith((".xlsx", ".xls")): return "excel"
    if fname.endswith(".pdf"): return "pdf"
    if fname.endswith((".txt", ".log", ".md")): return "text"
    return "unknown"


def get_agents_for_file(filename: str) -> list[str]:
    routing = {
        "csv":   ["csv_agent",  "structured_data",   "data_extractor"],
        "excel": ["xls_agent",  "structured_data",   "data_extractor"],
        "pdf":   ["pdf_agent",  "unstructured_data", "data_extractor"],
        "text":  ["text_agent", "unstructured_data", "data_extractor"],
    }
    return routing.get(categorize_file_type(filename), ["data_extractor"])


def get_categorization_info(filename: str) -> dict:
    file_type = categorize_file_type(filename)
    agents    = get_agents_for_file(filename)

    details = {
        "csv":   {"label": "Structured Data — CSV",   "icon": "csv",  "color": "#34d399", "description": "Tabular data. Uses SQL queries."},
        "excel": {"label": "Structured Data — Excel", "icon": "exc",  "color": "#2dd4bf", "description": "Spreadsheet. Supports multi-sheet analysis."},
        "pdf":   {"label": "Unstructured Data — PDF", "icon": "pdf",  "color": "#f87171", "description": "Document. Extracts text and tables."},
        "text":  {"label": "Unstructured Data — Text","icon": "text", "color": "#a78bfa", "description": "Text/log file. Pattern analysis."},
    }
    detail = details.get(file_type, {"label": "Unknown", "icon": "file", "color": "#555", "description": "Unrecognized type."})

    return {
        "file_type": file_type,
        "filename": filename,
        "recommended_agents": agents,
        "primary_agent": agents[0] if agents else "data_extractor",
        "category": detail,
    }


def run_parallel_analysis(question: str, focus_agents: list[str] = None, focus_tables: list[str] = None) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    start = time.time()
    load_dotenv(_env_path, override=True)

    available = get_available_providers()
    if not available:
        return {"status": "no_api_key", "results": [], "activated_agents": [], "workflow_elapsed": 0.0}

    tables = get_all_tables()
    if not tables:
        return {"status": "no_data", "results": [], "activated_agents": [], "workflow_elapsed": 0.0}

    specialist_agents = (
        [a for a in focus_agents if a in AGENT_REGISTRY]
        if focus_agents
        else (_detect_active_agents() or ["csv_agent"])
    )

    print(f"[parallel] Agents: {specialist_agents}")

    agent_results = []
    with ThreadPoolExecutor(max_workers=min(len(specialist_agents), 4)) as executor:
        futures = []
        for i, agent_id in enumerate(specialist_agents):
            if i > 0:
                time.sleep(0.5)
            futures.append(executor.submit(run_agent_query, agent_id, question, focus_tables))

        for i, future in enumerate(futures):
            agent_id = specialist_agents[i]
            try:
                res = future.result(timeout=120)
                res["agent_id"]   = agent_id
                res["agent_name"] = AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id)
                agent_results.append(res)
                print(f"[parallel] {agent_id}: {res.get('status')}")
            except Exception as e:
                agent_results.append({
                    "status": "error",
                    "agent_id": agent_id,
                    "agent_name": AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id),
                    "result": {"message": _friendly_error(str(e))},
                    "elapsed": 0,
                })

    successful = [r for r in agent_results if r.get("status") == "success"]
    elapsed    = round(time.time() - start, 2)

    if not successful:
        primary = agent_results[0] if agent_results else None
        return {
            "status": primary.get("status", "error") if primary else "error",
            "sql":    primary.get("sql", "") if primary else "",
            "result": primary.get("result", {"message": "No agents ran"}) if primary else {"message": "No agents ran"},
            "results": agent_results,
            "activated_agents": list(set(specialist_agents)),
            "parallel_count": len(specialist_agents),
            "workflow_elapsed": elapsed,
            "elapsed": elapsed,
            "provider": primary.get("provider") if primary else None,
        }

    merged_answers, merged_sql_parts = [], []
    merged_data, merged_columns = [], []
    merged_chart_type = merged_numeric = merged_label = first_provider = None

    for r in successful:
        res         = r.get("result", {})
        agent_name  = r.get("agent_name", r.get("agent_id", "Agent"))
        answer_text = res.get("answer", "")
        if answer_text:
            merged_answers.append(f"**[{agent_name}]**\n{answer_text}")
        sql = r.get("sql", "")
        if sql:
            merged_sql_parts.append(f"-- {agent_name}\n{sql}")
        data, columns = res.get("data", []), res.get("columns", [])
        if data and columns:
            merged_data.extend(data)
            for c in columns:
                if c not in merged_columns:
                    merged_columns.append(c)
        if not merged_chart_type and res.get("chart_type"):
            merged_chart_type = res["chart_type"]
            merged_numeric    = res.get("numeric_columns", [])
            merged_label      = res.get("label_column")
        if not first_provider:
            first_provider = r.get("provider")

    combined_answer = "\n\n---\n\n".join(merged_answers) if merged_answers else "Analysis complete."

    if len(successful) > 1:
        try:
            p, m = available[0]
            llm  = _build_llm(p, m)
            from langchain_core.messages import HumanMessage
            context = "\n\n".join([
                f"Agent {r['agent_name']}:\n{r['result'].get('answer', '')}"
                for r in successful
            ])
            synthesis = f"""You are a Master Analyst. Synthesize the following specialist findings into one cohesive answer.

User question: {question}

Specialist findings:
{context}

Provide a clear, concise combined analysis."""
            res = llm.invoke([HumanMessage(content=synthesis)])
            combined_answer = (
                f"{res.content}\n\n---\n\n**Detailed Agent Reports:**\n\n"
                + "\n\n---\n\n".join(merged_answers)
            )
        except Exception as e:
            print(f"[parallel] Synthesis failed: {e}")

    return {
        "status": "success",
        "sql": "\n\n".join(merged_sql_parts),
        "result": {
            "type": "answer",
            "answer": combined_answer,
            "data": merged_data,
            "columns": merged_columns,
            "row_count": len(merged_data),
            "chart_type": merged_chart_type,
            "numeric_columns": merged_numeric or [],
            "label_column": merged_label,
        },
        "results": agent_results,
        "activated_agents": list(set(specialist_agents)),
        "parallel_count": len(specialist_agents),
        "workflow_elapsed": elapsed,
        "elapsed": elapsed,
        "provider": first_provider,
    }


def run_parallel_workflow(question: str) -> dict:
    return run_parallel_analysis(question)
