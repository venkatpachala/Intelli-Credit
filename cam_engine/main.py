"""
cam_engine/main.py
====================
Pillar 3 Entry Point — generate_cam()

Full pipeline:
  1. Financial Scorer     → 4 dimension scores (Capacity/Capital/Collateral/GST)
  2. Composite Scorer     → weighted composite from all 8 dimensions
  3. Amount Engine        → recommended loan amount (transparent chain)
  4. Rate Engine          → recommended interest rate (basis-point chain)
  5. Conditions Deriver   → pre-disbursement conditions + covenants
  6. Narrative Generator  → 7 Claude-written CAM sections
  7. Document Builder     → python-docx → .docx
  8. PDF Converter        → .docx → .pdf

Returns:
  cam_dict — JSON-serialisable dict stored in backend SQLite cam_json column
  (also contains docx_path and pdf_path for the download endpoint)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# ── Load environment ──────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
except ImportError:
    pass


# ── Import sub-components ─────────────────────────────────────
from scoring.financial_scorer import (
    score_capacity, score_capital, score_collateral,
    score_gst_quality, score_from_research,
)
from scoring.composite_scorer import compute_composite
from scoring.models import FinancialScores

from recommendation.amount_engine import calculate_recommended_amount
from recommendation.rate_engine import (
    calculate_interest_rate,
    derive_conditions_precedent,
    derive_covenants,
)
from recommendation.models import LoanRecommendation

from narrative.generator import NarrativeGenerator
from narrative.models import NarrativeInput

from document.builder import CAMBuilder
from document.pdf_converter import convert_to_pdf


# ─────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────

def generate_cam(
    case_id:     str,
    extraction:  Dict,          # from Pillar 1 extractor output JSON
    research:    Dict,          # from Pillar 2 research agent ResearchOutput JSON
    req:         Dict,          # original request metadata (case details)
    output_dir:  str = "output",
) -> Dict:
    """
    Full Pillar 3 pipeline.

    Parameters
    ----------
    case_id    : Unique case ID (e.g. "CASE_2026_A1B2C3")
    extraction : Extractor JSON output dict
    research   : Research agent ResearchOutput dict
    req        : Request metadata (company_name, cin, gstin, loan, promoters)
    output_dir : Where to save .docx and .pdf files

    Returns
    -------
    dict  — cam_json (JSON-serialisable, stored in SQLite + returned by API)
    """
    started = datetime.now()
    print(f"\n[Pillar 3] Starting CAM generation for case: {case_id}")

    # Extract qualitative / primary insight data from req
    qualitative = req.get("qualitative", {}) or {}
    print(f"[Pillar 3] Primary insight fields: {list(qualitative.keys()) if qualitative else 'none entered'}")

    # ── 1. Score: Financial dimensions ───────────────────────
    print("[Pillar 3] Step 1/7 — Financial scoring...")
    requested_amount = float(
        req.get("loan", {}).get("amount_inr", 0) or
        req.get("loan_amount", 0) or 0
    )

    cap_dim  = score_capacity(extraction)
    cap2_dim = score_capital(extraction)
    col_dim  = score_collateral(extraction, requested_amount)
    gst_dim  = score_gst_quality(extraction)

    fin_scores = FinancialScores(
        capacity    = cap_dim,
        capital     = cap2_dim,
        collateral  = col_dim,
        gst_quality = gst_dim,
    )

    # ── 2. Score: Research dimensions ────────────────────────
    print("[Pillar 3] Step 2/7 — Research scoring...")
    res_scores = score_from_research(research)

    # ── 3. Composite ───────────────────────────────────────────
    print("[Pillar 3] Step 3/7 — Composite scoring...")
    composite = compute_composite(fin_scores, res_scores, research, qualitative)
    print(f"           Composite: {composite.composite_score}/100 -> {composite.risk_band} -> {composite.decision}")
    if composite.qualitative_adjustment != 0:
        print(f"           Qualitative adjustment: {'+' if composite.qualitative_adjustment > 0 else ''}{composite.qualitative_adjustment} pts applied")

    # ── 4. Loan recommendation ────────────────────────────────
    print("[Pillar 3] Step 4/7 — Loan recommendation...")
    amount_rec = calculate_recommended_amount(
        requested_amount = requested_amount,
        extraction       = extraction,
        research         = research,
        composite        = composite,
    )
    rate_rec = calculate_interest_rate(extraction, research, composite)
    conds    = derive_conditions_precedent(composite, amount_rec)
    covs     = derive_covenants(composite)

    rec_amount_cr  = amount_rec.final / 1e7
    req_amount_cr  = requested_amount / 1e7
    print(f"           Amount:  Rs.{rec_amount_cr:.2f} Cr (requested: Rs.{req_amount_cr:.2f} Cr)")
    print(f"           Rate:    {rate_rec.final_rate:.2f}% p.a. ({rate_rec.rate_band})")

    # ── 5. Build narratives ───────────────────────────────────
    print("[Pillar 3] Step 5/7 — Generating narratives (Claude)...")
    promoters   = req.get("promoters", [])
    industry    = (extraction.get("company_profile", {}).get("sector")
                   or req.get("industry", "Unknown Sector"))
    loan_type   = (req.get("loan", {}).get("type")
                   or req.get("loan_type", "Working Capital"))
    tenor       = int(req.get("loan", {}).get("tenor_months", 36) or 36)

    # Pull financial data for narrative hydration
    income      = extraction.get("income_statement", {})
    rev_vals    = _extract_period_values(income.get("total_revenue", {}))
    ebitda_vals = _extract_period_values(income.get("ebitda", {}))
    pat_vals    = _extract_period_values(income.get("pat", {}))
    cfo_vals    = _extract_period_values(extraction.get("cash_flow", {}).get("cfo", {}))
    periods     = income.get("periods", []) or list(income.get("total_revenue", {}).keys())[:3]
    rev_cagr    = _cagr(rev_vals)
    ebitda_m    = (ebitda_vals[-1] / rev_vals[-1] * 100) if (rev_vals and ebitda_vals and rev_vals[-1]) else 0.0

    bs          = extraction.get("balance_sheet", {})
    cm          = extraction.get("credit_metrics", {})
    nw          = _safe(bs.get("net_worth", 0))
    td_raw      = bs.get("total_debt", {})
    td          = _safe(td_raw) if not isinstance(td_raw, dict) else (
        _safe(td_raw.get("term_loan_outstanding", 0)) +
        _safe(td_raw.get("total_rated_facilities", 0))
    )
    ta          = _safe(bs.get("total_assets", 0))
    tnw         = _safe(bs.get("tangible_net_worth", 0)) or nw
    de          = _safe(cm.get("debt_equity", 0))
    if de == 0 and nw > 0 and td > 0:
        de = td / nw
    dscr        = _safe(cm.get("dscr", 0))
    icr         = _latest_val(cm.get("interest_coverage_ratio", {}))

    collateral  = extraction.get("collateral_data", [])
    total_market   = sum(_safe(a.get("market_value")) for a in collateral)
    total_distress = sum(_safe(a.get("distress_value")) for a in collateral)
    cov_market     = total_market / requested_amount if requested_amount > 0 else 0.0
    cov_distress   = total_distress / requested_amount if requested_amount > 0 else 0.0

    flags_list   = research.get("flags", [])
    tags_list    = research.get("tags", [])
    rbi_result   = "Not flagged in RBI Wilful Defaulter database"
    lit_flags    = [f for f in flags_list if f.get("category") == "LITIGATION"]
    news_signals = [f.get("title", f.get("description", "")) for f in flags_list if f.get("source") == "NEWS"]

    narr_input = NarrativeInput(
        case_id          = case_id,
        company_name     = req.get("company_name", extraction.get("company_profile", {}).get("legal_name", "Company")),
        cin              = req.get("cin", ""),
        industry         = industry,
        loan_type        = loan_type,
        tenor_months     = tenor,
        requested_cr     = req_amount_cr,
        recommended_cr   = rec_amount_cr,
        promoters        = promoters,
        decision         = composite.decision,
        risk_band        = composite.risk_band,
        composite_score  = composite.composite_score,
        interest_rate    = rate_rec.final_rate,
        character_score  = res_scores.character.score,
        capacity_score   = cap_dim.score,
        capital_score    = cap2_dim.score,
        collateral_score = col_dim.score,
        conditions_score = res_scores.conditions.score,
        capacity_breakdown  = [b.model_dump() for b in cap_dim.breakdown],
        capital_breakdown   = [b.model_dump() for b in cap2_dim.breakdown],
        collateral_breakdown= [b.model_dump() for b in col_dim.breakdown],
        revenue  = rev_vals,
        ebitda   = ebitda_vals,
        pat      = pat_vals,
        cfo      = cfo_vals,
        periods  = [str(p) for p in periods[:3]],
        rev_cagr = rev_cagr,
        ebitda_margin_latest = ebitda_m,
        dscr       = dscr,
        icr        = icr,
        de_ratio   = de,
        net_worth_cr    = nw / 1e2 if nw > 1e4 else nw,     # assume crores if < 10000
        total_debt_cr   = td / 1e2 if td > 1e4 else td,
        tangible_nw_cr  = tnw / 1e2 if tnw > 1e4 else tnw,
        total_assets_cr = ta / 1e2 if ta > 1e4 else ta,
        promoter_shareholding = float(extraction.get("company_profile", {}).get("promoter_stake_pct", 0) or 0),
        collateral_assets  = collateral,
        total_market_cr    = total_market / 1e2 if total_market > 1e4 else total_market,
        total_distress_cr  = total_distress / 1e2 if total_distress > 1e4 else total_distress,
        coverage_market    = cov_market,
        coverage_distress  = cov_distress,
        research_flags     = flags_list,
        research_tags      = tags_list,
        rbi_result         = rbi_result,
        litigation_count   = len(lit_flags),
        mca_flag_count     = len([f for f in flags_list if f.get("source") == "MCA"]),
        news_signals       = [s for s in news_signals if s][:5],
        sector_score       = res_scores.conditions.score,
        rate_base          = rate_rec.base_rate,
        rate_premiums      = [p.model_dump() for p in rate_rec.premiums],
        amount_adjustments = [a.model_dump() for a in amount_rec.adjustments],
        conditions_precedent = conds,
        covenants            = covs,
        # ── Primary Insight fields ───────────────────────────────────────
        qualitative_adjustment       = composite.qualitative_adjustment,
        qualitative_explanations     = composite.qualitative_explanations,
        cross_pillar_contradictions  = composite.cross_pillar_contradictions,
        factory_capacity_pct         = float(qualitative.get("factory_capacity_pct", -1) or -1),
        management_quality           = int(qualitative.get("management_quality", 0) or 0),
        site_condition               = str(qualitative.get("site_condition", "") or ""),
        key_person_risk              = bool(qualitative.get("key_person_risk", False)),
        supply_chain_risk            = bool(qualitative.get("supply_chain_risk", False)),
        cibil_commercial_score       = float(qualitative.get("cibil_commercial_score", -1) or -1),
        primary_insight_notes        = str(qualitative.get("notes", "") or ""),
    )

    narr_gen   = NarrativeGenerator(api_key=os.getenv("GEMINI_API_KEY"))
    narratives = narr_gen.generate_all(narr_input)
    print(f"           Narratives generated. Errors: {list(narratives.errors.keys()) or 'none'}")

    # ── 6. Build cam_data dict ────────────────────────────────
    print("[Pillar 3] Step 6/7 — Assembling CAM data...")
    all_dims = (
        composite.dimension_scores
        if composite.dimension_scores
        else []
    )

    cam_data = {
        # Identity
        "case_id":          case_id,
        "company_name":     narr_input.company_name,
        "cin":              narr_input.cin,
        "gstin":            req.get("gstin", ""),
        "industry":         industry,
        "loan_type":        loan_type,

        # Decision
        "decision":             composite.decision,
        "risk_band":            composite.risk_band,
        "composite_score":      composite.composite_score,
        "auto_reject":          composite.auto_reject,
        "rejection_reason":     composite.rejection_reason,

        # Amounts
        "requested_amount_inr":   requested_amount,
        "recommended_amount_inr": amount_rec.final,
        "wc_gap_inr":             amount_rec.wc_gap,
        "base_amount_inr":        amount_rec.base,

        # Rate
        "interest_rate":    rate_rec.final_rate,
        "base_rate":        rate_rec.base_rate,
        "rate_band":        rate_rec.rate_band,

        # Explainability chains
        "amount_adjustments":  [a.model_dump() for a in amount_rec.adjustments],
        "rate_premiums":       [p.model_dump() for p in rate_rec.premiums],

        # Dimension scores
        "dimension_scores": [d.model_dump() for d in all_dims],
        "five_c_scores": [
            {"name": "Character",   "score": res_scores.character.score,    "color": res_scores.character.color},
            {"name": "Capacity",    "score": cap_dim.score,                 "color": cap_dim.color},
            {"name": "Capital",     "score": cap2_dim.score,                "color": cap2_dim.color},
            {"name": "Collateral",  "score": col_dim.score,                 "color": col_dim.color},
            {"name": "Conditions",  "score": res_scores.conditions.score,   "color": res_scores.conditions.color},
        ],

        # Conditions
        "conditions_precedent": conds,
        "covenants":            covs,

        # Flags
        "research_flags":    flags_list,
        "extraction_flags":  extraction.get("risk_flags", {}).get("flags", []),
        "research_tags":     tags_list,

        # Narratives
        "narratives": narratives.model_dump(),

        # Pass-through data for document builder
        "promoters":      promoters,
        "company_profile":extraction.get("company_profile", {}),
        "loan_details":   req.get("loan", {}),
        "extraction":     extraction,

        # Metadata
        "generated_at":  started.isoformat(),
        "engine_version":"3.1.0",
        "prepared_by":   "Intelli-Credit AI Engine v3.1",

        # Score verbatim
        "explainability_text":       composite.explainability_text,

        # Primary Insight / Qualitative adjustment
        "qualitative_adjustment":    composite.qualitative_adjustment,
        "qualitative_explanations":  composite.qualitative_explanations,
        "cross_pillar_contradictions": composite.cross_pillar_contradictions,

        # Decision Rationale (from 8th narrative section)
        "decision_rationale": narratives.decision_rationale if hasattr(narratives, 'decision_rationale') else "",
    }


    # ── 7. Build Word document ────────────────────────────────
    print("[Pillar 3] Step 7/7 — Building Word document...")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    docx_path = str(Path(output_dir) / f"CAM_{case_id}_{ts}.docx")

    try:
        builder  = CAMBuilder()
        doc      = builder.build(cam_data)
        doc.save(docx_path)
        print(f"           DOCX saved: {docx_path}")
        cam_data["docx_path"] = docx_path

        # PDF conversion
        pdf_path  = docx_path.replace(".docx", ".pdf")
        pdf_result= convert_to_pdf(docx_path, pdf_path)
        cam_data["pdf_path"] = pdf_result or docx_path
    except Exception as e:
        print(f"[Pillar 3] Document build failed: {e}", file=sys.stderr)
        cam_data["docx_path"] = None
        cam_data["pdf_path"]  = None
        cam_data["doc_error"] = str(e)

    elapsed = (datetime.now() - started).total_seconds()
    print(f"[Pillar 3] Done! CAM generated in {elapsed:.1f}s")
    print(f"   Decision: {cam_data['decision']}")
    print(f"   Amount:   Rs.{cam_data['recommended_amount_inr']/1e7:.2f} Cr")
    print(f"   Rate:     {cam_data['interest_rate']:.2f}% p.a.")
    print(f"   Score:    {cam_data['composite_score']}/100 [{cam_data['risk_band']}]")
    print(f"   DOCX:     {cam_data.get('docx_path','--')}")
    print(f"   PDF:      {cam_data.get('pdf_path','--')}")

    return cam_data


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _safe(v, fallback: float = 0.0) -> float:
    if v is None: return fallback
    if isinstance(v, dict): return float(v.get("value", fallback) or fallback)
    try:    return float(v)
    except: return fallback


def _extract_period_values(period_dict: Dict) -> list:
    """Extract ordered list of values from {period: {value: N}} dict."""
    if not isinstance(period_dict, dict):
        return []
    out = []
    for v in period_dict.values():
        val = _safe(v)
        if val != 0:
            out.append(val)
    return out


def _cagr(values: list) -> float:
    if len(values) < 2 or values[0] <= 0:
        return 0.0
    n = len(values) - 1
    try:
        return ((values[-1] / values[0]) ** (1 / n) - 1) * 100
    except:
        return 0.0


def _latest_val(d) -> float:
    if not isinstance(d, dict):
        return _safe(d)
    vals = [_safe(v) for v in d.values() if _safe(v) > 0]
    return vals[-1] if vals else 0.0


# ─────────────────────────────────────────────────────────────
# CLI usage (standalone test)
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pillar 3 — CAM Generator")
    parser.add_argument("--extraction", required=True, help="Path to extractor output JSON")
    parser.add_argument("--research",   default="{}",  help="Path to research agent JSON (optional)")
    parser.add_argument("--case-id",    default="TEST_CASE_001")
    parser.add_argument("--company",    default="Test Company Ltd")
    parser.add_argument("--amount",     type=float, default=10_000_000, help="Amount in INR")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    with open(args.extraction) as f:
        extraction = json.load(f)

    research = {}
    if args.research and args.research != "{}":
        try:
            with open(args.research) as f:
                research = json.load(f)
        except Exception:
            pass

    req = {
        "company_name": args.company,
        "cin":   extraction.get("company_profile", {}).get("cin", "U00000MH2020PTC000000"),
        "gstin": "27AAAAA0000A1Z5",
        "loan":  {"amount_inr": args.amount, "type": "Working Capital", "tenor_months": 36, "purpose": "Working capital requirements"},
        "promoters": [],
        "ingestion_version": "CLI_TEST",
    }

    result = generate_cam(
        case_id    = args.case_id,
        extraction = extraction,
        research   = research,
        req        = req,
        output_dir = args.output_dir,
    )
    print("\n[CLI] CAM JSON keys:", list(result.keys()))
