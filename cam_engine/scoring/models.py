"""
cam_engine/scoring/models.py
============================
Pydantic models for all scoring-related data structures.
Every number produced by the scoring engine is wrapped here
so it can be serialised to JSON and traced in the CAM document.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    """One atomic scoring event — one line in the explainability table."""
    label:      str             # e.g. "DSCR 1.84x → 30 pts (good)"
    points:     int             # actual points awarded (can be negative)
    max_points: int             # maximum possible for this sub-dimension
    benchmark:  str             # e.g. "Benchmark: DSCR >= 2.0x for 40 pts"


class DimensionScore(BaseModel):
    """One of the 8 scoring dimensions."""
    name:      str              # "Capacity", "Capital", etc.
    score:     int              # 0–100 normalised
    weight:    float            # weight in composite (0.0–1.0)
    weighted:  float            # score × weight (contribution to composite)
    breakdown: List[ScoreBreakdown] = []
    color:     str = "AMBER"    # GREEN | AMBER | RED


class FinancialScores(BaseModel):
    """Output of financial_scorer.py — 4 financial dimensions."""
    capacity:   DimensionScore
    capital:    DimensionScore
    collateral: DimensionScore
    gst_quality: DimensionScore


class ResearchScores(BaseModel):
    """Scores derived from the research agent output."""
    character:       DimensionScore   # promoter integrity
    conditions:      DimensionScore   # sector outlook
    litigation_risk: DimensionScore   # eCourts risk
    mca_compliance:  DimensionScore   # ROC filing compliance


class CompositeResult(BaseModel):
    """Final output of composite_scorer.py — the single number that drives the decision."""
    composite_score:       int            # 0–100
    risk_band:             str            # GREEN | AMBER | RED | BLACK
    decision:              str            # APPROVE | CONDITIONAL | REJECT
    auto_reject:           bool = False
    rejection_reason:      Optional[str] = None

    dimension_scores:      List[DimensionScore] = []
    financial_scores:      FinancialScores
    research_scores:       ResearchScores

    # Pre-formatted explainability paragraph (pasted verbatim into the CAM)
    explainability_text:   str = ""

    # Research flags forwarded for use by later components
    research_flags:        List[dict] = []
    research_tags:         List[str]  = []

    # Primary Insight (qualitative) adjustment — from field observations
    qualitative_adjustment:      int       = 0    # +/- point delta applied to composite
    qualitative_explanations:    List[str] = []   # humanreadable explanation per field

    # Cross-pillar contradiction analysis
    cross_pillar_contradictions: List[str] = []   # natural language sentences


def score_to_color(score: int) -> str:
    if score >= 70:  return "GREEN"
    if score >= 50:  return "AMBER"
    if score >= 30:  return "RED"
    return "BLACK"
