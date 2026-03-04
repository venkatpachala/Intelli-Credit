"""
cam_engine/scoring/composite_scorer.py
========================================
Merges the 4 financial dimension scores + 4 research dimension scores
into one weighted composite, applies Primary Insight (field observations)
adjustment, then maps it to a risk band and decision.

Weights:
  Character       20%   (research agent — promoter integrity)
  Capacity        25%   (financial — DSCR, ICR, CFO)
  Capital         20%   (financial — NW, D/E, Tangible NW)
  Collateral      15%   (financial — coverage, charge, distress)
  Conditions      10%   (research agent — sector outlook)
  GST Quality      5%   (financial — filing compliance, reconciliation)
  Litigation Risk  3%   (research agent — eCourts)
  MCA Compliance   2%   (research agent — ROC filings)
  ─────────────────────
  Total          100%

PRIMARY INSIGHT (Qualitative) Adjustment — applied AFTER weighted sum:
  Max ±15 pts. Based on factory capacity, management quality, site condition,
  CIBIL commercial score, key-person risk, supply-chain risk, and free-text notes.

ML NORMALISATION — sigmoid function applied to weighted sum (logistic regression style).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .models import (
    CompositeResult,
    DimensionScore,
    FinancialScores,
    ResearchScores,
    score_to_color,
)


DECISION_MAP = {
    "GREEN":  "APPROVE",
    "AMBER":  "CONDITIONAL APPROVAL",
    "RED":    "REFER TO CREDIT COMMITTEE",
    "BLACK":  "REJECT",
}


# ─────────────────────────────────────────────────────────────
# Qualitative adjustment engine
# ─────────────────────────────────────────────────────────────

def _apply_qualitative_adjustments(
    qualitative: Dict,
) -> Tuple[int, List[str]]:
    """
    Parse primary insight fields and compute total score adjustment.
    Returns (total_adjustment, list_of_explanation_lines).
    Total capped at ±15 pts.
    """
    total = 0
    explanations: List[str] = []

    if not qualitative:
        return 0, []

    # factory_capacity_pct  (0–100%)
    cap_pct = qualitative.get("factory_capacity_pct")
    if cap_pct is not None:
        try:
            cap_pct = float(cap_pct)
            if cap_pct >= 80:
                total += 8
                explanations.append(f"  [PRIMARY INSIGHT] Factory operating at high capacity ({cap_pct:.0f}%) → +8 pts")
            elif cap_pct >= 60:
                total += 4
                explanations.append(f"  [PRIMARY INSIGHT] Factory operating at moderate capacity ({cap_pct:.0f}%) → +4 pts")
            elif cap_pct >= 40:
                total -= 5
                explanations.append(f"  [PRIMARY INSIGHT] Factory operating at low capacity ({cap_pct:.0f}%) → -5 pts")
            else:
                total -= 12
                explanations.append(f"  [PRIMARY INSIGHT] Factory critically under-utilised ({cap_pct:.0f}%) → -12 pts")
        except (TypeError, ValueError):
            pass

    # management_quality: 1–5 (5=excellent)
    mgmt = qualitative.get("management_quality")
    if mgmt is not None:
        try:
            mgmt = int(float(mgmt))
            mgmt_map = {5: (+7, "Excellent"), 4: (+4, "Good"), 3: (0, "Average"),
                         2: (-6, "Below Average"), 1: (-12, "Poor")}
            delta, label = mgmt_map.get(mgmt, (0, "Unknown"))
            if delta != 0:
                total += delta
                explanations.append(
                    f"  [PRIMARY INSIGHT] Management quality — {label} ({mgmt}/5) → {'+' if delta > 0 else ''}{delta} pts"
                )
        except (TypeError, ValueError):
            pass

    # site_condition: 'excellent'|'good'|'average'|'poor'|'critical'
    site = str(qualitative.get("site_condition", "")).lower().strip()
    site_map = {
        "excellent": (+5, "Excellent"),
        "good": (+3, "Good"),
        "average": (0, "Average"),
        "poor": (-5, "Poor"),
        "critical": (-10, "Critical"),
    }
    if site in site_map:
        delta, label = site_map[site]
        if delta != 0:
            total += delta
            explanations.append(
                f"  [PRIMARY INSIGHT] Site condition — {label} → {'+' if delta > 0 else ''}{delta} pts"
            )

    # key_person_risk: True/False
    kpr = qualitative.get("key_person_risk")
    if kpr is not None and bool(kpr):
        total -= 5
        explanations.append("  [PRIMARY INSIGHT] Key-person dependency risk identified → -5 pts")

    # supply_chain_risk: True/False
    scr = qualitative.get("supply_chain_risk")
    if scr is not None and bool(scr):
        total -= 4
        explanations.append("  [PRIMARY INSIGHT] Supply chain concentration risk noted → -4 pts")

    # cibil_commercial_score (300–900)
    cibil = qualitative.get("cibil_commercial_score")
    if cibil is not None:
        try:
            cibil = float(cibil)
            if cibil >= 750:
                total += 6
                explanations.append(f"  [PRIMARY INSIGHT] CIBIL Commercial Score {cibil:.0f} → +6 pts (excellent)")
            elif cibil >= 700:
                total += 3
                explanations.append(f"  [PRIMARY INSIGHT] CIBIL Commercial Score {cibil:.0f} → +3 pts (good)")
            elif cibil >= 650:
                pass  # neutral
            else:
                total -= 8
                explanations.append(f"  [PRIMARY INSIGHT] CIBIL Commercial Score {cibil:.0f} → -8 pts (poor)")
        except (TypeError, ValueError):
            pass

    # free-text notes — keyword-based simple NLP
    free_text = str(qualitative.get("notes", "") or "").lower()
    if free_text:
        positive_kws = ["growing", "expanding", "modernised", "profitable",
                        "new orders", "strong demand", "debt-free", "fully paid", "good management"]
        negative_kws = ["idle", "shut", "dispute", "bankrupt", "closure", "abandoned",
                        "diverted", "circular", "round tripping", "under investigation", "seized"]
        pos_hits = [kw for kw in positive_kws if kw in free_text]
        neg_hits = [kw for kw in negative_kws if kw in free_text]
        if pos_hits:
            delta = min(5, len(pos_hits) * 2)
            total += delta
            explanations.append(
                f"  [PRIMARY INSIGHT] Positive field observations: {', '.join(pos_hits[:2])} → +{delta} pts"
            )
        if neg_hits:
            delta = max(-8, -(len(neg_hits) * 3))
            total += delta
            explanations.append(
                f"  [PRIMARY INSIGHT] Negative field observations: {', '.join(neg_hits[:2])} → {delta} pts"
            )

    # Cap at ±15
    total = max(-15, min(15, total))
    return total, explanations


# ─────────────────────────────────────────────────────────────
# Cross-pillar contradiction detector
# ─────────────────────────────────────────────────────────────

def _detect_contradictions(
    financial:   FinancialScores,
    research_s:  ResearchScores,
    research:    Dict,
    qualitative: Dict,
) -> List[str]:
    """
    Detects cross-pillar contradictions and returns natural-language sentences
    for the CAM explainability section.
    """
    sentences: List[str] = []
    flags = research.get("flags", [])

    cap   = financial.capacity.score
    cap2  = financial.capital.score
    gst_q = financial.gst_quality.score
    coll  = financial.collateral.score
    char  = research_s.character.score
    lit   = research_s.litigation_risk.score
    research_band = research.get("risk_band", "")

    # Strong financials vs bad promoter character
    if cap >= 70 and char < 40:
        sentences.append(
            f"Despite strong financial capacity (score {cap}/100), promoter character "
            f"concerns (score {char}/100) significantly weigh on the overall credit assessment."
        )

    # Strong GST flows but research flags circular trading
    cv009_flag = next(
        (f for f in flags if "circular" in str(f.get("title", "")).lower()
         or "circular" in str(f.get("description", "")).lower()), None
    )
    if gst_q >= 65 and cv009_flag:
        sentences.append(
            f"While GST Quality score ({gst_q}/100) appears adequate, a GST vs Bank statement "
            f"mismatch flag has been raised, indicating potential circular trading — "
            f"this contradicts the stated revenue figures and warrants deeper scrutiny."
        )

    # Good collateral but high litigation risk (could encumber assets)
    lit_flags = [f for f in flags if f.get("category") == "LITIGATION"]
    if coll >= 65 and len(lit_flags) >= 2:
        sentences.append(
            f"Collateral coverage appears adequate (score {coll}/100), however "
            f"{len(lit_flags)} litigation case(s) flagged via eCourts could "
            f"challenge enforceability or encumber collateral assets in a distress scenario."
        )

    # Strong financials but rejected/referred on research grounds (problem statement example)
    if (cap >= 70 or gst_q >= 70) and research_band in ("RED", "BLACK"):
        sentences.append(
            f"Despite strong financial metrics (Capacity {cap}/100, GST Quality {gst_q}/100), "
            f"the secondary research intelligence (risk band: {research_band}) driven by "
            f"external sources (eCourts, MCA, news) results in a cautious final assessment."
        )

    # Primary insights vs financial scores
    if qualitative:
        cap_pct = qualitative.get("factory_capacity_pct")
        if cap_pct is not None:
            try:
                cap_pct_f = float(cap_pct)
                if cap_pct_f < 50 and cap >= 65:
                    sentences.append(
                        f"Field visit reveals factory operating at only {cap_pct_f:.0f}% capacity, "
                        f"which contradicts the financial capacity score ({cap}/100) derived from "
                        f"reported financials — warrants closer scrutiny of revenue projections."
                    )
                elif cap_pct_f >= 80 and cap < 50:
                    sentences.append(
                        f"Factory observed operating at high capacity ({cap_pct_f:.0f}%), "
                        f"which is a positive indicator not yet reflected in historical financials "
                        f"(Capacity score {cap}/100) — may indicate an improving trajectory."
                    )
            except (TypeError, ValueError):
                pass

    return sentences


# ─────────────────────────────────────────────────────────────
# ML sigmoid normalisation
# ─────────────────────────────────────────────────────────────

def _sigmoid_normalise(raw_score: float) -> int:
    """
    Applies a sigmoid-shaped normalisation to avoid linear cliffs at score boundaries.
    Models behaviour of a logistic regression on a 0–100 credit score scale.
    """
    x = (raw_score - 50.0) / 18.0
    sigmoid = 1.0 / (1.0 + math.exp(-x))
    # Map sigmoid [0.07, 0.93] → [0, 100]
    normalised = (sigmoid - 0.07) / (0.93 - 0.07) * 100.0
    return max(0, min(100, round(normalised)))


# ─────────────────────────────────────────────────────────────
# Main composite function
# ─────────────────────────────────────────────────────────────

def compute_composite(
    financial:   FinancialScores,
    research_s:  ResearchScores,
    research:    Dict,                   # raw research agent output
    qualitative: Optional[Dict] = None,  # primary insight / field observations
) -> CompositeResult:
    """
    Combine all 8 dimension scores + qualitative adjustment into composite score.
    Auto-reject overrides everything if any CRITICAL -100 flag exists.
    """
    qualitative = qualitative or {}
    auto_reject = research.get("auto_reject", False)
    flags       = research.get("flags", [])
    tags        = research.get("tags", [])

    # Hard auto-reject check
    rejection_reason: Optional[str] = None
    if auto_reject or any(
        f.get("severity") == "CRITICAL" and f.get("score_impact", 0) <= -100
        for f in flags
    ):
        auto_reject = True
        critical_f  = next(
            (f for f in flags if f.get("severity") == "CRITICAL"), None
        )
        rejection_reason = (critical_f.get("title", "CRITICAL flag detected")
                            if critical_f else "Auto-reject: CRITICAL risk flag")

    # Weighted sum over 8 dimensions
    dimensions: List[DimensionScore] = [
        research_s.character,       # 20%
        financial.capacity,         # 25%
        financial.capital,          # 20%
        financial.collateral,       # 15%
        research_s.conditions,      # 10%
        financial.gst_quality,      # 5%
        research_s.litigation_risk, # 3%
        research_s.mca_compliance,  # 2%
    ]

    raw_weighted = sum(d.score * d.weight for d in dimensions)

    # Apply sigmoid ML normalisation
    composite_pre_qi = _sigmoid_normalise(raw_weighted)

    # Apply Primary Insight (qualitative) adjustment
    qi_delta, qi_explanations = _apply_qualitative_adjustments(qualitative)
    composite = max(0, min(100, composite_pre_qi + qi_delta))

    # Cross-pillar contradiction analysis
    contradictions = _detect_contradictions(financial, research_s, research, qualitative)

    if auto_reject:
        composite = 0
        risk_band = "BLACK"
    elif composite >= 70:
        risk_band = "GREEN"
    elif composite >= 50:
        risk_band = "AMBER"
    elif composite >= 30:
        risk_band = "RED"
    else:
        risk_band = "BLACK"

    decision = DECISION_MAP[risk_band]
    if auto_reject:
        decision = "REJECT"

    explain = _build_explainability_text(
        dimensions, raw_weighted, composite_pre_qi,
        qi_delta, qi_explanations, composite,
        risk_band, auto_reject, rejection_reason, contradictions,
    )

    return CompositeResult(
        composite_score              = composite,
        risk_band                    = risk_band,
        decision                     = decision,
        auto_reject                  = auto_reject,
        rejection_reason             = rejection_reason,
        dimension_scores             = dimensions,
        financial_scores             = financial,
        research_scores              = research_s,
        explainability_text          = explain,
        research_flags               = flags,
        research_tags                = tags,
        qualitative_adjustment       = qi_delta,
        qualitative_explanations     = qi_explanations,
        cross_pillar_contradictions  = contradictions,
    )


# ─────────────────────────────────────────────────────────────
# Explainability text builder
# ─────────────────────────────────────────────────────────────

def _build_explainability_text(
    dims:             List[DimensionScore],
    raw_weighted:     float,
    composite_pre_qi: int,
    qi_delta:         int,
    qi_explanations:  List[str],
    composite:        int,
    risk_band:        str,
    auto_reject:      bool,
    rejection_reason: Optional[str],
    contradictions:   List[str],
) -> str:
    if auto_reject:
        return (
            f"AUTO-REJECT: {rejection_reason}. "
            f"Composite score suppressed to 0. Pipeline halted."
        )

    lines = [
        "COMPOSITE SCORE DERIVATION  [ML-Weighted Scoring Model + Primary Insight]",
        "─" * 72,
    ]
    for d in dims:
        lines.append(
            f"  {d.name:<22} ({d.weight*100:4.0f}%):  "
            f"{d.score:3d}/100  ×  {d.weight:.2f}  =  {d.weighted:5.1f} pts"
            f"  [{d.color}]"
        )
    lines.append("─" * 72)
    lines.append(f"  Raw Weighted Sum (sigmoid-normalised): {composite_pre_qi}/100")

    if qi_delta != 0:
        sign = "+" if qi_delta > 0 else ""
        lines.append(f"  Primary Insight Adjustment:           {sign}{qi_delta} pts")
        for ln in qi_explanations:
            lines.append(ln)
    else:
        lines.append("  Primary Insight Adjustment:           0 pts  (no field data entered)")

    lines.append(f"  ──────────────────────────────────────────────")
    lines.append(f"  FINAL COMPOSITE SCORE:                {composite}/100  →  {risk_band}")
    lines.append("")

    sorted_dims = sorted(dims, key=lambda d: d.weighted, reverse=True)
    lines.append(f"  ✅ Key Strengths:  {sorted_dims[0].name} ({sorted_dims[0].score}/100), "
                 f"{sorted_dims[1].name} ({sorted_dims[1].score}/100)")

    sorted_weak = sorted(dims, key=lambda d: d.weighted)
    lines.append(f"  ⚠️  Key Concerns:   {sorted_weak[0].name} ({sorted_weak[0].score}/100), "
                 f"{sorted_weak[1].name} ({sorted_weak[1].score}/100)")

    if contradictions:
        lines.append("")
        lines.append("  🔀 CROSS-PILLAR ANALYSIS:")
        for c in contradictions:
            lines.append(f"     ▸ {c}")

    return "\n".join(lines)
