import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional, List
from pydantic import BaseModel
from dotenv import load_dotenv, set_key

from backend.db import (
    init_db, get_all_tables, get_table_schema,
    get_sample_data, get_all_schemas, DB_PATH,
    upload_csv, upload_excel, upload_pdf, upload_text,
    clear_all_data
)
from backend.graph import run_graph_agent, get_provider_status, reset_agent
from backend.agents import (
    get_all_agents, get_agent_connections, run_agent_query, run_workflow, 
    run_parallel_analysis, categorize_file_type, get_agents_for_file, 
    get_categorization_info, run_parallel_workflow
)

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
)


#Start
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(ENV_PATH)

    tables = get_all_tables()
    if not tables:
        print("Initializing default dataset...")
        init_db()
    else:
        print(f"DB ready with tables: {tables}")
    yield


#App

app = FastAPI(
    title="AI Data Analyst",
    description="Upload any CSV and query it with natural language",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    question: str

class SetKeyRequest(BaseModel):
    provider: str
    api_key: str

@app.post("/api/query")
async def query_endpoint(question: str = Body(..., embed=True)):
    question = question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    return run_parallel_analysis(question)


@app.post("/api/upload")
async def upload_endpoint(file: UploadFile = File(...)):

    SUPPORTED = ('.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md')
    fname = file.filename.lower()
    if not any(fname.endswith(ext) for ext in SUPPORTED):
        raise HTTPException(400, f"Unsupported file type. Supported: {', '.join(SUPPORTED)}")

    MAX_SIZE = 50 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(413, "File too large (max 50MB)")

    try:
        if fname.endswith('.csv'):
            info = upload_csv(contents, file.filename)
        elif fname.endswith('.xlsx') or fname.endswith('.xls'):
            info = upload_excel(contents, file.filename)
        elif fname.endswith('.pdf'):
            info = upload_pdf(contents, file.filename)
        elif fname.endswith('.txt') or fname.endswith('.log') or fname.endswith('.md'):
            info = upload_text(contents, file.filename)
        else:
            raise HTTPException(400, f"Unsupported file type: {file.filename}")

        file_type = 'csv' if fname.endswith('.csv') else 'excel' if fname.endswith(('.xlsx', '.xls')) else 'pdf' if fname.endswith('.pdf') else 'text'
        
        # Get auto-categorization info
        categorization = get_categorization_info(file.filename)
        
        return {
            "status": "ok",
            "file_type": file_type,
            "message": f"'{file.filename}' uploaded successfully.",
            "categorization": categorization,
            "recommended_agents": categorization["recommended_agents"],
            **info,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to process file: {e}")


@app.get("/api/datasets")
async def datasets_endpoint():
    tables = get_all_tables()
    result = []
    for t in tables:
        schema = get_table_schema(t)
        sample = get_sample_data(1, t)
        result.append({
            "table_name": t,
            "columns": schema,
            "column_count": len(schema),
            "sample_row": sample[0] if sample else {},
        })
    return {"datasets": result, "count": len(result)}


@app.delete("/api/datasets/{table_name}")
async def delete_dataset(table_name: str):
    from sqlalchemy import text
    from backend.db import engine, DATA_DIR, get_all_tables
    import os


    tables = get_all_tables()

    actual_table_name = next((t for t in tables if t.lower() == table_name.lower()), None)
    
    if not actual_table_name:
        print(f"Table deletion failed: '{table_name}' not found in {tables}")
        raise HTTPException(404, f"Table '{table_name}' not found.")
    
    try:

        with engine.begin() as conn:
            conn.execute(text("PRAGMA busy_timeout = 5000"))
            conn.execute(text(f'DROP TABLE IF EXISTS "{actual_table_name}"'))
            print(f"SQL: DROP TABLE '{actual_table_name}' executed.")
    
        cleaned_any_file = False
        for ext in ['.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md']:
            for name_to_try in [table_name, actual_table_name]:
                fpath = os.path.join(DATA_DIR, f"{name_to_try}{ext}")
                if os.path.exists(fpath):
                    os.remove(fpath)
                    cleaned_any_file = True
                    print(f"Removed file: {fpath}")
                
        return {
            "status": "ok", 
            "message": f"Dataset '{actual_table_name}' removed.",
            "files_cleaned": cleaned_any_file
        }
    except Exception as e:
        print(f"Error deleting table '{table_name}': {e}")
        raise HTTPException(500, f"Failed to remove dataset: {str(e)}")


@app.delete("/api/datasets/clear-all")
async def clear_all_datasets():
    try:
        success = clear_all_data()
        if not success:
            raise HTTPException(500, "Failed to clear all data")
        return {"status": "ok", "message": "All datasets and files cleared."}
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@app.get("/api/setup")
async def setup_endpoint():
    load_dotenv(ENV_PATH, override=True)
    return {
        "providers": get_provider_status(),
        "database_ready": os.path.exists(DB_PATH),
        "tables": get_all_tables(),
    }


@app.post("/api/set-key")
async def set_key_endpoint(req: SetKeyRequest):
    key_map = {"google": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY"}
    env_var = key_map.get(req.provider.lower())
    if not env_var:
        raise HTTPException(400, f"Unknown provider: {req.provider}")
    if not req.api_key.strip():
        raise HTTPException(400, "API key cannot be empty")
    set_key(ENV_PATH, env_var, req.api_key.strip())
    os.environ[env_var] = req.api_key.strip()
    reset_agent()
    return {"status": "ok", "provider": req.provider}


@app.get("/api/schema")
async def schema_endpoint():
    tables = get_all_tables()
    if not tables:
        return {"table": None, "columns": {}, "sample_data": []}
    t = tables[0]
    return {
        "table": t,
        "columns": get_table_schema(t),
        "sample_data": get_sample_data(3, t),
    }


@app.get("/api/health")
async def health_endpoint():
    load_dotenv(ENV_PATH, override=True)
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "database": os.path.exists(DB_PATH),
        "tables": get_all_tables(),
        "providers": get_provider_status(),
    }

class AgentQueryRequest(BaseModel):
    question: str
    agent_id: str = "data_extractor"

@app.get("/api/agents")
async def list_agents():
    return {
        "agents": get_all_agents(),
        "connections": get_agent_connections(),
    }


@app.get("/api/categorizations")
async def list_categorizations():
    categorizations = {}
    file_types = ['test.csv', 'test.xlsx', 'test.pdf', 'test.txt']
    
    for fname in file_types:
        cat_info = get_categorization_info(fname)
        file_type = cat_info['file_type']
        categorizations[file_type] = {
            'label': cat_info['category']['label'],
            'icon': cat_info['category']['icon'],
            'color': cat_info['category']['color'],
            'description': cat_info['category']['description'],
            'primary_agent': cat_info['primary_agent'],
            'agents': cat_info['recommended_agents'],
        }
    
    return {
        "status": "ok",
        "categorizations": categorizations,
        "message": "File type categorizations and agent mappings",
    }

@app.post("/api/agent/query")
async def agent_query_endpoint(req: AgentQueryRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    return run_agent_query(req.agent_id, question)

@app.post("/api/workflow")
async def workflow_endpoint(question: str = Body(..., embed=True)):
    question = question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    return run_parallel_analysis(question)

@app.post("/api/parallel-workflow")
async def parallel_workflow_endpoint(req: QueryRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    return run_parallel_workflow(question)


@app.post("/api/categorize-file")
async def categorize_file_endpoint(filename: str):
    if not filename.strip():
        raise HTTPException(400, "Filename cannot be empty")
    
    categorization = get_categorization_info(filename)
    return {
        "status": "ok",
        "categorization": categorization,
    }


class UploadAndAnalyzeRequest(BaseModel):
    question: str = "Analyze this data and extract all insights"
    analyze: bool = True
    focus_agents: list[str] = None


@app.post("/api/upload-and-analyze")
async def upload_and_analyze_endpoint(
    file: UploadFile = File(...),
    question: str = "Analyze this data and extract all insights",
    analyze: bool = True,
    focus_agents: str = None,  # JSON string of agent IDs
):
    import json
    
    SUPPORTED = ('.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md')
    fname = file.filename.lower()
    if not any(fname.endswith(ext) for ext in SUPPORTED):
        raise HTTPException(400, f"Unsupported file type. Supported: {', '.join(SUPPORTED)}")

    MAX_SIZE = 50 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(413, "File too large (max 50MB)")

    try:
        # Step 1: Upload the file
        if fname.endswith('.csv'):
            upload_info = upload_csv(contents, file.filename)
        elif fname.endswith('.xlsx') or fname.endswith('.xls'):
            upload_info = upload_excel(contents, file.filename)
        elif fname.endswith('.pdf'):
            upload_info = upload_pdf(contents, file.filename)
        elif fname.endswith('.txt') or fname.endswith('.log') or fname.endswith('.md'):
            upload_info = upload_text(contents, file.filename)
        else:
            raise HTTPException(400, f"Unsupported file type: {file.filename}")

        file_type = 'csv' if fname.endswith('.csv') else 'excel' if fname.endswith(('.xlsx', '.xls')) else 'pdf' if fname.endswith('.pdf') else 'text'
        
        # Step 2: Get categorization info
        categorization = get_categorization_info(file.filename)
        
        result = {
            "status": "ok",
            "file_type": file_type,
            "message": f"'{file.filename}' uploaded successfully.",
            "categorization": categorization,
            **upload_info,
        }
        
        # Step 3: Run analysis if requested
        if analyze and question.strip():
            # Parse focus agents if provided
            agents_to_use = None
            if focus_agents:
                try:
                    agents_to_use = json.loads(focus_agents)
                except:
                    agents_to_use = None
            
            # If no focus agents specified, use the recommended agents for this file
            if not agents_to_use:
                agents_to_use = categorization["recommended_agents"]
            
            print(f"[auto-analyze] Running analysis with agents: {agents_to_use}")
            analysis_result = run_parallel_analysis(question, focus_agents=agents_to_use)
            result["analysis"] = analysis_result
            result["auto_analysis_agents"] = agents_to_use
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to process file: {e}")


class ParallelAnalysisRequest(BaseModel):
    question: str
    focus_agents: Optional[List[str]] = None
    focus_tables: Optional[List[str]] = None


@app.post("/api/parallel-analysis")
async def parallel_analysis_endpoint(req: ParallelAnalysisRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    
    focus_agents = req.focus_agents if req.focus_agents and len(req.focus_agents) > 0 else None
    focus_tables = req.focus_tables if req.focus_tables and len(req.focus_tables) > 0 else None
    
    return run_parallel_analysis(question, focus_agents=focus_agents, focus_tables=focus_tables)

@app.post("/api/agent/upload")
async def agent_upload_endpoint(agent_id: str = "csv_agent", file: UploadFile = File(...)):
    MAX_SIZE = 50 * 1024 * 1024
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(413, "File too large")

    fname = file.filename.lower()
    try:
        if agent_id in ("csv_agent", "structured_data", "data_extractor") and fname.endswith(".csv"):
            info = upload_csv(contents, file.filename)
        elif agent_id in ("xls_agent", "structured_data", "data_extractor") and (fname.endswith(".xlsx") or fname.endswith(".xls")):
            info = upload_excel(contents, file.filename)
        elif agent_id in ("pdf_agent", "unstructured_data", "data_extractor") and fname.endswith(".pdf"):
            info = upload_pdf(contents, file.filename)
        elif agent_id in ("text_agent", "unstructured_data", "data_extractor") and (fname.endswith(".txt") or fname.endswith(".log") or fname.endswith(".md")):
            info = upload_text(contents, file.filename)
        else:
            # Try to auto-detect by extension
            if fname.endswith(".csv"):
                info = upload_csv(contents, file.filename)
            elif fname.endswith(".xlsx") or fname.endswith(".xls"):
                info = upload_excel(contents, file.filename)
            elif fname.endswith(".pdf"):
                info = upload_pdf(contents, file.filename)
            elif fname.endswith(".txt") or fname.endswith(".log") or fname.endswith(".md"):
                info = upload_text(contents, file.filename)
            else:
                raise HTTPException(400, f"Unsupported file type: {file.filename}")

        # Get auto-categorization info
        categorization = get_categorization_info(file.filename)
        
        return {
            "status": "ok",
            "agent_id": agent_id,
            "message": f"'{file.filename}' processed successfully.",
            "categorization": categorization,
            "recommended_agents": categorization["recommended_agents"],
            **info,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to process file: {e}")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/canvas")
async def canvas_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "canvas.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
