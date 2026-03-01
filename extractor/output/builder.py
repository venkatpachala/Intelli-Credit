"""
output/builder.py
Assembles the final structured JSON from all pipeline stages.
Output matches the new unified credit schema for the Recommendation Engine.

Output sections:
    1.  company_snapshot
    2.  financial_health_assessment
    3.  banking_behavior_assessment
    4.  compliance_risk
    5.  litigation_risk
    6.  management_quality_assessment
    7.  industry_and_external_intelligence
    8.  credit_rating_analysis
    9.  esg_assessment
    10. overall_risk_scoring
    11. loan_recommendation_context
    12. critical_risk_flags_for_llm
    +   _metadata (pipeline info)
"""

from datetime import datetime


def build_final_json(
    raw_texts:    list,
    structured:   dict,
    validation:   list,
    source_file:  str,
    company_hint: str,
) -> dict:
    """
    Assembles the complete credit extraction JSON output in the new schema.
    """
    fields = structured.get("fields", structured)

    # Enrich cross-validation flags into the LLM output
    cv_flags = _extract_cv_flags(validation)
    risk_scores = _compute_risk_scores(fields, validation)

    # Merge cross-validation red flags into financial red flags
    llm_red_flags = fields.get("financial_health_assessment", {}).get("red_flags", [])
    llm_red_flags.extend(cv_flags)

    # Merge CV critical flags into critical_risk_flags_for_llm
    llm_critical = fields.get("critical_risk_flags_for_llm", [])
    for f in cv_flags:
        if f not in llm_critical:
            llm_critical.append(f)

    # Build the final output
    output = {
        # ── PIPELINE METADATA ─────────────────────────────────
        "_metadata": {
            "engine_version":   "2.0.0",
            "extracted_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_file":      source_file,
            "company_hint":     company_hint or "Unknown",
            "pages_processed":  len(raw_texts),
            "extractor_types":  list(set(p.get("type", "?") for p in raw_texts)),
            "parse_success":    structured.get("parse_success", True),
            "llm_provider":     structured.get("provider", "demo"),
            "cross_validation": {
                "checks_run":    len(validation),
                "checks_passed": sum(1 for c in validation if "PASS" in c.get("result", "")),
                "checks_failed": sum(1 for c in validation if any(kw in c.get("result", "") for kw in ["FAIL", "FLAG", "CRITICAL"])),
                "details":       validation,
            },
        },

        # ── 1. COMPANY SNAPSHOT ───────────────────────────────
        "company_snapshot": _safe_section(fields, "company_snapshot", {
            "name": company_hint or "",
            "industry": "",
            "sector_risk_level": "Medium",
            "years_in_operation": None,
            "market_position": "",
            "geographic_presence": [],
        }),

        # ── 2. FINANCIAL HEALTH ASSESSMENT ────────────────────
        "financial_health_assessment": _merge_financial(fields, llm_red_flags),

        # ── 3. BANKING BEHAVIOR ASSESSMENT ────────────────────
        "banking_behavior_assessment": _safe_section(fields, "banking_behavior_assessment", {
            "cash_flow_volatility": "Not available — no bank statement provided",
            "payment_discipline_score": None,
            "od_dependency_risk": "Not available — no bank statement provided",
            "emi_servicing_track_record": "Not available — no bank statement provided",
        }),

        # ── 4. COMPLIANCE RISK ────────────────────────────────
        "compliance_risk": _safe_section(fields, "compliance_risk", {
            "gst_risk": "Not assessed — no GST returns provided",
            "tax_compliance_risk": "",
            "roc_filing_status": "",
            "regulatory_violations": [],
        }),

        # ── 5. LITIGATION RISK ────────────────────────────────
        "litigation_risk": _safe_section(fields, "litigation_risk", {
            "active_cases_severity": "",
            "financial_impact_estimate": None,
            "criminal_exposure": False,
            "tax_exposure": "",
        }),

        # ── 6. MANAGEMENT QUALITY ─────────────────────────────
        "management_quality_assessment": _safe_section(fields, "management_quality_assessment", {
            "experience_level": "",
            "governance_practices_score": None,
            "related_party_risk": "",
            "credibility_risk": "",
        }),

        # ── 7. INDUSTRY & EXTERNAL INTELLIGENCE ──────────────
        "industry_and_external_intelligence": _safe_section(fields, "industry_and_external_intelligence", {
            "sector_growth_rate": None,
            "sector_outlook": "",
            "competitive_pressure": "",
            "recent_negative_news": [],
            "recent_positive_news": [],
            "macroeconomic_risk": "",
        }),

        # ── 8. CREDIT RATING ANALYSIS ─────────────────────────
        "credit_rating_analysis": _safe_section(fields, "credit_rating_analysis", {
            "current_rating": "",
            "rating_trend": "",
            "default_history": False,
        }),

        # ── 9. ESG ASSESSMENT ─────────────────────────────────
        "esg_assessment": _safe_section(fields, "esg_assessment", {
            "environmental_risk": "",
            "social_risk": "",
            "governance_risk": "",
        }),

        # ── 10. OVERALL RISK SCORING ──────────────────────────
        "overall_risk_scoring": risk_scores,

        # ── 11. LOAN RECOMMENDATION CONTEXT ───────────────────
        "loan_recommendation_context": _safe_section(fields, "loan_recommendation_context", {
            "recommended_loan_amount": None,
            "suggested_tenure": "",
            "collateral_required": "",
            "covenants_suggested": [],
            "key_conditions_precedent": [],
        }),

        # ── 12. CRITICAL RISK FLAGS ───────────────────────────
        "critical_risk_flags_for_llm": llm_critical,
    }

    return output


# ─────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────

def _safe_section(fields: dict, key: str, defaults: dict) -> dict:
    """Returns the LLM-extracted section, merged with defaults for missing keys."""
    extracted = fields.get(key, {})
    if not isinstance(extracted, dict):
        return defaults
    result = dict(defaults)  # start with defaults
    result.update({k: v for k, v in extracted.items() if v is not None and v != ""})
    return result


def _merge_financial(fields: dict, enriched_flags: list) -> dict:
    """Merges LLM financial health with cross-validation enriched red flags."""
    base = fields.get("financial_health_assessment", {})
    if not isinstance(base, dict):
        base = {}

    defaults = {
        "revenue_trend": "",
        "profitability_trend": "",
        "cash_flow_quality": "",
        "leverage_risk": "",
        "working_capital_cycle_days": None,
        "benchmark_comparison": {
            "industry_average_ebitda_margin": None,
            "company_ebitda_margin": None,
            "industry_average_de_ratio": None,
            "company_de_ratio": None,
        },
        "red_flags": [],
        "strengths": [],
    }

    result = dict(defaults)
    result.update({k: v for k, v in base.items() if v is not None and v != "" and k != "red_flags"})
    result["red_flags"] = enriched_flags
    if "strengths" in base and base["strengths"]:
        result["strengths"] = base["strengths"]

    return result


def _extract_cv_flags(validation: list) -> list:
    """Extracts human-readable flag strings from cross-validation results."""
    flags = []
    for check in validation:
        result = check.get("result", "")
        if any(kw in result for kw in ["FAIL", "FLAG", "WARN", "CRITICAL"]):
            flags.append(f"[CV_{check.get('check_id', '?')}] {result}")
    return flags


def _compute_risk_scores(fields: dict, validation: list) -> dict:
    """
    Computes risk scores. Uses LLM scores if available, otherwise
    derives from cross-validation results.
    """
    llm_scores = fields.get("overall_risk_scoring", {})
    if not isinstance(llm_scores, dict):
        llm_scores = {}

    # Count severity of cross-validation failures for fallback scoring
    critical = sum(1 for c in validation if c.get("severity") == "CRITICAL" and any(kw in c.get("result", "") for kw in ["FAIL", "FLAG", "CRITICAL"]))
    high     = sum(1 for c in validation if c.get("severity") == "HIGH" and any(kw in c.get("result", "") for kw in ["FAIL", "FLAG"]))
    medium   = sum(1 for c in validation if c.get("severity") == "MEDIUM" and "WARN" in c.get("result", ""))

    # Use LLM scores if present, else derive from CV results
    fin_score  = llm_scores.get("financial_risk_score") or min(critical * 3 + high * 2 + medium, 10)
    comp_score = llm_scores.get("compliance_risk_score") or 0
    mgmt_score = llm_scores.get("management_risk_score") or 0
    ind_score  = llm_scores.get("industry_risk_score") or 0

    # Weighted average (financial heaviest at 40%)
    scores = [s for s in [fin_score, comp_score, mgmt_score, ind_score] if s is not None]
    overall = round(sum(scores) / max(len(scores), 1), 1) if scores else 0

    # Map to risk category
    if overall <= 3:
        category = "Low"
    elif overall <= 5:
        category = "Moderate"
    elif overall <= 7:
        category = "High"
    else:
        category = "Very High"

    return {
        "financial_risk_score":   fin_score,
        "compliance_risk_score":  comp_score,
        "management_risk_score":  mgmt_score,
        "industry_risk_score":    ind_score,
        "overall_credit_score":   overall,
        "risk_category":          llm_scores.get("risk_category", category),
    }