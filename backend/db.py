import os
import re
import shutil
import pandas as pd
from sqlalchemy import create_engine, inspect, text, event


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "universal.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def csv_filename_to_table(filename: str) -> str:
    name = os.path.splitext(os.path.basename(filename))[0]
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    if not name:
        name = "uploaded_table"
    elif name[0].isdigit():
        name = "t_" + name
        
    # CLEANUP: Remove any old files with the same name but different extensions
    # to ensure _detect_active_tasks picks the correct agent for the new file.
    for ext in ['.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md']:
        old_file = os.path.join(DATA_DIR, name + ext)
        if os.path.exists(old_file):
            try: os.remove(old_file)
            except: pass
            
    return name


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Ensure columns are string types
    df.columns = [str(c) for c in df.columns]
    df.columns = (
        pd.Index(df.columns)
        .str.lower()
        .str.strip()
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(r"[^a-z0-9_]", "", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )
    seen = {}
    new_cols = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    df.columns = new_cols
    return df



def upload_csv(file_bytes: bytes, filename: str) -> dict:
    table_name = csv_filename_to_table(filename)

    import io
    df = pd.read_csv(io.BytesIO(file_bytes))
    df = _clean_columns(df)
    row_count = len(df)
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    csv_dest = os.path.join(DATA_DIR, f"{table_name}.csv")
    with open(csv_dest, "wb") as f:
        f.write(file_bytes)
    return {
        "table_name": table_name,
        "original_filename": filename,
        "row_count": row_count,
        "columns": df.columns.tolist(),
        "column_types": {col: str(df[col].dtype) for col in df.columns},
    }


def upload_excel(file_bytes: bytes, filename: str) -> dict:
    import io
    xls = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, engine="openpyxl")
    results = []
    base_name = os.path.splitext(os.path.basename(filename))[0]
    for sheet_name, df in xls.items():
        safe_name = csv_filename_to_table(f"{base_name}_{sheet_name}")
        df = _clean_columns(df)
        df.to_sql(safe_name, engine, if_exists="replace", index=False)
        results.append({
            "table_name": safe_name,
            "sheet": sheet_name,
            "row_count": len(df),
            "columns": df.columns.tolist(),
        })
    dest = os.path.join(DATA_DIR, csv_filename_to_table(filename) + ".xlsx")
    with open(dest, "wb") as f:
        f.write(file_bytes)

    total_rows = sum(r["row_count"] for r in results)
    all_cols = []
    for r in results:
        all_cols.extend(r["columns"])

    return {
        "table_name": results[0]["table_name"] if results else "unknown",
        "original_filename": filename,
        "sheets": results,
        "row_count": total_rows,
        "columns": list(set(all_cols)),
        "column_types": {},
    }


def upload_pdf(file_bytes: bytes, filename: str) -> dict:
    import io
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append({"page_number": i + 1, "content": text.strip()})

    table_name = csv_filename_to_table(filename)
    df = pd.DataFrame(pages)
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    dest = os.path.join(DATA_DIR, table_name + ".pdf")
    with open(dest, "wb") as f:
        f.write(file_bytes)

    total_chars = sum(len(p["content"]) for p in pages)

    return {
        "table_name": table_name,
        "original_filename": filename,
        "row_count": len(pages),
        "columns": ["page_number", "content"],
        "column_types": {"page_number": "int64", "content": "object"},
        "total_pages": len(pages),
        "total_chars": total_chars,
    }


def upload_text(file_bytes: bytes, filename: str) -> dict:
    text = file_bytes.decode("utf-8", errors="replace")
    lines = [l for l in text.split("\n") if l.strip()]

    chunks = []
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) > 500:
            if chunk:
                chunks.append({"chunk_id": len(chunks) + 1, "content": chunk.strip()})
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        chunks.append({"chunk_id": len(chunks) + 1, "content": chunk.strip()})

    table_name = csv_filename_to_table(filename)
    df = pd.DataFrame(chunks)
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    # Preserve original extension (.md, .log, .txt) for correct agent detection
    orig_ext = os.path.splitext(filename)[1].lower() or ".txt"
    dest = os.path.join(DATA_DIR, table_name + orig_ext)
    with open(dest, "wb") as f:
        f.write(file_bytes)

    return {
        "table_name": table_name,
        "original_filename": filename,
        "row_count": len(chunks),
        "columns": ["chunk_id", "content"],
        "column_types": {"chunk_id": "int64", "content": "object"},
    }


def init_db(csv_path: str = None):
    """Initialize the database with an optional default CSV file."""
    source = None
    if csv_path and os.path.exists(csv_path):
        source = csv_path
    else:
        # Look for any CSV file in the data directory as a default
        for f in os.listdir(DATA_DIR):
            if f.endswith('.csv'):
                source = os.path.join(DATA_DIR, f)
                break

    if not source:
        print("No default CSV found — skipping init_db(). Upload a file to get started.")
        return False

    with open(source, "rb") as f:
        file_bytes = f.read()

    fname = os.path.basename(source)
    result = upload_csv(file_bytes, fname)
    print(f"Default dataset loaded: {result}")
    return True

def clear_all_data():
    """Removes all tables and all files in data directory."""
    from sqlalchemy import text
    tables = get_all_tables()
    
    try:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA busy_timeout = 5000"))
            for t in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{t}"'))
        
        # Remove files
        for filename in os.listdir(DATA_DIR):
            if filename == "universal.db" or filename.startswith("universal.db-"):
                continue
            fpath = os.path.join(DATA_DIR, filename)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                elif os.path.isdir(fpath):
                    shutil.rmtree(fpath)
            except Exception as e:
                print(f"Failed to remove {fpath}: {e}")
        
        return True
    except Exception as e:
        print(f"Error clearing data: {e}")
        return False

def get_all_tables() -> list[str]:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    # Filter out internal SQLite tables
    return [t for t in tables if not t.startswith('sqlite_')]


def get_table_schema(table_name: str) -> dict:
    inspector = inspect(engine)
    try:
        cols = inspector.get_columns(table_name)
        return {col["name"]: str(col["type"]) for col in cols}
    except Exception:
        return {}


def get_schema() -> dict:
    tables = get_all_tables()
    if not tables:
        return {}
    return get_table_schema(tables[0])


def get_sample_data(n: int = 3, table_name: str = None) -> list[dict]:
    if not table_name:
        tables = get_all_tables()
        if not tables:
            return []
        table_name = tables[0]
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT * FROM "{table_name}" LIMIT {n}'))
            return [dict(row._mapping) for row in result]
    except Exception:
        return []


def get_all_schemas() -> dict:
    tables = get_all_tables()
    return {t: get_table_schema(t) for t in tables}


def get_schema_prompt(table_name: str = None, tables_list: list[str] = None) -> str:
    if tables_list is not None:
        tables = tables_list
    elif table_name:
        tables = [table_name]
    else:
        tables = get_all_tables()

    if not tables:
        return "No data uploaded yet."

    lines = []
    for t in tables:
        # Determine source extension
        source_ext = ""
        for ext in ['.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md']:
            if os.path.exists(os.path.join(DATA_DIR, f"{t}{ext}")):
                source_ext = ext
                break
        
        schema = get_table_schema(t)
        samples = get_sample_data(2, t)
        lines.append(f"TABLE: {t}{f' (Source: {source_ext})' if source_ext else ''}")
        lines.append("COLUMNS:")
        for col, typ in schema.items():
            lines.append(f"  - {col} ({typ})")
        if samples:
            lines.append(f"SAMPLE ROW: {samples[0]}")
        lines.append("")

    return "\n".join(lines)