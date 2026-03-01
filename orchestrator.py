"""
orchestrator.py
Master API that chains: Data Ingestor → Research Agent (optional) → Synthesized JSON → FAISS
Single entry point for the frontend.

Usage:
    uvicorn orchestrator:app --reload --port 9000
"""

import os
import sys
import json
import shutil
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Add extractor to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "extractor"))

from research_agent.web_search import search_company
from research_agent.synthesizer import synthesize

app = FastAPI(
    title="Intelli-Credit Orchestrator",
    description="Master API: Data Ingestor + Research Agent → Unified Credit JSON",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "extractor", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.get("/")
def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "online"}


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/analyze")
async def analyze(
    company_name: str = Form(...),
    web_search: str = Form("true"),
    files: List[UploadFile] = File(...)
):
    """
    Full pipeline:
    1. Save uploads → temp folder
    2. Run Data Ingestor
    3. (Optional) Run Research Agent
    4. Synthesize → Final JSON
    5. Auto-ingest into FAISS
    """
    do_web = web_search.lower() in ("true", "1", "yes")
    request_id = uuid.uuid4().hex[:8]
    temp_input = os.path.join(os.path.dirname(__file__), "extractor", f"_tmp_{request_id}")
    os.makedirs(temp_input, exist_ok=True)

    try:
        # Step 1: Save files
        print(f"\n[Orchestrator] {request_id}: {len(files)} file(s), company='{company_name}', web={do_web}")
        for f in files:
            dest = os.path.join(temp_input, f.filename)
            with open(dest, "wb") as buf:
                buf.write(await f.read())

        # Step 2: Data Ingestor
        print(f"[Orchestrator] Running Data Ingestor...")
        from main import run_pipeline
        ingestor_json = run_pipeline(input_folder=temp_input, company_hint=company_name, demo=False)

        if isinstance(ingestor_json, dict) and "error" in ingestor_json:
            raise HTTPException(status_code=400, detail=ingestor_json["error"])

        # Step 3: Research Agent (optional)
        if do_web:
            print(f"[Orchestrator] Running Research Agent (web search)...")
            industry = ingestor_json.get("company_snapshot", {}).get("industry", "")
            research_data = search_company(company_name, industry=industry)
            final_json = synthesize(ingestor_json, research_data)
        else:
            print(f"[Orchestrator] Skipping web search (toggle off)")
            final_json = ingestor_json

        # Save output
        safe_name = company_name.replace(" ", "_").replace("/", "_")[:40]
        out_name = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path = os.path.join(OUTPUT_DIR, out_name)
        with open(out_path, "w") as f:
            json.dump(final_json, f, indent=2)

        print(f"[Orchestrator] ✅ Saved: {out_name}")
        return final_json

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Orchestrator] ❌ {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_input):
            shutil.rmtree(temp_input, ignore_errors=True)


@app.get("/outputs")
def list_outputs():
    if not os.path.exists(OUTPUT_DIR):
        return {"files": [], "count": 0}
    files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".json")], reverse=True)
    return {"files": files, "count": len(files)}


@app.get("/output/{filename}")
def get_output(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Not found: {filename}")
    with open(path, "r") as f:
        return json.load(f)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
