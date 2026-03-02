"""
core/output_contract.py
=======================
All output-side Pydantic models and enumerations.
ResearchFlag, Severity, FlagCategory, DataSource are imported
by sources/all_sources.py — do NOT rename them.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # Auto-reject territory
    HIGH     = "HIGH"       # Strong concern; needs escalation
    MEDIUM   = "MEDIUM"     # Moderate risk; needs explanation
    LOW      = "LOW"        # Minor observation
    INFO     = "INFO"       # Positive / neutral finding


class FlagCategory(str, Enum):
    FRAUD      = "FRAUD"        # Fraud / wilful default
    FINANCIAL  = "FINANCIAL"    # Debt capacity, charges, NPA
    LITIGATION = "LITIGATION"   # Court cases
    REGULATORY = "REGULATORY"   # Compliance gaps (ROC, GST)
    PROMOTER   = "PROMOTER"     # Promoter track-record issues
    SECTOR     = "SECTOR"       # Industry-level risk


class DataSource(str, Enum):
    RBI      = "RBI"        # RBI Wilful Defaulter List
    MCA      = "MCA"        # MCA21 Company Registry
    ECOURTS  = "ECOURTS"    # eCourts.gov.in
    NEWS     = "NEWS"       # Tavily AI news search
    GSTN     = "GSTN"       # GSTIN portal
    INTERNAL = "INTERNAL"   # System-generated


class RiskBand(str, Enum):
    GREEN  = "GREEN"    # Score >= 70 — Proceed
    AMBER  = "AMBER"    # Score 40–69 — Proceed with conditions
    RED    = "RED"      # Score 1–39 — High risk; escalate
    BLACK  = "BLACK"    # Score <= 0 — Auto-reject


# ─────────────────────────────────────────────────────────────
# Core Flag Model
# ─────────────────────────────────────────────────────────────

class ResearchFlag(BaseModel):
    """A single risk signal raised by any of the 5 sources."""

    flag_id:   str = Field(default_factory=lambda: f"FLAG_{uuid4().hex[:8].upper()}")
    severity:  Severity
    category:  FlagCategory
    source:    DataSource

    title:       str
    description: str
    evidence:    Optional[str]  = None
    source_url:  Optional[str]  = None

    # For litigation flags
    case_number: Optional[str]  = None
    court:       Optional[str]  = None
    case_status: Optional[str]  = None

    # Scoring
    score_impact:         int   = 0       # negative = bad
    confidence:           float = 1.0     # 0.0 – 1.0
    requires_verification: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# Aggregated Output (what the API returns)
# ─────────────────────────────────────────────────────────────

class SourceResult(BaseModel):
    """Result from a single data source."""
    source:   DataSource
    flags:    List[ResearchFlag] = []
    findings: List[dict]         = []
    raw_data: dict               = {}
    error:    Optional[str]      = None
    duration_ms: float           = 0.0


class ResearchOutput(BaseModel):
    """Full research output returned by the orchestrator / API."""

    case_id:      str
    company_name: str
    cin:          str
    gstin:        str

    # Scoring
    risk_score:  int      # 0 – 100
    risk_band:   RiskBand
    auto_reject: bool     # True if any CRITICAL flag with score_impact <= -100

    # Aggregated flags (all sources merged)
    flags:       List[ResearchFlag]
    findings:    List[dict]

    # Per-source breakdown
    source_results: List[SourceResult]

    # Tags (added by processing/tagger.py)
    tags: List[str] = []

    # Timestamps
    started_at:   datetime
    completed_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()

    def critical_flags(self) -> List[ResearchFlag]:
        return [f for f in self.flags if f.severity == Severity.CRITICAL]

    def flag_count_by_severity(self) -> dict:
        counts: dict = {s.value: 0 for s in Severity}
        for f in self.flags:
            counts[f.severity.value] += 1
        return counts
