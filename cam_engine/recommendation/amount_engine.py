"""
cam_engine/recommendation/amount_engine.py
=============================================
Calculates the recommended loan amount via a transparent
sequential multiplier chain.

Every adjustment is recorded with:
  factor  — the multiplier applied
  reason  — plain English explanation
  before  — amount before this adjustment
  after   — amount after this adjustment

This chain gets printed verbatim in the CAM document (Section 9.1)
so the judge can trace every rupee.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import Adjustment, AmountRecommendation

# Minimum collateral coverage the bank requires for full disbursement
PREFERRED_COVERAGE    = 1.50
MINIMUM_COVERAGE      = 1.25
# Round recommended amount to nearest X INR (₹25L = 2_500_000)
ROUNDING_UNIT         = 2_500_000


def _safe(v) -> float:
    if v is None: return 0.0
    if isinstance(v, dict): return float(v.get("value", 0) or 0)
    try:    return float(v)
    except: return 0.0


def calculate_recommended_amount(
    requested_amount: float,       # INR
    extraction:       Dict,
    research:         Dict,
    composite,                     # CompositeResult
) -> AmountRecommendation:
    """
    Returns AmountRecommendation with:
      - full adjustment chain
      - final recommended amount (rounded)
      - decision (APPROVE | CONDITIONAL | REJECT)
    """
    flags       = research.get("flags", [])
    auto_reject = composite.auto_reject

    # ── Hard reject ──────────────────────────────────────────
    if auto_reject:
        return AmountRecommendation(
            requested=requested_amount, wc_gap=0, base=0,
            adjustments=[], final=0,
            decision="REJECT",
            rejection_reason=composite.rejection_reason or "CRITICAL flag triggered auto-reject",
        )

    # ── Working Capital Gap ceiling ──────────────────────────
    bs  = extraction.get("balance_sheet", {})
    ca  = _safe(bs.get("current_assets"))
    cl  = _safe(bs.get("current_liabilities"))
    wc_gap = max(0.0, ca - cl) if (ca and cl) else 0.0

    base = min(requested_amount, wc_gap) if wc_gap > 0 else requested_amount

    adjustments: List[Adjustment] = []
    amount = base

    def apply(factor: float, reason: str):
        nonlocal amount
        before = amount
        after  = amount * factor
        adjustments.append(Adjustment(factor=factor, reason=reason, before=before, after=after))
        amount = after

    # ── D/E Ratio ────────────────────────────────────────────
    cm         = extraction.get("credit_metrics", {})
    de_raw     = cm.get("debt_equity", 0)
    if isinstance(de_raw, dict):
        de_vals = [_safe(v) for v in de_raw.values()]
        de = de_vals[-1] if de_vals else 0.0
    else:
        de = _safe(de_raw)
    
    if de == 0:
        # Estimate from BS
        de_dict = bs.get("gearing_ratio", {})
        if isinstance(de_dict, dict) and de_dict:
            vals = list(de_dict.values())
            de = _safe(vals[-1]) if vals else 0.0

    if de > 3.0:
        apply(0.70, f"D/E {de:.2f}x → above 3x high leverage threshold")
    elif de > 2.0:
        apply(0.85, f"D/E {de:.2f}x → elevated leverage (2–3x band)")
    elif de > 1.5:
        apply(0.92, f"D/E {de:.2f}x → moderate leverage (1.5–2x band)")

    # ── DSCR ─────────────────────────────────────────────────
    dscr = _safe(cm.get("dscr"))
    if dscr == 0:
        icr_dict = cm.get("interest_coverage_ratio", {})
        if isinstance(icr_dict, dict) and icr_dict:
            vals = list(icr_dict.values())
            dscr = _safe(vals[-1]) if vals else 0.0

    if 0 < dscr < 1.25:
        apply(0.70, f"DSCR {dscr:.2f}x → below minimum RBI threshold of 1.25x")
    elif dscr < 1.5:
        apply(0.85, f"DSCR {dscr:.2f}x → tight coverage (1.25–1.5x band)")

    # ── Research HIGH flags ──────────────────────────────────
    high_flags     = [f for f in flags if f.get("severity") == "HIGH"]
    critical_flags = [f for f in flags if f.get("severity") == "CRITICAL"]

    if critical_flags:
        return AmountRecommendation(
            requested=requested_amount, wc_gap=wc_gap, base=base,
            adjustments=adjustments, final=0,
            decision="REJECT",
            rejection_reason=f"CRITICAL research flag: {critical_flags[0].get('title', 'unknown')}",
        )

    if len(high_flags) >= 2:
        apply(0.75, f"{len(high_flags)} HIGH severity research flags detected")
    elif len(high_flags) == 1:
        apply(0.90, f"1 HIGH severity flag: {high_flags[0].get('title', 'research flag')}")

    # ── Collateral Coverage ──────────────────────────────────
    collateral_data  = extraction.get("collateral_data", [])
    total_market     = sum(_safe(a.get("market_value")) for a in collateral_data)
    coverage_ratio   = (total_market / requested_amount) if requested_amount > 0 else 0.0

    if collateral_data:
        if coverage_ratio < MINIMUM_COVERAGE:
            apply(0.75, f"Collateral coverage {coverage_ratio:.2f}x — below minimum {MINIMUM_COVERAGE}x")
        elif coverage_ratio < PREFERRED_COVERAGE:
            apply(0.90, f"Collateral coverage {coverage_ratio:.2f}x — below preferred {PREFERRED_COVERAGE}x")

    # ── GST Compliance ───────────────────────────────────────
    gst         = extraction.get("gst_data", {})
    compliance  = float(gst.get("filing_compliance_pct", -1) or -1)
    if 0 <= compliance < 80:
        apply(0.85, f"GST filing compliance {compliance:.0f}% — below 80% threshold")

    # ── Banking Behaviour ────────────────────────────────────
    bank    = extraction.get("banking_data", {})
    bounces = int(bank.get("emi_bounces", 0) or 0)
    if bounces > 3:
        apply(0.90, f"{bounces} EMI/ECS bounces in banking history")

    # ── Round to nearest ₹25L ────────────────────────────────
    final_raw = amount
    final_rnd = round(amount / ROUNDING_UNIT) * ROUNDING_UNIT
    final_rnd = max(0, final_rnd)

    # Ensure we never recommend more than what was requested
    final_rnd = min(final_rnd, requested_amount)

    decision = "APPROVE" if not adjustments else "CONDITIONAL APPROVAL"

    return AmountRecommendation(
        requested      = requested_amount,
        wc_gap         = wc_gap,
        base           = base,
        adjustments    = adjustments,
        final          = final_rnd,
        decision       = decision,
        coverage_ratio = coverage_ratio,
    )
