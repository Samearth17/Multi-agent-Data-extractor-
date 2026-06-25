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
    from backend.db import get_schema_pro