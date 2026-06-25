import re


def clean_sql(raw: str) -> str:
    """Extract and clean a SQL query from LLM output.
    Handles markdown code fences, explanations, and formatting artifacts.
    """
    # Remove markdown code fences: ```sql ... ``` or ``` ... ```
    fenced = re.search(r"```(?:sql)?\s*\n?(.*?)```", raw, re.IGNORECASE | re.DOTALL)
    if fenced:
        raw = fenced.group(1)

    # Extract from SELECT onward (ignore any preamble/explanation)
    match = re.search(r"(SELECT\s.*)", raw, re.IGNORECASE | re.DOTALL)
    if match:
        sql = match.group(1)
    else:
        sql = raw.strip()

    # Remove trailing semicolons and whitespace
    sql = sql.strip().rstrip(";").strip()

    # Remove any lines after a blank line (usually explanations)
    lines = sql.split("\n")
    cleaned_lines = []
    for line in lines:
        if line.strip() == "" and cleaned_lines:
            break
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


BLOCKED_KEYWORDS = [
    "drop", "delete", "update", "insert", "alter", "create",
    "truncate", "replace", "exec", "execute", "grant", "revoke",
    "attach", "detach", "pragma"
]


def is_safe_sql(sql: str) -> bool:
    """Check if a SQL query is safe to execute (SELECT only, no mutations)."""
    normalized = sql.lower().strip()

    # Must start with SELECT
    if not normalized.startswith("select"):
        return False

    # Check for blocked keywords (as whole words)
    for keyword in BLOCKED_KEYWORDS:
        if re.search(rf"\b{keyword}\b", normalized):
            return False

    return True


def validate_columns(sql: str, valid_columns: list[str]) -> list[str]:
    """Check if the SQL references any columns not in the schema.
    Returns a list of invalid column names found.
    """
    # Extract potential column references (words that aren't SQL keywords)
    sql_keywords = {
        "select", "from", "where", "and", "or", "not", "in", "is", "null",
        "like", "between", "as", "on", "join", "left", "right", "inner",
        "outer", "group", "by", "order", "asc", "desc", "limit", "offset",
        "having", "count", "sum", "avg", "min", "max", "distinct", "case",
        "when", "then", "else", "end", "cast", "coalesce", "ifnull",
        "car_sales", "true", "false", "union", "all", "exists", "upper",
        "lower", "trim", "length", "substr", "replace", "round", "abs",
        "date", "time", "datetime", "strftime", "typeof", "total",
    }

    # This is a best-effort check — not a full SQL parser
    words = re.findall(r"\b([a-z_][a-z0-9_]*)\b", sql.lower())
    valid_set = {c.lower() for c in valid_columns}

    invalid = []
    for word in words:
        if word not in sql_keywords and word not in valid_set and not word.startswith("row"):
            # Could be an alias or function — skip numbers and common patterns
            if not word.isdigit():
                invalid.append(word)

    return list(set(invalid))


def format_results_for_display(results: list[dict]) -> dict:
    """Format query results into a structured response for the frontend."""
    if not results:
        return {
            "type": "empty",
            "message": "Query returned no results.",
            "data": [],
            "columns": []
        }

    columns = list(results[0].keys())

    # Detect if results are chart-friendly (has a label + numeric column)
    numeric_cols = [
        c for c in columns
        if all(isinstance(r.get(c), (int, float)) for r in results)
    ]
    label_cols = [c for c in columns if c not in numeric_cols]

    chart_type = None
    if len(results) <= 20 and numeric_cols and label_cols:
        chart_type = "bar"
        if len(results) > 10:
            chart_type = "line"

    return {
        "type": "table",
        "columns": columns,
        "data": results,
        "row_count": len(results),
        "chart_type": chart_type,
        "numeric_columns": numeric_cols,
        "label_column": label_cols[0] if label_cols else None
    }