# app/main.py
"""
Complete FastAPI implementation for the Store Intelligence System.
Handles JSON payload validations, bootstrapping, and exposes REST endpoints.
Exposes both strict compliant endpoints and backward-compatible versions.
"""
import os
import time
import uuid
import json
import sqlite3
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.models import EventPayload
from app.ingestion import IngestionEngine
from app.metrics import MetricsEngine
from app.funnel import FunnelEngine
from app.anomalies import AnomalyEngine
from app.health import HealthCheck

app = FastAPI(
    title="Purplle Store Intelligence API",
    description="Backend for ingestion and computation of conversion, funnels, and store retail metrics.",
    version="1.0.0"
)

# Enable CORS for the dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize engines
ingestion_engine = IngestionEngine()
metrics_engine = MetricsEngine()
funnel_engine = FunnelEngine()
anomaly_engine = AnomalyEngine()
health_check = HealthCheck()

# Structured logging middleware
@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    start_time = time.time()
    
    # Try to extract store_id
    store_id = None
    path_parts = request.url.path.strip("/").split("/")
    if "stores" in path_parts:
        idx = path_parts.index("stores")
        if len(path_parts) > idx + 1:
            store_id = path_parts[idx + 1]
    
    if not store_id:
        store_id = request.query_params.get("store_id")

    # Proceed with request
    response = await call_next(request)
    
    latency_ms = int((time.time() - start_time) * 1000)
    event_count = getattr(request.state, "event_count", 0)
    
    # Generate structured log line
    log_line = {
        "trace_id": trace_id,
        "store_id": store_id,
        "endpoint": request.url.path,
        "latency_ms": latency_ms,
        "event_count": event_count,
        "status_code": response.status_code
    }
    print(json.dumps(log_line))
    return response

# SQL DB failure exception mapper (graceful degradation returning HTTP 503)
@app.exception_handler(sqlite3.OperationalError)
def sqlite_exception_handler(request: Request, exc: sqlite3.OperationalError):
    trace_id = getattr(request.state, "trace_id", "unknown")
    log_line = {
        "trace_id": trace_id,
        "endpoint": request.url.path,
        "status_code": 503,
        "error": f"Database Operational Error: {str(exc)}"
    }
    print(json.dumps(log_line))
    return JSONResponse(
        status_code=503,
        content={"detail": "Service Temporarily Unavailable: Database connection failed or is locked."}
    )

# Prevent Python stack traces from leaking in general unhandled exceptions (return HTTP 500)
@app.exception_handler(Exception)
def general_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "unknown")
    log_line = {
        "trace_id": trace_id,
        "endpoint": request.url.path,
        "status_code": 500,
        "error": f"Unhandled Server Exception: {str(exc)}"
    }
    print(json.dumps(log_line))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error."}
    )

@app.on_event("startup")
def bootstrap_sample_data():
    """Bootstraps the database with sample events if empty."""
    # Check if empty
    conn = sqlite3.connect("store_intelligence.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM events")
    count = cursor.fetchone()[0]
    conn.close()

    if count == 0:
        jsonl_files = []
        if os.path.exists("emitted_events.jsonl"):
            jsonl_files.append("emitted_events.jsonl")
        for file in os.listdir("."):
            if file.startswith("sample_events") and file.endswith(".jsonl"):
                jsonl_files.append(file)
        
        # Deduplicate
        jsonl_files = list(set(jsonl_files))
        
        if not jsonl_files:
            print("No event files found for bootstrapping.")
            return

        for events_file in jsonl_files:
            print(f"Bootstrapping database with events from {events_file}...")
            with open(events_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        ingestion_engine.ingest_raw_json(line)
        print("Bootstrapping complete.")
    else:
        print("Database already contains events. Skipping bootstrapper.")

@app.get("/", response_class=HTMLResponse)
def read_root():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Purplle Store Intelligence API Gateway</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #0b071e;
                --panel-bg: rgba(25, 18, 48, 0.65);
                --border-color: rgba(255, 255, 255, 0.1);
                --text-primary: #ffffff;
                --text-secondary: #a39cb5;
                --accent-purplle: #7e22ce;
                --accent-pink: #ec4899;
                --accent-cyan: #06b6d4;
            }
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
                font-family: 'Outfit', sans-serif;
            }
            body {
                background-color: var(--bg-color);
                background-image: radial-gradient(circle at 10% 20%, rgba(126, 34, 206, 0.15) 0%, transparent 40%),
                                  radial-gradient(circle at 90% 80%, rgba(236, 72, 153, 0.15) 0%, transparent 40%);
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                padding: 20px;
                color: var(--text-primary);
            }
            .container {
                max-width: 600px;
                width: 100%;
                text-align: center;
                background: var(--panel-bg);
                border: 1px solid var(--border-color);
                border-radius: 20px;
                padding: 40px;
                backdrop-filter: blur(12px);
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            }
            h1 {
                font-size: 2.2rem;
                font-weight: 800;
                background: linear-gradient(135deg, var(--accent-cyan), var(--accent-pink));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 10px;
            }
            .subtitle {
                font-size: 1rem;
                color: var(--text-secondary);
                margin-bottom: 30px;
            }
            .links-grid {
                display: flex;
                flex-direction: column;
                gap: 15px;
            }
            .btn {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 18px 25px;
                border-radius: 12px;
                text-decoration: none;
                font-weight: 600;
                transition: all 0.3s ease;
                border: 1px solid var(--border-color);
                background: rgba(255, 255, 255, 0.03);
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
            }
            .btn-dashboard {
                border-color: rgba(6, 182, 212, 0.4);
                color: var(--accent-cyan);
            }
            .btn-dashboard:hover {
                background: rgba(6, 182, 212, 0.1);
            }
            .btn-docs {
                border-color: rgba(236, 72, 153, 0.4);
                color: var(--accent-pink);
            }
            .btn-docs:hover {
                background: rgba(236, 72, 153, 0.1);
            }
            .btn-health {
                border-color: rgba(126, 34, 206, 0.4);
                color: #a78bfa;
            }
            .btn-health:hover {
                background: rgba(126, 34, 206, 0.1);
            }
            .btn span {
                color: inherit;
            }
            .btn-arrow {
                font-size: 1.2rem;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Purplle Store Intelligence</h1>
            <p class="subtitle">API Gateway & Live Analytics Portal</p>
            <div class="links-grid">
                <a href="/dashboard" class="btn btn-dashboard">
                    <span>📊 Go to Dashboard</span>
                    <span class="btn-arrow">→</span>
                </a>
                <a href="/docs" class="btn btn-docs">
                    <span>🔌 Interactive API Docs (Swagger)</span>
                    <span class="btn-arrow">→</span>
                </a>
                <a href="/health" class="btn btn-health">
                    <span>❤️ Service Health Status</span>
                    <span class="btn-arrow">→</span>
                </a>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return html_content

@app.get("/health")
def get_health():
    return health_check.check()

# --- STRICT COMPLIANT ENDPOINTS ---

@app.post("/events/ingest")
def ingest_batch_events(events: List[Dict[str, Any]], request: Request):
    """
    Strictly compliant endpoint accepting a batch of up to 500 events.
    Enforces validation, deduplication, and handles partial successes.
    """
    if len(events) > 500:
        raise HTTPException(status_code=400, detail="Batch size exceeds maximum limit of 500 events.")
    
    # Store event count on request state for logger
    request.state.event_count = len(events)
    
    result = ingestion_engine.ingest_batch(events)
    return result

@app.get("/stores/{id}/metrics")
def get_store_metrics(id: str, date: str = "2026-03-08"):
    try:
        return metrics_engine.compute_metrics(id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stores/{id}/funnel")
def get_store_funnel(id: str, date: str = "2026-03-08"):
    try:
        return funnel_engine.compute_funnel(id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stores/{id}/anomalies")
def get_store_anomalies(id: str, date: str = "2026-03-08"):
    try:
        return anomaly_engine.detect_anomalies(id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stores/{id}/heatmap")
def get_store_heatmap(id: str, date: str = "2026-03-08"):
    try:
        return metrics_engine.compute_heatmap(id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- BACKWARD COMPATIBLE ENDPOINTS (For existing tests & runner) ---

@app.post("/events")
def ingest_event(event: EventPayload, request: Request):
    request.state.event_count = 1
    success = ingestion_engine.ingest(event)
    if not success:
        raise HTTPException(status_code=400, detail="Event ingestion or validation failed.")
    return {"status": "success", "message": "Event recorded successfully."}

@app.get("/metrics")
def get_metrics(store_id: str, date: str = "2026-03-08"):
    try:
        return metrics_engine.compute_metrics(store_id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/funnel")
def get_funnel(store_id: str, date: str = "2026-03-08"):
    try:
        return funnel_engine.compute_funnel(store_id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/anomalies")
def get_anomalies(store_id: str, date: str = "2026-03-08"):
    try:
        return anomaly_engine.detect_anomalies(store_id, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
