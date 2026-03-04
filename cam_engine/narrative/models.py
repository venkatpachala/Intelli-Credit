"""
cam_engine/narrative/models.py
================================
Pydantic models for the narrative generator.
NarrativeInput = everything Claude needs.
CAMNarratives  = everything Claude produces.
"""

from __future__ import annotations

from typing import List, Optional, Any, Dict
from pydantic import BaseModel


class CAMNarratives(BaseModel):
    """All LLM-generated sections of the CAM."""
    executive_summary: str = ""
    character:         str = ""
    capacity:          str = ""
    capital:           str = ""
    collateral:        str = ""
    conditions:        str = ""
    risk_mitigants:    str = ""
    decision_rationale:str = ""   # cross-pillar AI-written decision explanation

    # track which sections had errors
    errors: Dict[str, str] = {}


class NarrativeInput(BaseModel):
    """Fully hydrated input bundle passed to the narrative generator."""

    # Identity
    case_id:      str
    company_name: str
    cin:          str
    industry:     str
    loan_type:    str
    tenor_months: int
    requested_cr: float
    recommended_cr: float

    # Promoters
    promoters: List[Dict[str, Any]] = []

    # Decision
    decision:        str
    risk_band:       str
    composite_score: int
    interest_rate:   float

    # Dimension scores (for per-section headers)
    character_score:  int
    capacity_score:   int
    capital_score:    int
    collateral_score: int
    conditions_score: int

    # Score breakdowns (for explainability tables)
    capacity_breakdown:  List[Dict[str, Any]] = []
    capital_breakdown:   List[Dict[str, Any]] = []
    collateral_breakdown:List[Dict[str, Any]] = []

    # Financial data (3-year trend)
    revenue:  List[float] = []    # FY1, FY2, FY3
    ebitda:   List[float] = []
    pat:      List[float] = []
    cfo:      List[float] = []
    periods:  List[str]   = []    # ["FY2023", "FY2024", "FY2025"]
    rev_cagr: float = 0.0
    ebitda_margin_latest: float = 0.0

    # Key ratios
    dscr:     float = 0.0
    icr:      float = 0.0
    de_ratio: float = 0.0
    net_worth_cr:      float = 0.0
    total_debt_cr:     float = 0.0
    tangible_nw_cr:    float = 0.0
    total_assets_cr:   float = 0.0
    promoter_shareholding: float = 0.0

    # Collateral
    collateral_assets:   List[Dict[str, Any]] = []
    total_market_cr:     float = 0.0
    total_distress_cr:   float = 0.0
    coverage_market:     float = 0.0
    coverage_distress:   float = 0.0

    # Research agent outputs
    research_flags:   List[Dict[str, Any]] = []
    research_tags:    List[str]  = []
    rbi_result:       str = "Not flagged"
    litigation_count: int = 0
    mca_flag_count:   int = 0
    news_signals:     List[str] = []
    sector_score:     int = 70

    # Rate derivation (for Executive Summary)
    rate_base:    float = 9.50
    rate_premiums: List[Dict[str, Any]] = []

    # Amount derivation (for Executive Summary)
    amount_adjustments: List[Dict[str, Any]] = []

    # Conditions precedent and covenants (for risk section)
    conditions_precedent: List[str] = []
    covenants:            List[str] = []

    # Repo rate context
    repo_rate: float = 6.50

    # ── Primary Insight (Qualitative) Fields ──────────────────
    qualitative_adjustment:      int       = 0
    qualitative_explanations:    list      = []
    cross_pillar_contradictions: list      = []  # natural language contradiction sentences
    factory_capacity_pct:        float     = -1.0   # -1 = not entered
    management_quality:          int       = 0       # 0 = not entered, 1-5
    site_condition:              str       = ""      # excellent/good/average/poor/critical
    key_person_risk:             bool      = False
    supply_chain_risk:           bool      = False
    cibil_commercial_score:      float     = -1.0   # -1 = not entered
    primary_insight_notes:       str       = ""     # free text from credit officer
