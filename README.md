# ⚡ Universal Data Extractor

A multi-agent AI-powered data analysis platform that lets you upload **any file** (CSV, Excel, PDF, Text) and query it using natural language. Built with a hierarchical agent architecture that automatically routes your data to the right specialist agent for analysis.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-121212?style=flat&logo=chainlink&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## ✨ Features

- **📂 Universal File Support** — Upload CSV, Excel (.xlsx/.xls), PDF, and Text/Log/Markdown files
- **🤖 Multi-Agent Architecture** — Hierarchical agent system with specialized agents for each file type
- **⚡ Parallel Processing** — Multiple agents analyze your data simultaneously for faster results
- **🗣️ Natural Language Queries** — Ask questions in plain English, get SQL-powered answers
- **📊 Auto-Visualization** — Charts and tables are generated automatically from query results
- **🎨 Agent Canvas** — Visual drag-and-drop interface to see agent hierarchy and workflow
- **🔄 Auto-Categorization** — Files are automatically routed to the correct specialist agent
- **🔌 Multi-Provider LLM Support** — Works with Google Gemini, Groq, and NVIDIA APIs (all free tiers available)

## 🏗️ Architecture

```
                    ┌──────────────────┐
                    │  Data Extractor  │  ← Top-level Orchestrator
                    │   (Orchestrator) │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │                             │
    ┌─────────▼──────────┐       ┌─────────▼──────────┐
    │  Structured Data   │       │ Unstructured Data   │
    │    (Manager)       │       │    (Manager)        │
    └────────┬───────────┘       └────────┬────────────┘
             │                            │
      ┌──────┴──────┐             ┌──────┴──────┐
      │             │             │             │
  ┌───▼───┐   ┌────▼──┐    ┌────▼───┐   ┌────▼───┐
  │  CSV  │   │  XLS  │    │  PDF   │   │  Text  │
  │ Agent │   │ Agent │    │ Agent  │   │ Agent  │
  └───────┘   └───────┘    └────────┘   └────────┘
```

Each specialist agent has SQL access to the database and uses LLM-powered reasoning to analyze your data.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- At least one LLM API key (all have free tiers):
  - [Google Gemini](https://aistudio.google.com/apikey) (Recommended — Free)
  - [Groq](https://console.groq.com/keys) (Free)
  - [NVIDIA](https://build.nvidia.com) (Free BUILD program)

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/universal-data-extractor.git
cd universal-data-extractor

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add at least one API key
```

### Run Locally

```bash
# Start the server
uvicorn backend.main:app --reload --port 8000

# Open in browser
open http://localhost:8000
```

The app will be available at `http://localhost:8000` with the Agent Canvas at `http://localhost:8000/canvas`.

## 📖 Usage

1. **Upload a file** — Drag & drop or click to upload any CSV, Excel, PDF, or text file
2. **Ask a question** — Type a natural language question about your data
3. **Get insights** — The AI agents analyze your data and return tables, charts, and explanations
4. **Use the Canvas** — Visit `/canvas` to see the multi-agent workflow visually

### Example Questions

- *"What are the top 5 rows?"*
- *"Show me a summary of the numeric columns with min, max, and average"*
- *"How many unique categories are there?"*
- *"Create a bar chart comparing sales by region"*

## 🔧 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI, Python 3.11+ |
| **Database** | SQLite (via SQLAlchemy) |
| **AI/ML** | LangChain, LangGraph, SQL Toolkit |
| **LLM Providers** | Google Gemini, Groq, NVIDIA |
| **Frontend** | Vanilla HTML/CSS/JS, Chart.js |
| **File Parsing** | Pandas, PyPDF2, openpyxl |

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Main chat interface |
| `GET` | `/canvas` | Agent canvas visualization |
| `POST` | `/api/upload` | Upload a file |
| `POST` | `/api/query` | Query data with natural language |
| `GET` | `/api/datasets` | List all uploaded datasets |
| `DELETE` | `/api/datasets/{name}` | Delete a dataset |
| `GET` | `/api/agents` | List all agents and connections |
| `POST` | `/api/parallel-analysis` | Run multi-agent parallel analysis |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/setup` | Check provider configuration |
| `POST` | `/api/set-key` | Configure an API key |

## 🌐 Deployment

### Deploy to Render (Recommended — Free Tier)

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables (API keys) in the Render dashboard

### Deploy to Railway

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | At least one | Google Gemini API key |
| `GROQ_API_KEY` | At least one | Groq API key |
| `NVIDIA_API_KEY` | Optional | NVIDIA API key |

## 📁 Project Structure

```
universal-data-extractor/
├── backend/
│   ├── __init__.py       # Package init
│   ├── main.py           # FastAPI app & routes
│   ├── db.py             # SQLite database operations
│   ├── agents.py         # Multi-agent system & registry
│   ├── graph.py          # LLM integration & SQL agent
│   └── util.py           # SQL cleaning & validation
├── frontend/
│   ├── index.html        # Main chat interface
│   ├── style.css         # Chat UI styles
│   ├── script.js         # Chat logic
│   ├── canvas.html       # Agent canvas page
│   ├── canvas.css        # Canvas styles
│   └── canvas.js         # Canvas interaction logic
├── .env.example          # Environment template
├── requirements.txt      # Python dependencies
├── Procfile              # Deployment config
├── ARCHITECTURE.md       # Detailed architecture docs
├── LICENSE               # MIT License
└── README.md             # This file
```

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

Built with ❤️ using FastAPI, LangChain, and multi-agent AI
