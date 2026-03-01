"""
research_agent/synthesizer.py
Merges Data Ingestor JSON + Web Research into the final unified credit schema.
This is the "brain" that combines both pipelines into one output.
"""

import json
from datetime import datetime


def synthesize(ingestor_json: dict, research_data: dict) -> dict:
    """
    Takes:
        ingestor_json  — output from the Data Ingestor API (POST /process)
        research_data  — output from web_search.search_company()
    
    Returns:
        Unified credit schema JSON for the Recommendation Engine.
    """

    # Start with ingestor data as the base
    final = dict(ingestor_json)

    # ── Enrich company_snapshot ────────────────────────────
    snapshot = final.get("company_snapshot", {})
    if not snapshot.get("name") and research_data.get("company_name"):
        snapshot["name"] = research_data["company_name"]
    if not snapshot.get("industry") and research_data.get("industry"):
        snapshot["industry"] = research_data["industry"]
    final["company_snapshot"] = snapshot

    # ── Enrich industry_and_external_intelligence ─────────
    intel = final.get("industry_and_external_intelligence", {})

    # Add negative news from web search
    existing_neg = intel.get("recent_negative_news", [])
    for item in research_data.get("negative_news", []):
        title = item.get("title", "")
        if title and title not in existing_neg:
            existing_neg.append(title)
    intel["recent_negative_news"] = existing_neg[:10]  # cap at 10

    # Add positive news from web search
    existing_pos = intel.get("recent_positive_news", [])
    for item in research_data.get("positive_news", []):
        title = item.get("title", "")
        if title and title not in existing_pos:
            existing_pos.append(title)
    intel["recent_positive_news"] = existing_pos[:10]

    # Enrich sector outlook
    if research_data.get("sector_outlook") and not intel.get("sector_outlook"):
        summaries = [r.get("body", "") for r in research_data["sector_outlook"][:3]]
        intel["sector_outlook"] = " | ".join(summaries)[:500]

    final["industry_and_external_intelligence"] = intel

    # ── Enrich litigation_risk ────────────────────────────
    litigation = final.get("litigation_risk", {})
    lit_results = research_data.get("litigation", [])
    if lit_results:
        # Check if any litigation results contain serious keywords
        serious_keywords = ["nclt", "ibc", "insolvency", "fraud", "arrest", "scam", "default"]
        serious_cases = []
        for item in lit_results:
            text = (item.get("title", "") + " " + item.get("body", "")).lower()
            if any(kw in text for kw in serious_keywords):
                serious_cases.append(item.get("title", ""))

        if serious_cases:
            litigation["active_cases_severity"] = "High"
            
            # Add to critical flags
            critical = final.get("critical_risk_flags_for_llm", [])
            for case in serious_cases[:3]:
                flag = f"Web Research: {case}"
                if flag not in critical:
                    critical.append(flag)
            final["critical_risk_flags_for_llm"] = critical

    final["litigation_risk"] = litigation

    # ── Enrich management_quality_assessment ───────────────
    mgmt = final.get("management_quality_assessment", {})
    promoter_results = research_data.get("promoter_info", [])
    if promoter_results and not mgmt.get("credibility_risk"):
        # Check for negative promoter news
        neg_keywords = ["arrest", "fraud", "scam", "resignation", "controversy", "disqualified"]
        for item in promoter_results:
            text = (item.get("title", "") + " " + item.get("body", "")).lower()
            if any(kw in text for kw in neg_keywords):
                mgmt["credibility_risk"] = "High — Negative promoter news found in web research"
                break
    final["management_quality_assessment"] = mgmt

    # ── Enrich compliance_risk ────────────────────────────
    compliance = final.get("compliance_risk", {})
    reg_results = research_data.get("regulatory_news", [])
    if reg_results:
        violations = compliance.get("regulatory_violations", [])
        for item in reg_results:
            text = (item.get("title", "") + " " + item.get("body", "")).lower()
            if any(kw in text for kw in ["penalty", "fine", "violation", "ban", "suspended"]):
                violations.append(item.get("title", ""))
        compliance["regulatory_violations"] = violations[:5]
    final["compliance_risk"] = compliance

    # ── Add research metadata ─────────────────────────────
    meta = final.get("_metadata", {})
    meta["research_agent"] = {
        "searched_at": research_data.get("searched_at", ""),
        "queries_run": 6,
        "total_results": sum(
            len(research_data.get(k, []))
            for k in ["negative_news", "positive_news", "litigation",
                       "sector_outlook", "promoter_info", "regulatory_news"]
        ),
    }
    final["_metadata"] = meta

    return final
