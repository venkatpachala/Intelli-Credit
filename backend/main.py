"""
backend/main.py
================
Intelli-Credit — Unified API Backend
Runs on port 8000. Orchestrates:
 - Auth (signup / login / JWT)
 - Case management (CRUD)
 - File upload → Extractor → Research Agent → CAM
 - Approver review workflow
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

load_dotenv()

# ── Config ────────────────────────────────────────────────────
SECRET_KEY     = os.getenv("JWT_SECRET", "intelli-credit-secret-key-2026-iit-hackathon")
ALGORITHM      = "HS256"
TOKEN_EXPIRE_H = 24

BASE_DIR         = Path(__file__).parent
DB_PATH          = BASE_DIR / "data.db"
UPLOADS_DIR      = BASE_DIR / "uploads"
EXTRACTOR_DIR    = BASE_DIR.parent / "extractor"
CAM_ENGINE_DIR   = BASE_DIR.parent / "cam_engine"
CAM_OUTPUT_DIR   = BASE_DIR / "cam_output"
RESEARCH_URL     = os.getenv("RESEARCH_AGENT_URL", "http://localhost:8001/research")

UPLOADS_DIR.mkdir(exist_ok=True)
CAM_OUTPUT_DIR.mkdir(exist_ok=True)

# ── Database ──────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'credit_manager',
            branch      TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cases (
            id              TEXT PRIMARY KEY,
            company_name    TEXT NOT NULL,
            cin             TEXT,
            gstin           TEXT,
            pan             TEXT,
            industry        TEXT,
            constitution    TEXT,
            address         TEXT,
            loan_amount     REAL,
            loan_type       TEXT,
            tenor           INTEGER,
            purpose         TEXT,
            promoters_json  TEXT,
            loan_json       TEXT,
            status          TEXT NOT NULL DEFAULT 'draft',
            pipeline_stage  TEXT DEFAULT 'created',
            created_by      TEXT NOT NULL,
            assigned_to_approver TEXT,
            extraction_result TEXT,
            research_result   TEXT,
            cam_json          TEXT,
            cam_docx_path     TEXT,
            cam_pdf_path      TEXT,
            approver_decision TEXT,
            approver_comments TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS pipeline_logs (
            id       TEXT PRIMARY KEY,
            case_id  TEXT NOT NULL,
            stage    TEXT NOT NULL,
            status   TEXT NOT NULL,
            message  TEXT,
            ts       TEXT NOT NULL,
            FOREIGN KEY(case_id) REFERENCES cases(id)
        );
    """)
    # Add new columns to existing databases (idempotent)
    for col, ctype in [
        ("cam_docx_path",   "TEXT"),
        ("cam_pdf_path",    "TEXT"),
        ("qualitative_json","TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} {ctype}")
            conn.commit()
        except Exception:
            pass   # Column already exists
    conn.close()


init_db()

# ── JWT Auth ──────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_token(user_id: str, email: str, role: str, name: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "name": name,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_H),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_token(credentials.credentials)


def require_manager(user=Depends(get_current_user)):
    if user["role"] not in ("credit_manager", "senior_approver"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def require_approver(user=Depends(get_current_user)):
    if user["role"] != "senior_approver":
        raise HTTPException(status_code=403, detail="Approver role required")
    return user


# ── Pydantic Models ───────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "credit_manager"
    branch: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class CaseCreateRequest(BaseModel):
    company: dict
    promoters: list
    loan: dict


class ReviewRequest(BaseModel):
    decision: str
    modified_limit: Optional[float] = None
    modified_rate: Optional[float] = None
    conditions: Optional[str] = None
    comments: str


class PrimaryInsightRequest(BaseModel):
    """Credit officer field observation inputs — adjusts the composite score."""
    factory_visit_date:   Optional[str]   = None    # ISO date string
    factory_capacity_pct: Optional[float] = None    # 0-100 %
    management_quality:   Optional[int]   = None    # 1-5
    site_condition:       Optional[str]   = None    # excellent/good/average/poor/critical
    key_person_risk:      Optional[bool]  = None
    supply_chain_risk:    Optional[bool]  = None
    cibil_commercial_score: Optional[float] = None  # 300-900
    notes:                Optional[str]   = None    # free text observations


# ── App ───────────────────────────────────────────────────────

app = FastAPI(
    title="Intelli-Credit API",
    description="Production credit appraisal platform backend",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pipeline log helper ────────────────────────────────────────

def log_stage(case_id: str, stage: str, status: str, message: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO pipeline_logs VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), case_id, stage, status, message, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def update_case_field(case_id: str, **kwargs):
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [case_id]
    conn = get_db()
    conn.execute(f"UPDATE cases SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


# ── Pipeline runner (background thread) ────────────────────────

def run_pipeline_bg(case_id: str, upload_folder: str, company_name: str, research_payload: dict):
    """
    Full pipeline:
      1. Extractor (subprocess → Python script in extractor/)
      2. Research Agent (HTTP POST)
      3. CAM generation (combine both outputs)
    """
    try:
        # STAGE 1: DOCUMENT PARSING via extractor
        update_case_field(case_id, pipeline_stage="extracting")
        log_stage(case_id, "extraction", "running", "Calling extractor pipeline...")

        extractor_python = str(EXTRACTOR_DIR / "venv" / "Scripts" / "python.exe")
        if not Path(extractor_python).exists():
            extractor_python = sys.executable  # fallback to current venv

        result = subprocess.run(
            [extractor_python, "main.py", "--folder", upload_folder,
             "--company", company_name],
            cwd=str(EXTRACTOR_DIR),
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PYTHONPATH": str(EXTRACTOR_DIR)}
        )

        extraction_data = {}
        if result.returncode == 0:
            # Find the latest output file
            output_dir = EXTRACTOR_DIR / "output"
            if output_dir.exists():
                files = sorted(output_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
                if files:
                    with open(files[0]) as f:
                        extraction_data = json.load(f)
            log_stage(case_id, "extraction", "complete", f"Extracted {len(extraction_data)} fields")
        else:
            log_stage(case_id, "extraction", "warning", f"Extractor error: {result.stderr[:500]}")

        update_case_field(case_id, extraction_result=json.dumps(extraction_data), pipeline_stage="researching")

        # STAGE 2: RESEARCH AGENT
        log_stage(case_id, "research", "running", "Running 5-source research...")

        research_data = {}
        try:
            resp = httpx.post(RESEARCH_URL, json=research_payload, timeout=120.0)
            if resp.status_code == 200:
                research_data = resp.json()
                log_stage(case_id, "research", "complete",
                          f"Risk score: {research_data.get('risk_score', 'N/A')}")
            else:
                log_stage(case_id, "research", "warning", f"Research agent returned {resp.status_code}")
        except Exception as e:
            log_stage(case_id, "research", "warning", f"Research agent unavailable: {str(e)[:200]}")

        update_case_field(case_id, research_result=json.dumps(research_data), pipeline_stage="generating_cam")

        # STAGE 3: PILLAR 3 — CAM ENGINE
        log_stage(case_id, "cam_generation", "running", "Running Pillar 3 CAM engine (scoring + narratives + DOCX)...")
        try:
            # Add cam_engine to path so sub-modules resolve correctly
            cam_engine_path = str(CAM_ENGINE_DIR)
            if cam_engine_path not in sys.path:
                sys.path.insert(0, cam_engine_path)

            from main import generate_cam  # cam_engine/main.py
            case_output_dir = str(CAM_OUTPUT_DIR / case_id)

            cam = generate_cam(
                case_id    = case_id,
                extraction = extraction_data,
                research   = research_data,
                req        = research_payload,
                output_dir = case_output_dir,
            )

            update_case_field(
                case_id,
                cam_json      = json.dumps(cam),
                cam_docx_path = cam.get("docx_path"),
                cam_pdf_path  = cam.get("pdf_path"),
                pipeline_stage= "complete",
                status        = "cam_ready",
            )
            log_stage(case_id, "cam_generation", "complete",
                      f"CAM generated. Decision: {cam.get('decision')} | "
                      f"Score: {cam.get('composite_score')}/100 | "
                      f"Amount: {cam.get('recommended_amount_inr',0)/1e7:.1f} Cr")
        except Exception as cam_err:
            # Graceful degradation — run old basic CAM if engine fails
            log_stage(case_id, "cam_generation", "warning",
                      f"CAM engine error: {str(cam_err)[:300]}. Falling back to basic CAM.")
            cam = build_cam(case_id, extraction_data, research_data, research_payload)
            update_case_field(
                case_id,
                cam_json      = json.dumps(cam),
                pipeline_stage= "complete",
                status        = "cam_ready",
            )
            log_stage(case_id, "cam_generation", "complete", f"Basic CAM. Decision: {cam.get('decision')}")

    except subprocess.TimeoutExpired:
        update_case_field(case_id, pipeline_stage="error", status="error")
        log_stage(case_id, "pipeline", "error", "Pipeline timed out after 300s")
    except Exception as e:
        update_case_field(case_id, pipeline_stage="error", status="error")
        log_stage(case_id, "pipeline", "error", str(e))


def build_cam(case_id: str, extraction: dict, research: dict, req: dict) -> dict:
    """
    Builds the CAM JSON from extractor + research outputs.
    Decision logic based on risk flags + research score.
    """
    # Get basic extraction fields
    profile   = extraction.get("company_profile", {})
    rec       = extraction.get("credit_recommendation", {})
    risk_f    = extraction.get("risk_flags", {})
    inc_stmt  = extraction.get("income_statement", {})
    credit_m  = extraction.get("credit_metrics", {})
    bal_sheet = extraction.get("balance_sheet", {})

    company_name = req.get("company_name", profile.get("legal_name", {})
        if isinstance(profile.get("legal_name"), dict)
        else profile.get("legal_name", "Unknown Company"))
    if isinstance(company_name, dict):
        company_name = company_name.get("value", "Unknown Company")

    loan_amount = float(req.get("loan", {}).get("amount_inr", 0) or 0)

    # Research-based risk score
    r_score      = research.get("risk_score", 70)
    r_band       = research.get("risk_band", "MEDIUM")
    r_flags      = research.get("flags", [])
    r_tags       = research.get("tags", [])

    # Extraction-based flags
    e_critical   = risk_f.get("CRITICAL", 0)
    e_high       = risk_f.get("HIGH", 0)
    e_medium     = risk_f.get("MEDIUM", 0)
    all_e_flags  = risk_f.get("flags", [])

    # Combined decision
    if e_critical > 0 or r_band == "REJECT":
        decision    = "REJECTED"
        d_color     = "RED"
        rec_limit   = 0
    elif e_high >= 3 or r_band in ("HIGH_RISK",):
        decision    = "REFER TO CREDIT COMMITTEE"
        d_color     = "BLACK"
        rec_limit   = int(loan_amount * 0.5)
    elif e_high >= 1 or r_band == "MEDIUM":
        decision    = "CONDITIONAL APPROVAL"
        d_color     = "AMBER"
        rec_limit   = int(loan_amount * 0.75)
    else:
        decision    = "APPROVED"
        d_color     = "GREEN"
        rec_limit   = int(loan_amount)

    # Composite score (blend extraction flags + research score)
    flag_penalty = (e_critical * 25) + (e_high * 10) + (e_medium * 3)
    composite    = max(0, min(100, r_score - flag_penalty))

    # Interest rate derivation
    base_rate  = 9.50
    rate_items = [{"label": "Base Rate (MCLR + spread)", "rate": base_rate, "is_base": True}]
    if e_high >= 1:
        rate_items.append({"label": "HIGH severity flags premium", "rate": 0.50})
    if e_critical >= 1:
        rate_items.append({"label": "CRITICAL flag override", "rate": 1.50})
    if r_score < 50:
        rate_items.append({"label": "Research risk premium", "rate": 0.75})
    elif r_score < 70:
        rate_items.append({"label": "Moderate research risk", "rate": 0.25})
    total_rate = sum(r["rate"] for r in rate_items)

    # Five Cs scores
    dscr_val = _safe_num(credit_m.get("dscr"))
    capacity_score = min(100, int(dscr_val * 40)) if dscr_val else max(20, 100 - flag_penalty * 2)
    five_cs = [
        {"name": "Character",   "score": max(20, 100 - e_critical * 30 - e_high * 10), "max": 100},
        {"name": "Capacity",    "score": max(20, capacity_score),                       "max": 100},
        {"name": "Capital",     "score": max(20, r_score - flag_penalty // 2),          "max": 100},
        {"name": "Collateral",  "score": max(20, 80 - e_high * 8),                      "max": 100},
        {"name": "Conditions",  "score": max(20, 90 - e_medium * 5),                    "max": 100},
    ]
    for c in five_cs:
        c["color"] = "green" if c["score"] >= 75 else ("amber" if c["score"] >= 50 else "red")

    # Risk flags for CAM
    cam_flags = []
    # From research
    for f in r_flags:
        cam_flags.append({
            "level":   f.get("severity", "MEDIUM").upper(),
            "message": f.get("message", str(f)),
            "source":  "Research Agent",
        })
    # From extraction
    for f in all_e_flags:
        cam_flags.append({
            "level":   f.get("severity", "MEDIUM").upper(),
            "message": f.get("flag", str(f)),
            "source":  "Document Analysis",
        })

    # Group flags by level
    flag_groups = {}
    for f in cam_flags:
        lvl = f["level"]
        flag_groups.setdefault(lvl, [])
        flag_groups[lvl].append(f["message"])

    # Positive signals from research
    positives = []
    for tag in r_tags:
        if isinstance(tag, str) and any(k in tag.lower() for k in ["clean", "active", "good", "pass"]):
            positives.append(tag)
    if not cam_flags:
        positives.append("No adverse flags detected across all checks")

    risk_flag_sections = []
    for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        risk_flag_sections.append({
            "level": level,
            "flags": flag_groups.get(level, []),
        })
    risk_flag_sections.append({
        "level": "POSITIVE",
        "flags": positives,
    })

    # Decision summary
    summary_parts = []
    if decision == "CONDITIONAL APPROVAL":
        summary_parts.append(
            f"Recommended for conditional approval at ₹{rec_limit/10000000:.1f} Cr "
            f"(vs requested ₹{loan_amount/10000000:.1f} Cr). "
        )
    elif decision == "REJECTED":
        summary_parts.append(
            f"Application rejected due to {e_critical} CRITICAL flag(s) detected during analysis. "
        )
    elif decision == "APPROVED":
        summary_parts.append(
            f"Application approved at full requested amount ₹{rec_limit/10000000:.1f} Cr. "
        )
    else:
        summary_parts.append(
            f"Case referred to credit committee due to elevated risk profile. "
        )
    summary_parts.append(
        f"Composite risk score: {composite}/100 ({d_color}). "
        f"Research agent risk band: {r_band}. "
    )
    if e_high > 0:
        summary_parts.append(f"{e_high} HIGH severity flag(s) noted from document analysis. ")
    if positives:
        summary_parts.append("Positive factors include: " + "; ".join(positives[:3]) + ".")

    return {
        "case_id":            case_id,
        "company_name":       company_name,
        "generated_at":       datetime.now().strftime("%d %b %Y, %H:%M"),
        "prepared_by":        "Intelli-Credit AI Engine v2.0",
        "decision":           decision,
        "decision_color":     d_color,
        "recommended_limit":  rec_limit,
        "requested_limit":    int(loan_amount),
        "interest_rate":      round(total_rate, 2),
        "tenor":              int(req.get("loan", {}).get("tenor", 36) or 36),
        "composite_score":    composite,
        "decision_summary":   " ".join(summary_parts),
        "five_c_scores":      five_cs,
        "risk_flags":         risk_flag_sections,
        "rate_derivation":    rate_items,
        "research_risk_band": r_band,
        "research_risk_score":r_score,
        "extraction_flags":   len(all_e_flags),
        "research_flags":     len(r_flags),
        "tags":               r_tags,
    }


def _safe_num(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, dict):
        return float(val.get("value", 0) or 0)
    try:
        return float(val)
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════

# ── Health ────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "time": datetime.now().isoformat()}


# ── Auth ────────────────────────────────────────

@app.post("/auth/register", status_code=201)
async def register(req: SignupRequest):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email=?", (req.email.lower(),)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="Email already registered")

    if req.role not in ("credit_manager", "senior_approver"):
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid role")

    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        (user_id, req.name, req.email.lower(), hash_pw(req.password),
         req.role, req.branch, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    token = create_token(user_id, req.email.lower(), req.role, req.name)
    return {
        "message":      "Account created successfully",
        "access_token": token,
        "role":         req.role,
        "name":         req.name,
        "user_id":      user_id,
    }


@app.post("/auth/login")
async def login(req: LoginRequest):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (req.email.lower(),)).fetchone()
    conn.close()

    if not user or user["password_hash"] != hash_pw(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user["id"], user["email"], user["role"], user["name"])
    return {
        "access_token": token,
        "role":         user["role"],
        "name":         user["name"],
        "user_id":      user["id"],
        "branch":       user["branch"],
    }


@app.get("/auth/me")
async def me(user=Depends(get_current_user)):
    conn = get_db()
    u = conn.execute("SELECT id,name,email,role,branch,created_at FROM users WHERE id=?",
                     (user["sub"],)).fetchone()
    conn.close()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(u)


# ── Cases ──────────────────────────────────────

@app.get("/cases")
async def list_cases(
    status_filter: Optional[str] = None,
    user=Depends(get_current_user),
):
    conn = get_db()
    if user["role"] == "senior_approver":
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM cases WHERE status=? ORDER BY created_at DESC",
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cases WHERE status IN ('pending_approval','cam_ready','approved','rejected') ORDER BY created_at DESC"
            ).fetchall()
    else:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM cases WHERE created_by=? AND status=? ORDER BY created_at DESC",
                (user["sub"], status_filter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cases WHERE created_by=? ORDER BY created_at DESC",
                (user["sub"],),
            ).fetchall()
    conn.close()
    return [_format_case(dict(r)) for r in rows]


@app.post("/cases", status_code=201)
async def create_case(req: CaseCreateRequest, user=Depends(require_manager)):
    case_id  = f"CASE_{datetime.now().strftime('%Y')}_{str(uuid.uuid4())[:6].upper()}"
    now      = datetime.now().isoformat()
    company  = req.company
    loan     = req.loan

    conn = get_db()
    conn.execute(
        """INSERT INTO cases
           (id,company_name,cin,gstin,pan,industry,constitution,address,
            loan_amount,loan_type,tenor,purpose,promoters_json,loan_json,
            status,pipeline_stage,created_by,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            case_id,
            company.get("legalName", "Unknown"),
            company.get("cin", ""),
            company.get("gstin", ""),
            company.get("pan", ""),
            company.get("industry", ""),
            company.get("constitution", ""),
            f"{company.get('address','')} {company.get('city','')} {company.get('state','')}".strip(),
            float(loan.get("amount", 0) or 0),
            loan.get("loanType", ""),
            int(loan.get("tenor", 36) or 36),
            loan.get("purpose", ""),
            json.dumps(req.promoters),
            json.dumps(loan),
            "draft",
            "created",
            user["sub"],
            now, now,
        ),
    )
    conn.commit()
    conn.close()
    return {"case_id": case_id, "status": "draft"}


@app.get("/cases/{case_id}")
async def get_case(case_id: str, user=Depends(get_current_user)):
    conn = get_db()
    row  = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return _format_case(dict(row))


@app.post("/cases/{case_id}/upload")
async def upload_documents(
    case_id: str,
    files: List[UploadFile] = File(...),
    user=Depends(require_manager),
):
    conn = get_db()
    row  = conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    upload_folder = UPLOADS_DIR / case_id
    upload_folder.mkdir(exist_ok=True)

    saved = []
    for f in files:
        dest = upload_folder / f.filename
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(f.filename)

    update_case_field(case_id, status="uploaded", pipeline_stage="uploaded")
    return {"uploaded": saved, "count": len(saved)}


@app.post("/cases/{case_id}/start")
async def start_pipeline(
    case_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(require_manager),
):
    conn = get_db()
    row  = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    row = dict(row)
    upload_folder = str(UPLOADS_DIR / case_id)

    # Build research payload
    promoters = json.loads(row.get("promoters_json") or "[]")
    qualitative = json.loads(row.get("qualitative_json") or "{}")

    research_payload = {
        "case_id":           case_id,
        "company_name":      row["company_name"],
        "cin":               row.get("cin") or f"U{str(uuid.uuid4())[:17].upper()}",
        "gstin":             row.get("gstin") or f"27AAACS{str(uuid.uuid4())[:7].upper()}Z5",
        "pan":               row.get("pan") or f"AAAC{str(uuid.uuid4())[:5].upper()}A",
        "promoters":         [
            {
                "name": p.get("fullName", "Unknown"),
                "pan":  p.get("pan", "AAAAA0000A"),
                "din":  p.get("din", "00000000"),
            }
            for p in (promoters if isinstance(promoters, list) else [])
        ] or [{"name": "Director", "pan": "AAAAA0000A", "din": "00000000"}],
        "loan": {
            "amount_inr":  row.get("loan_amount", 0),
            "type":        row.get("loan_type", "Working Capital"),
            "tenor_months":row.get("tenor", 36),
            "purpose":     row.get("purpose", ""),
        },
        "ingestion_version": "2.0.0",
        "qualitative":       qualitative,   # primary insight fields from credit officer
    }

    update_case_field(case_id, status="processing", pipeline_stage="starting")
    log_stage(case_id, "pipeline", "running", "Pipeline started")

    background_tasks.add_task(
        run_pipeline_bg, case_id, upload_folder, row["company_name"], research_payload
    )
    return {"message": "Pipeline started", "case_id": case_id}


@app.get("/cases/{case_id}/status")
async def pipeline_status(case_id: str, user=Depends(get_current_user)):
    conn = get_db()
    row  = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    logs = conn.execute(
        "SELECT stage,status,message,ts FROM pipeline_logs WHERE case_id=? ORDER BY ts",
        (case_id,),
    ).fetchall()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    row = dict(row)
    stage_map = {
        "created":        0, "uploaded": 1, "starting": 2,
        "extracting":     3, "researching": 4, "generating_cam": 5,
        "complete":       6, "error": -1,
    }

    pipeline_stage = row.get("pipeline_stage", "created")
    current_step   = stage_map.get(pipeline_stage, 0)

    stages = [
        {"id": "upload",      "label": "Documents Uploaded",       "detail": "All files received & stored"},
        {"id": "entity",      "label": "Entity Profile Built",      "detail": f"Company: {row['company_name']}"},
        {"id": "extraction",  "label": "Document Parsing",          "detail": "Extracting financials via AI OCR"},
        {"id": "research",    "label": "Secondary Research",        "detail": "MCA · eCourts · RBI · News · GSTN"},
        {"id": "cam",         "label": "CAM Generation",            "detail": "Compiling Credit Appraisal Memorandum"},
        {"id": "complete",    "label": "Pipeline Complete",         "detail": "CAM ready for review"},
    ]

    for i, s in enumerate(stages):
        if i < current_step:
            s["status"] = "complete"
        elif i == current_step:
            s["status"] = "running" if pipeline_stage not in ("complete", "error") else "complete"
        else:
            s["status"] = "waiting"

    if pipeline_stage == "error":
        stages[current_step if current_step >= 0 else 0]["status"] = "error"

    return {
        "case_id":       case_id,
        "status":        row["status"],
        "pipeline_stage":pipeline_stage,
        "stages":        stages,
        "logs":         [dict(l) for l in logs[-10:]],
        "is_complete":  row["status"] == "cam_ready",
    }


@app.get("/cases/{case_id}/cam")
async def get_cam(case_id: str, user=Depends(get_current_user)):
    conn = get_db()
    row  = conn.execute("SELECT cam_json, status FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    if not row["cam_json"]:
        raise HTTPException(status_code=404, detail="CAM not yet generated")

    return json.loads(row["cam_json"])


def generate_cam_documents(case_id: str, cam_data: dict, company_name: str):
    """
    Build DOCX + PDF from an existing cam_data dict.
    Used to regenerate files for cases where docx/pdf paths are missing.
    Returns (docx_path, pdf_path).
    """
    cam_engine_path = str(CAM_ENGINE_DIR)
    if cam_engine_path not in sys.path:
        sys.path.insert(0, cam_engine_path)

    from document.builder import CAMBuilder
    from document.pdf_converter import convert_to_pdf

    case_output_dir = CAM_OUTPUT_DIR / case_id
    case_output_dir.mkdir(parents=True, exist_ok=True)

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    docx_path = str(case_output_dir / f"CAM_{case_id}_{ts}.docx")

    builder = CAMBuilder()
    doc     = builder.build(cam_data)
    doc.save(docx_path)

    pdf_path   = docx_path.replace(".docx", ".pdf")
    pdf_result = convert_to_pdf(docx_path, pdf_path)
    final_pdf  = pdf_result if (pdf_result and Path(pdf_result).exists()) else docx_path

    return docx_path, final_pdf


@app.get("/cases/{case_id}/cam/download")
async def download_cam(
    case_id: str,
    fmt: str = "pdf",
    user=Depends(get_current_user),
):
    """
    Download the generated CAM document as PDF or DOCX.
    ?fmt=pdf  (default) or ?fmt=docx
    """
    conn = get_db()
    row  = conn.execute(
        "SELECT cam_docx_path, cam_pdf_path, company_name, cam_json FROM cases WHERE id=?",
        (case_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    file_path = None
    media_type = None
    suffix = None

    if fmt == "docx":
        file_path = row["cam_docx_path"]
        media_type= "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        suffix    = ".docx"
    else: # default to pdf
        file_path = row["cam_pdf_path"]
        media_type= "application/pdf"
        suffix    = ".pdf"

    # Check if file exists, if not, try to regenerate
    if not file_path or not Path(file_path).exists():
        if not row["cam_json"]:
            raise HTTPException(
                status_code=404,
                detail=f"CAM {fmt.upper()} file not found and CAM JSON is missing. Run the pipeline first."
            )
        
        log_stage(case_id, "cam_download", "regenerating", f"CAM {fmt.upper()} file not found, regenerating from CAM JSON.")
        
        # Regenerate CAM documents
        cam_data = json.loads(row["cam_json"])
        docx_path, pdf_path = generate_cam_documents(case_id, cam_data, row["company_name"])
        
        # Update database with new paths
        update_case_field(case_id, cam_docx_path=docx_path, cam_pdf_path=pdf_path)

        # Update row with new paths for immediate use
        row = dict(row) # Convert to dict to allow modification
        row["cam_docx_path"] = docx_path
        row["cam_pdf_path"] = pdf_path

        # Re-evaluate file_path based on regenerated paths
        if fmt == "docx":
            file_path = row["cam_docx_path"]
        else:
            file_path = row["cam_pdf_path"]

        if not file_path or not Path(file_path).exists():
            raise HTTPException(
                status_code=500,
                detail=f"Failed to regenerate CAM {fmt.upper()} file."
            )

    filename = f"CAM_{case_id}_{row['company_name'].replace(' ','_')[:30]}{suffix}"
    return FileResponse(
        path       = file_path,
        media_type = media_type,
        filename   = filename,
    )


@app.patch("/cases/{case_id}/primary-insight")
async def save_primary_insight(
    case_id: str,
    req: PrimaryInsightRequest,
    user=Depends(require_manager),
):
    """
    Save credit officer primary insight / field observations for a case.
    These directly adjust the composite credit score (+/- up to 15 pts).
    Must be saved BEFORE calling /cases/{case_id}/start.
    """
    conn = get_db()
    row  = conn.execute("SELECT id, qualitative_json FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    # Merge with existing qualitative data (if any)
    existing = {}
    if row["qualitative_json"]:
        try:
            existing = json.loads(row["qualitative_json"])
        except Exception:
            pass

    # Apply only provided (non-None) fields
    update = req.model_dump(exclude_none=True)
    merged = {**existing, **update}

    update_case_field(case_id, qualitative_json=json.dumps(merged))
    log_stage(case_id, "primary_insight", "saved",
              f"Credit officer field observations saved: {list(update.keys())}")

    return {
        "message":    "Primary insight saved successfully",
        "fields_saved": list(update.keys()),
        "qualitative": merged,
    }


@app.get("/cases/{case_id}/primary-insight")
async def get_primary_insight(case_id: str, user=Depends(get_current_user)):
    """Retrieve the saved primary insight fields for a case."""
    conn = get_db()
    row  = conn.execute("SELECT qualitative_json FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    qualitative = {}
    if row["qualitative_json"]:
        try:
            qualitative = json.loads(row["qualitative_json"])
        except Exception:
            pass

    return {"qualitative": qualitative, "has_field_data": bool(qualitative)}


@app.post("/cases/{case_id}/send-to-approver")
async def send_to_approver(case_id: str, user=Depends(require_manager)):
    conn = get_db()
    row  = conn.execute("SELECT status FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    if row["status"] != "cam_ready":
        raise HTTPException(status_code=400, detail="CAM not ready yet")

    update_case_field(case_id, status="pending_approval")
    log_stage(case_id, "approval", "pending", "Sent to Senior Approver queue")
    return {"message": "Case sent to approver queue"}


@app.post("/cases/{case_id}/review")
async def submit_review(case_id: str, req: ReviewRequest, user=Depends(require_approver)):
    conn = get_db()
    row  = conn.execute("SELECT status FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    new_status = {
        "approve":          "approved",
        "approve_modified": "approved",
        "reject":           "rejected",
        "send_back":        "cam_ready",
    }.get(req.decision, "pending_approval")

    update_case_field(
        case_id,
        status=new_status,
        approver_decision=req.decision,
        approver_comments=req.comments,
        assigned_to_approver=user["sub"],
    )
    log_stage(case_id, "approval", req.decision,
              f"Approver decision: {req.decision}. Comments: {req.comments[:100]}")
    return {"message": "Review submitted", "new_status": new_status}


# ── Helpers ───────────────────────────────────────────────────

def _format_case(row: dict) -> dict:
    cam = {}
    if row.get("cam_json"):
        try:
            cam = json.loads(row["cam_json"])
        except Exception:
            pass
    # Support both old (recommended_limit) and new (recommended_amount_inr) cam_json schemas
    rec_limit = cam.get("recommended_limit") or cam.get("recommended_amount_inr")
    risk_color= cam.get("decision_color") or cam.get("risk_band", "AMBER")
    has_doc   = bool(row.get("cam_pdf_path") or row.get("cam_docx_path"))

    return {
        "id":              row["id"],
        "company_name":    row["company_name"],
        "status":          row["status"],
        "pipeline_stage":  row.get("pipeline_stage", "created"),
        "risk_color":      risk_color,
        "risk_band":       cam.get("risk_band", "AMBER"),
        "decision":        cam.get("decision"),
        "loan_amount":     row.get("loan_amount"),
        "loan_type":       row.get("loan_type"),
        "industry":        row.get("industry"),
        "recommended_limit":  rec_limit,
        "composite_score":    cam.get("composite_score"),
        "interest_rate":      cam.get("interest_rate"),
        "has_cam_document":   has_doc,
        "created_at":         row.get("created_at"),
        "updated_at":         row.get("updated_at"),
        "created_by":         row.get("created_by"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
