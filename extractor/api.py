"""
api.py
FastAPI wrapper for the Credit Extractor Pipeline.
Enables research agents and other services to pull structured credit data via HTTP.

Usage:
    uvicorn api:app --reload --port 8000

Endpoints:
    POST /process     — Run full extraction pipeline, returns new-format JSON
    GET  /outputs     — List all generated JSON files
    GET  /output/{id} — Get a specific output file
"""

import os
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from main import run_pipeline

app = FastAPI(
    title="Intelli-Credit API",
    description="API for multi-format document extraction, credit analysis, and FAISS ingestion.",
    version="2.0.0"
)


class ExtractionRequest(BaseModel):
    folder: str = "input"
    company_hint: Optional[str] = None
    demo: bool = False


@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Intelli-Credit Pipeline API v2.0",
        "schema": "New 12-section credit schema",
        "endpoints": {
            "POST /process": "Triggers full extraction → new JSON + FAISS ingestion",
            "GET  /outputs": "Lists all generated JSON files",
            "GET  /output/{filename}": "Returns a specific output JSON",
            "GET  /docs": "Swagger API documentation",
        }
    }


@app.post("/process")
def process_documents(request: ExtractionRequest):
    """
    Triggers the full extraction pipeline for the specified folder.
    Returns the new 12-section credit schema JSON.
    Auto-ingests output into FAISS vector database.
    """
    try:
        result = run_pipeline(
            input_folder = request.folder,
            company_hint = request.company_hint,
            demo         = request.demo
        )
        
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
            
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@app.get("/outputs")
def list_outputs():
    """Lists all generated JSON output files."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return {"files": []}
    
    files = [f for f in os.listdir(output_dir) if f.endswith(".json")]
    return {"files": files, "count": len(files)}


@app.get("/output/{filename}")
def get_output(filename: str):
    """Returns the contents of a specific output JSON file."""
    path = os.path.join("output", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    
    with open(path, "r") as f:
        return json.load(f)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
