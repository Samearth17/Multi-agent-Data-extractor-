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
        "color": "#8b5cf6",
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
        "color": "#06b6d4",
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
        "color": "#f59e0b",
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
        "color": "#10b981",
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
        "color": "#22d3ee",
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
        "color": "#ef4444",
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
        "color": "#a855f7",
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
            connections.append({
                "from": agent["id"],
                "to": child_id,
            })
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
        md_path = os.path.join(DATA_DIR, f"{t}.md")
        log_path = os.path.join(DATA_DIR, f"{t}.log")

        if agent_id in ("csv_agent", "structured_data") and os.path.exists(csv_path):
            agent_tables.append(t)
        elif agent_id in ("xls_agent", "structured_data") and os.path.exists(xls_path):
            agent_tables.append(t)
        elif agent_id in ("pdf_agent", "unstructured_data") and os.path.exists(pdf_path):
            agent_tables.append(t)
        elif agent_id in ("text_agent", "unstructured_data") and (os.path.exists(txt_path) or os.path.exists(md_path) or os.path.exists(log_path)):
            agent_tables.append(t)
            
    if agent_id in ("csv_agent", "structured_data"):
        for t in tables:
            if not any(os.path.exists(os.path.join(DATA_DIR, f"{t}{ext}")) for ext in ['.csv', '.xlsx', '.pdf', '.txt', '.md', '.log']):
                if t not in agent_tables:
                    agent_tables.append(t)

    return agent_tables


def _build_agent_prompt(agent_id: str, question: str, focus_tables: list[str] = None) -> str:
    agent = AGENT_REGISTRY[agent_id]
    tables = focus_tables if focus_tables is not None else get_all_tables()
    schema_text = get_schema_prompt(tables_list=tables)
    table_list = ", ".join(f"`{t}`" for t in tables) if tables else "No tables uploaded"

    agents_path = os.path.join(BASE_DIR, "AGENTS.md")
    agents_md = ""
    if os.path.exists(agents_path):
        with open(agents_path) as f:
            agents_md = f.read()

    base = f"""You are the **{agent['name']}** — {agent['description']}

## Your Role
{_get_role_prompt(agent_id)}

## Extra Context
{agents_md[:1500]}

## Available Tables
{table_list}

## Database Schema
{schema_text}

## CRITICAL OUTPUT FORMAT RULES
1. When you retrieve data from the database, you MUST ALWAYS format the results as a **markdown table**.
2. Use proper markdown table syntax with headers, separator row (---|---), and data rows.
3. Example format:
   | Column1 | Column2 | Column3 |
   |---------|---------|---------|
   | value1  | value2  | value3  |
4. After the table, provide your analysis and insights.
5. NEVER output raw Python code, `import` statements, or JSON blocks. Always explain findings in natural language.
6. To generate a chart, simply provide the data in a Markdown Table. The system will automatically convert it into a graph.
7. ALWAYS query ALL available tables that are relevant to the question.
"""
    return base


def _get_role_prompt(agent_id: str) -> str:
    prompts = {
        "data_extractor": (
            "You are the top-level Data Extractor. You can directly query the SQL database. "
            "Analyze the user's question and provide comprehensive data analysis. "
            "If the question involves structured data (CSV/Excel), use SQL queries. "
            "Provide detailed insights, statistics, and format data as markdown tables."
        ),
        "structured_data": (
            "You specialize in structured/tabular data analysis. "
            "You can run SQL queries against uploaded CSV and Excel data. "
            "Focus on data structure, column relationships, and statistical summaries."
        ),
        "unstructured_data": (
            "You specialize in unstructured data analysis. "
            "While your primary role is document analysis, you can also query the SQL database "
            "to cross-reference structured data. Explain your findings in plain language."
        ),
        "csv_agent": (
            "You are a CSV data specialist. You MUST ONLY query and analyze data from CSV-sourced tables. "
            "You excel at parsing, cleaning, and querying CSV data. Use SQL to extract insights. "
            "Ignore any tables that are not from CSV sources unless explicitly asked to join them."
        ),
        "xls_agent": (
            "You are an Excel specialist. You MUST ONLY query and analyze data from Excel-sourced tables. "
            "Focus on multi-sheet analysis patterns, pivot-style summaries, and formatted output. "
            "Ignore any tables that are not from Excel sources unless explicitly asked to join them."
        ),
        "pdf_agent": (
            "You are a PDF document specialist. You MUST ONLY focus on data sourced from PDF documents. "
            "Your strength is in explaining document-related data, extracting key information, "
            "and summarizing findings from document-sourced data. "
            "Ignore any tables that are not from PDF sources."
        ),
        "text_agent": (
            "You are a Text/Log file specialist. You MUST ONLY focus on data sourced from text, log, or markdown files. "
            "You are an expert in pattern recognition, text analysis, keyword extraction, and summarizing unstructured logs. "
            "Ignore any tables that are not from text-based sources."
        ),
    }
    return prompts.get(agent_id, "Analyze the data and provide insights.")


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
            "result": {"message": "No API key configured."},
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
                "answer": f"No relevant files for the **{AGENT_REGISTRY[agent_id].get('name', agent_id)}** to analyze.",
                "data": [],
                "columns": [],
                "row_count": 0,
            },
            "elapsed": round(time.time() - start, 2),
        }

    last_error = "Unknown error"

    for provider, model_name in available:
        try:
            print(f"[{agent_id}] Attempting with: {provider} ({model_name}) | Tables: {tables}")
            llm = _build_llm(provider, model_name)
            system_prompt = _build_agent_prompt(agent_id, question, focus_tables=tables)
            from langchain_community.utilities import SQLDatabase
            from langchain_community.agent_toolkits import create_sql_agent
            from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit

            from langchain_community.utilities import SQLDatabase
            db = SQLDatabase(engine,
                sample_rows_in_table_info=2,
                include_tables=tables,
            )
            toolkit = SQLDatabaseToolkit(db=db, llm=llm)

            agent = create_sql_agent(
                llm=llm,
                toolkit=toolkit,
                verbose=False,
                agent_type="tool-calling",
                system_message=system_prompt,
                max_iterations=12,
                handle_parsing_errors=True,
            )

            try:
                result = agent.invoke({"input": question})
                answer = result.get("output", str(result))
            except Exception as e:
                if "Extra data" in str(e):
                    print(f"[safety-net] JSON error in agent.invoke, falling back to raw output")
                    # In some cases the error itself contains the partial output
                    answer = f"The agent encountered a formatting error but might have been trying to say: {str(e)}"
                    result = {"output": answer, "intermediate_steps": []}
                else:
                    raise e
            tabular = None
            
            # Catch raw tool call outputs or code leakage
            if isinstance(answer, str) and (
                '"sql_db_query"' in answer or 
                '<|python_tag|>' in answer or 
                '"tool_input"' in answer or
                '{"type": "function"' in answer or
                'import json' in answer or
                'import pandas' in answer or
                '```python' in answer
            ):
                import re
                print(f"[safety-net] Triggered for {agent_id}. Scanned output: {answer[:300]}...")
                
                # 1. Try to extract the SQL query if it generated one
                # Look for "query": "SELECT..." or just 'SELECT...' or "SELECT..."
                sql_match = re.search(r'(?i)["\']query["\']\s*:\s*["\']([^"\']*(?:SELECT|WITH)[^"\']+)["\']', answer)
                if not sql_match:
                    sql_match = re.search(r'(?i)["\']([^"\']*(?:SELECT|WITH)\s+[^"\']+)["\']', answer)
                if not sql_match:
                    sql_match = re.search(r'(?i)(?:SELECT|WITH)\s+.*?(?:FROM|LIMIT).*?(?:["\']|\n|;|$)', answer, re.DOTALL)
                
                if sql_match:
                    extracted_sql = sql_match.group(1) if sql_match.lastindex else sql_match.group(0)
                    extracted_sql = extracted_sql.replace('\\"', '"').strip('"\n;')
                    try:
                        from sqlalchemy import text
                        with engine.connect() as conn:
                            res = conn.execute(text(extracted_sql))
                            rows = [dict(row._mapping) for row in res]
                            
                            if rows:
                                cols = list(rows[0].keys())
                                new_answer = f"*(I had to extract this data directly from my code because my API formatting failed!)*\n\n"
                                new_answer += "| " + " | ".join(cols) + " |\n"
                                new_answer += "|" + "|".join(["---"] * len(cols)) + "|\n"
                                for r in rows[:15]:
                                    new_answer += "| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n"
                                
                                answer = new_answer
                                # Pre-populate tabular with the raw rows so we don't lose numeric precision
                                tabular = _parse_markdown_table(answer)
                                if rows and not tabular.get("data"):
                                    tabular["data"] = rows
                                    tabular["columns"] = cols

                                # We also need to inject it into intermediate_steps so the frontend gets the SQL string
                                if not result.get("intermediate_steps"):
                                    class MockAction: pass
                                    mock = MockAction()
                                    mock.tool_input = {"query": extracted_sql}
                                    result["intermediate_steps"] = [(mock, None)]
                            else:
                                answer = "I successfully extracted and ran the SQL query, but it returned 0 rows."
                    except Exception as e:
                        answer = f"*(I tried to extract a SQL query from my output, but it failed to execute: {e})*\n\nOriginal Output:\n{answer}"
                else:
                    # 2. If it's just trying to look up the schema, tell the user the LLM got stuck
                    if "sql_db_schema" in answer or "sql_db_list_tables" in answer:
                        answer = "*(Oops! I got stuck trying to look up the database schema instead of generating the final answer. This sometimes happens with smaller AI models when they get confused by the tool formatting. Please try asking a more direct SQL question!)*"
                    else:
                        answer = "*(Oops! I generated raw tool-calling code instead of natural language, and couldn't find a valid SQL query to salvage.)*\n\n" + answer

            # Extract SQL
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

            elapsed = round(time.time() - start, 2)
            if not tabular:
                tabular = _parse_markdown_table(answer)

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
            if "Extra data" in err_str:
                last_error = f"JSON Parsing Error (LLM returned malformed data): {err_str}"
            else:
                last_error = err_str
            print(f"[{agent_id}] Provider {provider} failed: {last_error[:200]}")
            continue

    elapsed = round(time.time() - start, 2)
    return {
        "status": "error",
        "agent_id": agent_id,
        "sql": "",
        "result": {"message": f"All providers failed. Last error: {last_error}"},
        "elapsed": elapsed,
    }


def run_workflow(question: str) -> dict:
    start = time.time()

    result = run_agent_query("data_extractor", question)

    activated = ["data_extractor"]
    q_lower = question.lower()

    if any(kw in q_lower for kw in ["csv", "table", "column", "row", "sql", "data", "price", "count", "sum", "average"]):
        activated.append("structured_data")
        activated.append("csv_agent")
    if any(kw in q_lower for kw in ["excel", "xls", "spreadsheet", "sheet"]):
        activated.append("structured_data")
        activated.append("xls_agent")
    if any(kw in q_lower for kw in ["pdf", "document", "report", "page"]):
        activated.append("unstructured_data")
        activated.append("pdf_agent")
    if any(kw in q_lower for kw in ["text", "log", "file", "content", "read"]):
        activated.append("unstructured_data")
        activated.append("text_agent")

    if len(activated) == 1:
        activated.extend(["structured_data", "csv_agent"])

    result["activated_agents"] = list(set(activated))
    result["workflow_elapsed"] = round(time.time() - start, 2)
    return result


def _detect_active_agents() -> list[str]:
    from backend.db import get_all_tables, DATA_DIR
    tables = get_all_tables()
    if not tables:
        return []

    active = []
    for t in tables:
        # Check for source files to detect type
        csv_path = os.path.join(DATA_DIR, f"{t}.csv")
        xls_path = os.path.join(DATA_DIR, f"{t}.xlsx")
        pdf_path = os.path.join(DATA_DIR, f"{t}.pdf")
        txt_path = os.path.join(DATA_DIR, f"{t}.txt")
        md_path = os.path.join(DATA_DIR, f"{t}.md")
        log_path = os.path.join(DATA_DIR, f"{t}.log")

        if os.path.exists(csv_path):
            if "csv_agent" not in active:
                active.append("csv_agent")
        elif os.path.exists(xls_path):
            if "xls_agent" not in active:
                active.append("xls_agent")
        elif os.path.exists(pdf_path):
            if "pdf_agent" not in active:
                active.append("pdf_agent")
        elif os.path.exists(txt_path) or os.path.exists(md_path) or os.path.exists(log_path):
            if "text_agent" not in active:
                active.append("text_agent")
        else:
            # Default to csv_agent for unknown sources
            if "csv_agent" not in active:
                active.append("csv_agent")

    return active




def categorize_file_type(filename: str) -> str:
    fname_lower = filename.lower()
    
    if fname_lower.endswith('.csv'):
        return 'csv'
    elif fname_lower.endswith(('.xlsx', '.xls')):
        return 'excel'
    elif fname_lower.endswith('.pdf'):
        return 'pdf'
    elif fname_lower.endswith(('.txt', '.log', '.md')):
        return 'text'
    else:
        return 'unknown'


def get_agents_for_file(filename: str) -> list[str]:
    file_type = categorize_file_type(filename)
    
    routing_map = {
        'csv': ['csv_agent', 'structured_data', 'data_extractor'],
        'excel': ['xls_agent', 'structured_data', 'data_extractor'],
        'pdf': ['pdf_agent', 'unstructured_data', 'data_extractor'],
        'text': ['text_agent', 'unstructured_data', 'data_extractor'],
    }
    
    return routing_map.get(file_type, ['data_extractor'])


def get_categorization_info(filename: str) -> dict:
    file_type = categorize_file_type(filename)
    agents = get_agents_for_file(filename)
    
    category_details = {
        'csv': {
            'label': 'Structured Data - CSV',
            'icon': 'csv',
            'color': '#10b981',
            'description': 'Tabular data file. Will use SQL queries for analysis.',
        },
        'excel': {
            'label': 'Structured Data - Excel',
            'icon': 'exc',
            'color': '#22d3ee',
            'description': 'Spreadsheet file. Supports multi-sheet analysis.',
        },
        'pdf': {
            'label': 'Unstructured Data - PDF',
            'icon': 'pdf',
            'color': '#ef4444',
            'description': 'Document file. Extracts text and structured data.',
        },
        'text': {
            'label': 'Unstructured Data - Text',
            'icon': 'text',
            'color': '#a855f7',
            'description': 'Text/log file. Performs text analysis and extraction.',
        },
    }
    
    detail = category_details.get(file_type, {
        'label': 'Unknown Type',
        'icon': 'file',
        'color': '#666666',
        'description': 'File type not recognized.',
    })
    
    return {
        'file_type': file_type,
        'filename': filename,
        'recommended_agents': agents,
        'primary_agent': agents[0] if agents else 'data_extractor',
        'category': detail,
    }


def run_parallel_analysis(question: str, focus_agents: list[str] = None, focus_tables: list[str] = None) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    start = time.time()
    load_dotenv(_env_path, override=True)

    available = get_available_providers()
    if not available:
        return {
            "status": "no_api_key",
            "results": [],
            "activated_agents": [],
            "workflow_elapsed": 0.0,
        }

    tables = get_all_tables()
    if not tables:
        return {
            "status": "no_data",
            "results": [],
            "activated_agents": [],
            "workflow_elapsed": 0.0,
        }

    # Determine which agents to run
    if focus_agents:
        # Filter to valid agents only
        specialist_agents = [a for a in focus_agents if a in AGENT_REGISTRY]
    else:
        # Auto-detect all active agents
        specialist_agents = _detect_active_agents()
        if not specialist_agents:
            specialist_agents = ["csv_agent"]

    # Build hierarchy - ONLY include the agents that are actually running
    activated = [a for a in specialist_agents]

    print(f"[parallel] Running focused analysis with agents: {specialist_agents}")

    # Run agents in parallel
    agent_results = []
    with ThreadPoolExecutor(max_workers=min(len(specialist_agents), 4)) as executor:
        futures = []
        for i, agent_id in enumerate(specialist_agents):
            # CRITICAL: Stagger submissions by 500ms to avoid 429 RESOURCE_EXHAUSTED errors on free tier
            if i > 0:
                time.sleep(0.5)
            futures.append(executor.submit(run_agent_query, agent_id, question, focus_tables))

        for i, future in enumerate(futures):
            agent_id = specialist_agents[i]
            try:
                result = future.result(timeout=120)
                result["agent_id"] = agent_id
                result["agent_name"] = AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id)
                agent_results.append(result)
                print(f"[parallel] {agent_id} completed: {result.get('status')}")
            except Exception as e:
                agent_results.append({
                    "status": "error",
                    "agent_id": agent_id,
                    "agent_name": AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id),
                    "result": {"message": f"Agent failed: {str(e)}"},
                    "elapsed": 0,
                })
                print(f"[parallel] {agent_id} failed: {e}")

    # Merge results
    successful = [r for r in agent_results if r.get("status") == "success"]
    elapsed = round(time.time() - start, 2)

    if not successful:
        primary = agent_results[0] if agent_results else None
        return {
            "status": primary.get("status", "error") if primary else "error",
            "sql": primary.get("sql", "") if primary else "",
            "result": primary.get("result", {}) if primary else {"message": "No agents ran"},
            "results": agent_results,
            "activated_agents": list(set(activated)),
            "parallel_count": len(specialist_agents),
            "workflow_elapsed": elapsed,
            "elapsed": elapsed,
            "provider": primary.get("provider") if primary else None,
        }

    # Merge successful results
    merged_answers = []
    merged_sql_parts = []
    merged_data = []
    merged_columns = []
    merged_numeric = []
    merged_label = None
    merged_chart_type = None
    first_provider = None

    for r in successful:
        res = r.get("result", {})
        agent_name = r.get("agent_name", r.get("agent_id", "Agent"))

        answer_text = res.get("answer", "")
        if answer_text:
            merged_answers.append(f"**[{agent_name}]**\n{answer_text}")

        sql = r.get("sql", "")
        if sql:
            merged_sql_parts.append(f"-- {agent_name}\n{sql}")

        data = res.get("data", [])
        columns = res.get("columns", [])
        if data and columns:
            merged_data.extend(data)
            for c in columns:
                if c not in merged_columns:
                    merged_columns.append(c)

        if not merged_chart_type and res.get("chart_type"):
            merged_chart_type = res["chart_type"]
            merged_numeric = res.get("numeric_columns", [])
            merged_label = res.get("label_column")

        if not first_provider:
            first_provider = r.get("provider")

    combined_answer = "\n\n---\n\n".join(merged_answers) if merged_answers else "Analysis complete."
    
    if len(successful) > 1:
        # Synthesis Step: Run a final LLM call to combine findings
        try:
            p, m = available[0]
            llm = _build_llm(p, m)
            from langchain_core.messages import HumanMessage
            
            context = "\n\n".join([f"Agent {r['agent_name']} findings:\n{r['result'].get('answer', '')}" for r in successful])
            
            synthesis_prompt = f"""You are a Master Analyst. You have findings from multiple specialist agents. 
Your goal is to provide a unified, cohesive answer to the user's original question by synthesizing these findings.
Identify commonalities, differences, and key insights across all sources.

User's Question: {question}

Specialist Findings:
{context}

Provide a final, combined analysis that directly answers the user's question clearly and concisely."""
            
            res = llm.invoke([HumanMessage(content=synthesis_prompt)])
            final_synthesis = res.content
            combined_answer = f"{final_synthesis}\n\n---\n\n**Detailed Agent Reports:**\n\n" + "\n\n---\n\n".join(merged_answers)
        except Exception as e:
            print(f"[parallel] Synthesis failed: {e}")
            # Fallback to simple concatenation if synthesis fails

    combined_sql = "\n\n".join(merged_sql_parts)

    return {
        "status": "success",
        "sql": combined_sql,
        "result": {
            "type": "answer",
            "answer": combined_answer,
            "data": merged_data,
            "columns": merged_columns,
            "row_count": len(merged_data),
            "chart_type": merged_chart_type,
            "numeric_columns": merged_numeric,
            "label_column": merged_label,
        },
        "results": agent_results,
        "activated_agents": list(set(activated)),
        "parallel_count": len(specialist_agents),
        "workflow_elapsed": elapsed,
        "elapsed": elapsed,
        "provider": first_provider,
    }

def run_parallel_workflow(question: str) -> dict:
    """Wrapper for run_parallel_analysis to match main.py expectations."""
    return run_parallel_analysis(question)
