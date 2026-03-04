"""
cam_engine/recommendation/rate_engine.py
=========================================
Calculates the recommended interest rate via an additive premium chain.

Base Rate = Repo Rate + Bank Spread (configurable in .env)
Each premium is added in basis points (100 bps = 1%) and corresponds
to a specific risk finding from either the financial or research data.

Total premium is capped at 3.50% above base to avoid punitive rates.

Every premium gets printed in the CAM rate derivation table (Section 9.2)
so the banker can explain each basis point to the borrower.
"""

from __future__ import annotations

import os
from typing import Dict, List

from .models import LoanRecommendation, Premium, RateRecommendation, AmountRecommendation

# ── Rate parameters (override via .env) ─────────────────────
REPO_RATE    = float(os.getenv("REPO_RATE",    "6.50"))
BANK_SPREAD  = float(os.getenv("BANK_SPREAD",  "3.00"))
BASE_RATE    = REPO_RATE + BANK_SPREAD          # default 9.50%
MAX_PREMIUM  = float(os.getenv("MAX_PREMIUM_PCT", "3.50"))   # cap in %


def _safe(v) -> float:
    if v is None: return 0.0
    if isinstance(v, dict): return float(v.get("value", 0) or 0)
    try:    return float(v)
    except: return 0.0


def calculate_interest_rate(
    extraction:  Dict,
    research:    Dict,
    composite,                  # CompositeResult
) -> RateRecommendation:
    """
    Build the interest rate premium chain.
    Returns RateRecommendation with every basis point justified.
    """
    flags = research.get("flags", [])
    tags  = research.get("tags", [])
    cm    = extraction.get("credit_metrics", {})
    bs    = extraction.get("balance_sheet", {})

    premiums: List[Premium] = []

    # ── DSCR-based premium ───────────────────────────────────
    dscr = _safe(cm.get("dscr"))
    if dscr == 0:
        icr_dict = cm.get("interest_coverage_ratio", {})
        if isinstance(icr_dict, dict) and icr_dict:
            dscr_vals = [_safe(v) for v in icr_dict.values()]
            dscr = dscr_vals[-1] if dscr_vals else 0.0

    if 0 < dscr < 1.25:
        premiums.append(Premium(bps=75,  source="FINANCIAL",
                                reason=f"DSCR {dscr:.2f}x — below RBI minimum 1.25x (significant repayment risk)"))
    elif dscr < 1.5:
        premiums.append(Premium(bps=25,  source="FINANCIAL",
                                reason=f"DSCR {dscr:.2f}x — tight coverage (1.25–1.50x band)"))

    # ── D/E Ratio premium ────────────────────────────────────
    de = _safe(cm.get("debt_equity"))
    if de == 0:
        de_dict = bs.get("gearing_ratio", {})
        if isinstance(de_dict, dict) and de_dict:
            de_vals = [_safe(v) for v in de_dict.values()]
            de = de_vals[-1] if de_vals else 0.0

    if de > 3.0:
        premiums.append(Premium(bps=100, source="FINANCIAL",
                                reason=f"D/E ratio {de:.2f}x — high leverage above 3x threshold"))
    elif de > 2.0:
        premiums.append(Premium(bps=50,  source="FINANCIAL",
                                reason=f"D/E ratio {de:.2f}x — elevated leverage (2–3x band)"))

    # ── Sector headwind (from research tags) ─────────────────
    if any("headwind" in t.lower() or "stress" in t.lower() or "SECTOR" in t for t in tags):
        premiums.append(Premium(bps=50,  source="RESEARCH",
                                reason="Sector headwind flag from research agent (news/regulatory signals)"))

    # ── Promoter HIGH flag ───────────────────────────────────
    promoter_high = [f for f in flags
                     if f.get("severity") == "HIGH"
                     and f.get("category") in ("PROMOTER", "FRAUD")]
    if promoter_high:
        premiums.append(Premium(bps=75, source="RESEARCH",
                                reason=f"HIGH promoter flag: {promoter_high[0].get('title', 'promoter concern')}"))

    # ── Litigation HIGH flag ─────────────────────────────────
    lit_high = [f for f in flags
                if f.get("severity") == "HIGH"
                and f.get("category") == "LITIGATION"]
    if lit_high:
        premiums.append(Premium(bps=100, source="RESEARCH",
                                reason=f"HIGH litigation flag: {lit_high[0].get('title', 'court case')}"))

    # ── CIBIL CMR Score ──────────────────────────────────────
    cb   = extraction.get("credit_bureau_data", {})
    cmr  = int(_safe(cb.get("cmr_score")) or 0)
    if cmr >= 6:
        premiums.append(Premium(bps=150, source="FINANCIAL",
                                reason=f"CIBIL CMR score {cmr} — high credit risk band (5–10)"))
    elif cmr >= 5:
        premiums.append(Premium(bps=75,  source="FINANCIAL",
                                reason=f"CIBIL CMR score {cmr} — moderate credit risk band (4–5)"))

    # ── MCA Compliance gap ───────────────────────────────────
    mca_flags = [f for f in flags if f.get("source") == "MCA" or f.get("category") == "REGULATORY"]
    mca_medium = [f for f in mca_flags if f.get("severity") == "MEDIUM"]
    if mca_medium:
        premiums.append(Premium(bps=25, source="RESEARCH",
                                reason=f"MCA/ROC compliance gap: {mca_medium[0].get('title', 'ROC filing delay')}"))

    # ── NPA / overdue in banking data ────────────────────────
    bank    = extraction.get("banking_data", {})
    bounces = int(_safe(bank.get("emi_bounces")) or 0)
    if bounces > 2:
        premiums.append(Premium(bps=50, source="FINANCIAL",
                                reason=f"{bounces} EMI/ECS bounces in last 12 months (banking irregularity)"))

    # ── GST compliance gap ───────────────────────────────────
    gst        = extraction.get("gst_data", {})
    compliance = float(gst.get("filing_compliance_pct", -1) or -1)
    if 0 <= compliance < 80:
        premiums.append(Premium(bps=25, source="FINANCIAL",
                                reason=f"GST filing compliance {compliance:.0f}% — below 80% threshold"))

    # ── Existing NPA from debt schedule ──────────────────────
    debt_sched = extraction.get("debt_data", [])
    npa_debts  = [d for d in debt_sched if d.get("npa_status") or int(_safe(d.get("dpd")) or 0) > 90]
    if npa_debts:
        premiums.append(Premium(bps=150, source="FINANCIAL",
                                reason=f"Existing NPA/overdue facility detected (DPD >90 days)"))

    # ── Cap total premium ────────────────────────────────────
    total_bps_raw = sum(p.bps for p in premiums)
    total_bps     = min(total_bps_raw, int(MAX_PREMIUM * 100))

    if total_bps < total_bps_raw:
        # Add a cap note
        premiums.append(Premium(bps=0, source="INTERNAL",
                                reason=f"Premium capped at {MAX_PREMIUM}% (bank policy maximum above base)"))

    final_rate = round(BASE_RATE + total_bps / 100, 2)
    rate_band  = f"{BASE_RATE:.2f}% + {total_bps/100:.2f}% = {final_rate:.2f}%"

    return RateRecommendation(
        base_rate         = BASE_RATE,
        premiums          = premiums,
        total_premium_bps = total_bps,
        final_rate        = final_rate,
        rate_band         = rate_band,
    )


# ────────────────────────────────────────────────────────────
# Auto-derive conditions precedent and covenants
# ────────────────────────────────────────────────────────────

def derive_conditions_precedent(composite, amount_rec: AmountRecommendation) -> list[str]:
    """Standard + risk-triggered conditions before first disbursement."""
    flags = composite.research_flags

    conditions = [
        "Execution of all security documents — loan agreement, hypothecation deed, and mortgage deed.",
        "Submission of latest audited financial statements (within 6 months of year-end).",
        "Board resolution authorising borrowing and security creation.",
        "Proof of insurance on all hypothecated / mortgaged assets naming bank as beneficiary.",
    ]

    # Collateral coverage gap
    if amount_rec.coverage_ratio > 0 and amount_rec.coverage_ratio < 1.50:
        conditions.append(
            f"Additional collateral to bring total coverage to ≥1.50x, OR written acceptance "
            f"of reduced limit of ₹{amount_rec.final/1e7:.2f} Cr."
        )

    # MCA flags
    mca_flags = [f for f in flags if f.get("source") == "MCA" or f.get("category") == "REGULATORY"]
    if mca_flags:
        conditions.append(
            "Closure or satisfactory explanation with supporting documents for all pending MCA charges/filings."
        )

    # GST arrears
    gst_tags = [t for t in composite.research_tags if "GST" in t.upper()]
    if gst_tags:
        conditions.append("GST filing arrears cleared. Compliance certificate from Chartered Accountant.")

    # Litigation
    lit_flags = [f for f in flags if f.get("category") == "LITIGATION" and f.get("severity") in ("HIGH", "CRITICAL")]
    if lit_flags:
        conditions.append(
            "Written status report on all HIGH severity court cases, along with legal opinion from empanelled advocate."
        )

    # NPA check
    conditions.append("Certificate from existing lenders confirming no NPA / overdue classification.")

    return conditions


def derive_covenants(composite) -> list[str]:
    """Standard + risk-triggered ongoing covenants."""
    return [
        "Annual submission of audited financial statements within 90 days of financial year-end.",
        "Quarterly stock and debtors statements for working capital monitoring.",
        f"Maintenance of DSCR ≥1.25x — tested annually from audited accounts.",
        "Immediate notification to bank of any litigation, regulatory action, or adverse news event.",
        "No additional secured borrowing above ₹1 Cr without bank's prior written consent.",
        "Promoter shareholding to remain above 51% throughout the loan tenure.",
        "Half-yearly internal audit report to be submitted to the bank.",
        "Annual site visit by bank credit officer — access to books and records to be provided.",
    ]
