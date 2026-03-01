"""
api/main.py
===========
FastAPI application — single POST /research endpoint.

Accepts a ResearchRequest JSON body (validated by Pydantic),
builds EntityProfile, runs 6-source orchestrator,
and returns a ResearchOutput JSON.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from config.settings import get_settings
from core.entity_builder import build_entity_profile
from core.input_contract import ResearchRequest
from core.orchestrator import run_research

logger   = structlog.get_logger(__name__)
settings = get_settings()


# ── App lifecycle ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("research_agent_starting", version=settings.app_version)
    yield
    logger.info("research_agent_shutdown")


# ── FastAPI app ───────────────────────────────────────────────

app = FastAPI(
    title="Research Agent — Credit Intelligence API",
    description=(
        "Automated KYC/due-diligence pipeline for Indian SME loan applicants. "
        "Checks 6 sources: RBI defaulter list, MCA21, "
        "eCourts, Tavily news, GSTN, and internal Qualitative Notes."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request timing middleware ─────────────────────────────────

@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    t0       = time.monotonic()
    response = await call_next(request)
    elapsed  = round((time.monotonic() - t0) * 1000, 1)
    response.headers["X-Process-Time-Ms"] = str(elapsed)
    return response


# ── Health check ──────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    """Quick liveness check."""
    return {"status": "ok", "version": settings.app_version}


# ── Main endpoint ─────────────────────────────────────────────

@app.post(
    "/research",
    tags=["Research"],
    summary="Run full 6-source research on a loan applicant",
    response_description="ResearchOutput with risk score, flags, tags",
    status_code=status.HTTP_200_OK,
)
async def research(payload: ResearchRequest):
    """
    ### What this does
    1. Validates the input (CIN, GSTIN, PAN format + cross-field checks)
    2. Builds an `EntityProfile` from the request
    3. Runs **6 sources concurrently**:
       - RBI Wilful Defaulter List
       - MCA21 (charges, director history, ROC filings)
       - eCourts (litigation)
       - Tavily news (fraud/NPA signals)
       - GSTN (GST registration status)
       - Primary Insights (Qualitative Notes evaluation)
    4. Scores and tags the aggregated findings
    5. Returns `ResearchOutput`

    ### Mandatory fields
    `case_id`, `company_name`, `cin`, `gstin`, `pan`, `promoters` (≥1),
    `loan`, `ingestion_version`
    """
    log = logger.bind(case_id=payload.case_id, company=payload.company_name)
    log.info("research_request_received")

    try:
        entity = build_entity_profile(payload)
        output = await run_research(entity, db=None)
        log.info(
            "research_complete",
            score=output.risk_score,
            band=output.risk_band,
            flags=len(output.flags),
        )
        return output

    except Exception as exc:
        log.error("research_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Research pipeline error: {exc}",
        )


# ── Validation error handler ──────────────────────────────────

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": None},
    )


# ── Dev runner ────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info",
    )
