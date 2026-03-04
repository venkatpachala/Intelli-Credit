"""
cam_engine/scoring/financial_scorer.py
=======================================
Scores the four financial dimensions of the Five Cs:
  Capacity   (DSCR, ICR, CFO, Revenue growth)
  Capital    (Net Worth, D/E, Tangible NW, Working Capital ratio)
  Collateral (Coverage ratio, charge rank, distress value quality)
  GST Quality(Filing compliance, 2A/3B reconciliation, bank correlation)

Each scorer returns (normalised_score: int, breakdown: List[ScoreBreakdown])
so every point awarded is traceable in the CAM document.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from .models import DimensionScore, ScoreBreakdown, score_to_color


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _val(obj: Any, *keys: str, fallback: float = 0.0) -> float:
    """Deep-get a value that may be a plain number or a {'value': N} dict."""
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k, fallback)
        else:
            return fallback
    if isinstance(obj, dict):
        return float(obj.get("value", fallback) or fallback)
    try:
        return float(obj or fallback)
    except (TypeError, ValueError):
        return fallback


def _list_values(obj: Any, *keys: str) -> List[float]:
    """Extract a list of floats from nested dict (period → {value:N})."""
    container = obj
    for k in keys:
        if not isinstance(container, dict):
            return []
        container = container.get(k, {})
    if not isinstance(container, dict):
        return []
    out = []
    for v in container.values():
        if isinstance(v, dict):
            val = v.get("value", None)
        else:
            val = v
        try:
            out.append(float(val))
        except (TypeError, ValueError):
            pass
    return out


def _cagr(values: List[float]) -> float:
    """Compute CAGR from a list of annual values (first → last)."""
    if len(values) < 2 or values[0] <= 0:
        return 0.0
    n = len(values) - 1
    try:
        return ((values[-1] / values[0]) ** (1 / n) - 1) * 100
    except (ZeroDivisionError, ValueError):
        return 0.0


def _make_dim(name: str, weight: float, raw_pts: int, max_pts: int,
              breakdown: List[ScoreBreakdown]) -> DimensionScore:
    """Normalise raw points to 0–100 and wrap as DimensionScore."""
    score = max(0, min(100, round(raw_pts / max_pts * 100)))
    return DimensionScore(
        name=name, score=score, weight=weight,
        weighted=round(score * weight, 2),
        breakdown=breakdown,
        color=score_to_color(score),
    )


# ─────────────────────────────────────────────────────────────
# 1. Capacity Score
# ─────────────────────────────────────────────────────────────

def score_capacity(extraction: Dict) -> DimensionScore:
    """
    Repayment ability.
    Max raw points = 100 (DSCR 40 + ICR 25 + CFO 20 + Growth 15)
    Deductions for late GST filings (max -10).
    """
    pts = 0
    bd:  List[ScoreBreakdown] = []

    credit_m = extraction.get("credit_metrics", {})
    income   = extraction.get("income_statement", {})
    cash_f   = extraction.get("cash_flow", {})
    gst      = extraction.get("gst_data", {})
    finance_cost = extraction.get("finance_cost", {})

    # ── DSCR (40 pts) ────────────────────────────────────────
    dscr_val = _val(credit_m, "dscr")
    if dscr_val == 0:
        # Try compound from ICR + PAT as fallback
        dscr_val = _val(credit_m, "interest_coverage_ratio")

    if dscr_val >= 2.0:
        d, label = 40, f"DSCR {dscr_val:.2f}x → 40 pts (excellent, ≥2.0x)"
    elif dscr_val >= 1.5:
        d, label = 30, f"DSCR {dscr_val:.2f}x → 30 pts (good, 1.5–2.0x)"
    elif dscr_val >= 1.25:
        d, label = 20, f"DSCR {dscr_val:.2f}x → 20 pts (adequate, 1.25–1.5x)"
    elif dscr_val > 0:
        d, label = 5, f"DSCR {dscr_val:.2f}x → 5 pts (below RBI minimum 1.25x)"
    else:
        d, label = 0, "DSCR not available — 0 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=40,
                             benchmark="Benchmark: DSCR ≥2.0x = 40pts, ≥1.5x = 30pts, ≥1.25x = 20pts"))

    # ── Interest Coverage Ratio (25 pts) ─────────────────────
    icr_raw = credit_m.get("interest_coverage_ratio", {})
    if isinstance(icr_raw, dict):
        # Take latest period value
        icr_vals = [_val(icr_raw, k) for k in icr_raw.keys()]
        icr_val  = icr_vals[-1] if icr_vals else 0.0
    else:
        icr_val = _val(credit_m, "interest_coverage_ratio")

    if icr_val >= 4.0:
        d, label = 25, f"ICR {icr_val:.2f}x → 25 pts (strong, ≥4x)"
    elif icr_val >= 3.0:
        d, label = 20, f"ICR {icr_val:.2f}x → 20 pts (good, 3–4x)"
    elif icr_val >= 2.0:
        d, label = 12, f"ICR {icr_val:.2f}x → 12 pts (moderate, 2–3x)"
    elif icr_val > 0:
        d, label = 3, f"ICR {icr_val:.2f}x → 3 pts (weak, <2x)"
    else:
        d, label = 0, "ICR not available — 0 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=25,
                             benchmark="Benchmark: ICR ≥4x = 25pts, ≥3x = 20pts, ≥2x = 12pts"))

    # ── CFO Trend (20 pts) ───────────────────────────────────
    cfo_vals = _list_values(cash_f, "cfo")
    if not cfo_vals:
        # try extraction root
        cfo_vals = _list_values(extraction, "cash_flow", "cfo")
    
    if len(cfo_vals) >= 3:
        positive_years = sum(1 for v in cfo_vals[-3:] if v > 0)
        latest_cfo_neg = cfo_vals[-1] < 0
    elif len(cfo_vals) == 2:
        positive_years = sum(1 for v in cfo_vals if v > 0)
        latest_cfo_neg = cfo_vals[-1] < 0
    else:
        positive_years = 0
        latest_cfo_neg = True

    if positive_years >= 3 and not latest_cfo_neg:
        d, label = 20, "CFO positive all 3 years → 20 pts"
    elif positive_years >= 2 and not latest_cfo_neg:
        d, label = 13, f"CFO positive {positive_years}/3 years → 13 pts"
    elif positive_years == 1 and not latest_cfo_neg:
        d, label = 7, "CFO positive latest year only → 7 pts"
    elif latest_cfo_neg:
        d, label = 0, "CFO negative in latest year → 0 pts (cash drain)"
    else:
        d, label = 8, "CFO data limited — partial credit 8 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=20,
                             benchmark="Benchmark: CFO positive all 3 years = 20pts"))

    # ── Revenue CAGR (15 pts) ────────────────────────────────
    rev_values = _list_values(income, "total_revenue")
    rev_cagr   = _cagr(rev_values) if len(rev_values) >= 2 else 0.0

    if rev_cagr >= 20:
        d, label = 15, f"Revenue CAGR {rev_cagr:.1f}% → 15 pts (strong ≥20%)"
    elif rev_cagr >= 10:
        d, label = 10, f"Revenue CAGR {rev_cagr:.1f}% → 10 pts (good 10–20%)"
    elif rev_cagr >= 0:
        d, label = 5, f"Revenue CAGR {rev_cagr:.1f}% → 5 pts (flat/slow 0–10%)"
    else:
        d, label = 0, f"Revenue CAGR {rev_cagr:.1f}% → 0 pts (declining revenue)"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=15,
                             benchmark="Benchmark: CAGR ≥20% = 15pts, ≥10% = 10pts"))

    # ── GST Late Filing Deduction (max -10) ──────────────────
    late_filings = int(gst.get("late_filings_count", 0) or 0)
    compliance   = float(gst.get("filing_compliance_pct", 100) or 100)
    if compliance < 100:
        estimated_late = max(late_filings, round((100 - compliance) / 10))
    else:
        estimated_late = 0
    
    deduction = min(10, estimated_late * 2)
    if deduction > 0:
        pts -= deduction
        bd.append(ScoreBreakdown(
            label=f"GST late filings penalty: -{deduction} pts ({estimated_late} late returns)",
            points=-deduction, max_points=0,
            benchmark="Penalty: 2 pts per late GSTR-3B filing, max deduction 10 pts"
        ))

    return _make_dim("Capacity", 0.25, pts, 100, bd)


# ─────────────────────────────────────────────────────────────
# 2. Capital Score
# ─────────────────────────────────────────────────────────────

def score_capital(extraction: Dict) -> DimensionScore:
    """
    Balance sheet strength — skin in the game.
    Max raw pts = 100 (NW 30 + D/E 35 + Tangible NW 20 + WC ratio 15)
    """
    pts = 0
    bd:  List[ScoreBreakdown] = []

    bs = extraction.get("balance_sheet", {})
    cm = extraction.get("credit_metrics", {})

    # ── Net Worth (30 pts) ───────────────────────────────────
    nw = _val(bs, "net_worth")
    if nw == 0:
        # Try via equity = total_assets - total_debt
        ta = _val(bs, "total_assets")
        td = _val(bs, "total_debt")
        nw = max(0.0, ta - td) if ta and td else 0.0

    if nw >= 1000:       # ₹1000 Cr+
        d, label = 30, f"Net Worth ₹{nw:.0f} Cr → 30 pts (very strong)"
    elif nw >= 500:
        d, label = 25, f"Net Worth ₹{nw:.0f} Cr → 25 pts (strong)"
    elif nw >= 100:
        d, label = 20, f"Net Worth ₹{nw:.0f} Cr → 20 pts (adequate)"
    elif nw >= 10:
        d, label = 14, f"Net Worth ₹{nw:.0f} Cr → 14 pts (modest)"
    elif nw > 0:
        d, label = 5, f"Net Worth ₹{nw:.0f} Cr → 5 pts (very thin)"
    else:
        d, label = 0, "Net Worth not available — 0 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=30,
                             benchmark="Benchmark: NW ≥₹1000 Cr = 30pts, ≥₹500 Cr = 25pts"))

    # ── D/E Ratio (35 pts) ───────────────────────────────────
    de = _val(cm, "debt_equity")
    if de == 0:
        de_raw = bs.get("gearing_ratio", {})
        if isinstance(de_raw, dict):
            de_vals = [_val(de_raw, k) for k in de_raw.keys()]
            de = de_vals[-1] if de_vals else 0.0

    if de == 0:
        # Estimate from total_debt / net_worth
        td = _val(bs, "total_debt")
        if nw > 0 and td > 0:
            de = td / nw

    if 0 < de <= 1.0:
        d, label = 35, f"D/E {de:.2f}x → 35 pts (low leverage ≤1x)"
    elif de <= 2.0:
        d, label = 27, f"D/E {de:.2f}x → 27 pts (moderate 1–2x)"
    elif de <= 3.0:
        d, label = 16, f"D/E {de:.2f}x → 16 pts (elevated 2–3x)"
    elif de > 3.0:
        d, label = 5, f"D/E {de:.2f}x → 5 pts (high leverage above 3x)"
    else:
        d, label = 20, "D/E not computed — neutral 20 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=35,
                             benchmark="Benchmark: D/E ≤1x = 35pts, ≤2x = 27pts, ≤3x = 16pts"))

    # ── Tangible Net Worth (20 pts) ──────────────────────────
    tnw = _val(bs, "tangible_net_worth")
    if tnw == 0:
        tnw = nw  # assume no intangibles if not reported

    tnw_pct = (tnw / nw * 100) if nw > 0 else 100.0

    if tnw_pct >= 95:
        d, label = 20, f"Tangible NW {tnw_pct:.0f}% of NW → 20 pts (very clean)"
    elif tnw_pct >= 80:
        d, label = 15, f"Tangible NW {tnw_pct:.0f}% of NW → 15 pts (good)"
    elif tnw_pct >= 60:
        d, label = 8, f"Tangible NW {tnw_pct:.0f}% of NW → 8 pts (moderate intangibles)"
    else:
        d, label = 3, f"Tangible NW {tnw_pct:.0f}% of NW → 3 pts (high intangibles)"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=20,
                             benchmark="Benchmark: Tangible NW ≥95% of NW = 20pts"))

    # ── Working Capital Ratio (15 pts) ───────────────────────
    ca  = _val(bs, "current_assets")
    cl  = _val(bs, "current_liabilities")
    wcr = (ca / cl) if cl > 0 else 0.0
    cr  = _val(cm, "current_ratio") or wcr

    if cr >= 2.0:
        d, label = 15, f"Current Ratio {cr:.2f}x → 15 pts (healthy ≥2x)"
    elif cr >= 1.5:
        d, label = 10, f"Current Ratio {cr:.2f}x → 10 pts (adequate 1.5–2x)"
    elif cr >= 1.0:
        d, label = 5, f"Current Ratio {cr:.2f}x → 5 pts (tight 1–1.5x)"
    elif cr > 0:
        d, label = 0, f"Current Ratio {cr:.2f}x → 0 pts (below 1x, stress)"
    else:
        d, label = 7, "Current Ratio not available — neutral 7 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=15,
                             benchmark="Benchmark: Current Ratio ≥2x = 15pts"))

    return _make_dim("Capital", 0.20, pts, 100, bd)


# ─────────────────────────────────────────────────────────────
# 3. Collateral Score
# ─────────────────────────────────────────────────────────────

def score_collateral(extraction: Dict, requested_amount: float = 0) -> DimensionScore:
    """
    Security coverage and quality.
    Max raw pts = 100 (Coverage 50 + Charge rank 20 + Pledge status 15 + Distress quality 15)
    """
    pts = 0
    bd:  List[ScoreBreakdown] = []

    assets = extraction.get("collateral_data", [])
    if not assets:
        # Attempt to read from credit_metrics existing_credit_facilities
        # No collateral data reported — use neutral scoring
        bd.append(ScoreBreakdown(
            label="Collateral data not available — neutral 50 pts",
            points=50, max_points=100,
            benchmark="Upload collateral statement for full scoring"
        ))
        return _make_dim("Collateral", 0.15, 50, 100, bd)

    total_market  = sum(float(a.get("market_value", 0) or 0)  for a in assets)
    total_distress= sum(float(a.get("distress_value", 0) or 0) for a in assets)

    # Use loan_amount from extraction if requested_amount not provided
    if requested_amount <= 0:
        requested_amount = _val(extraction, "loan", "amount_inr")
    if requested_amount <= 0:
        requested_amount = total_market / 1.5  # fallback assumption

    coverage = (total_market / requested_amount) if requested_amount > 0 else 0.0

    # ── Coverage Ratio (50 pts) ──────────────────────────────
    if coverage >= 2.0:
        d, label = 50, f"Coverage Ratio {coverage:.2f}x → 50 pts (excellent ≥2x)"
    elif coverage >= 1.5:
        d, label = 40, f"Coverage Ratio {coverage:.2f}x → 40 pts (adequate 1.5–2x)"
    elif coverage >= 1.25:
        d, label = 25, f"Coverage Ratio {coverage:.2f}x → 25 pts (below preferred 1.25–1.5x)"
    elif coverage > 0:
        d, label = 10, f"Coverage Ratio {coverage:.2f}x → 10 pts (insufficient <1.25x)"
    else:
        d, label = 0, "Coverage Ratio 0 — no collateral quantified"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=50,
                             benchmark="Benchmark: Coverage ≥2x = 50pts, ≥1.5x = 40pts (preferred)"))

    # ── Charge Rank (20 pts) ─────────────────────────────────
    charges = [str(a.get("charge", "")).lower() for a in assets]
    if any("first" in c or "exclusive" in c for c in charges):
        d, label = 20, "First/exclusive charge on collateral → 20 pts"
    elif any("second" in c or "pari passu" in c for c in charges):
        d, label = 10, "Second / pari passu charge → 10 pts"
    elif charges and charges[0]:
        d, label = 5, f"Third or lower charge → 5 pts"
    else:
        d, label = 12, "Charge rank not specified — neutral 12 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=20,
                             benchmark="Benchmark: First charge = 20pts, Second/pari passu = 10pts"))

    # ── Pledge Status (15 pts) ───────────────────────────────
    pledged = [a for a in assets if a.get("pledged", False)]
    if not pledged:
        d, label = 15, "No assets pledged elsewhere → 15 pts"
    elif len(pledged) < len(assets):
        d, label = 8, f"{len(pledged)}/{len(assets)} assets pledged elsewhere → 8 pts"
    else:
        d, label = 0, "All assets pledged elsewhere → 0 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=15,
                             benchmark="Benchmark: No pledges = 15pts"))

    # ── Distress Value Quality (15 pts) ──────────────────────
    if total_market > 0:
        distress_pct = total_distress / total_market * 100
    else:
        distress_pct = 70.0

    if distress_pct >= 75:
        d, label = 15, f"Distress value {distress_pct:.0f}% of market → 15 pts (liquid assets)"
    elif distress_pct >= 55:
        d, label = 8, f"Distress value {distress_pct:.0f}% of market → 8 pts (semi-liquid)"
    else:
        d, label = 2, f"Distress value {distress_pct:.0f}% of market → 2 pts (illiquid)"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=15,
                             benchmark="Benchmark: Distress ≥75% of market = 15pts"))

    return _make_dim("Collateral", 0.15, pts, 100, bd)


# ─────────────────────────────────────────────────────────────
# 4. GST Quality Score
# ─────────────────────────────────────────────────────────────

def score_gst_quality(extraction: Dict) -> DimensionScore:
    """
    GST compliance quality — filing compliance + bank reconciliation + EMI behaviour.
    Max raw pts = 100.
    """
    pts = 0
    bd:  List[ScoreBreakdown] = []

    gst  = extraction.get("gst_data", {})
    bank = extraction.get("banking_data", {})

    # ── Filing Compliance % (40 pts) ─────────────────────────
    compliance = float(gst.get("filing_compliance_pct", -1) or -1)
    if compliance < 0:
        # not available — neutral
        d, label = 28, "GST filing compliance not available — neutral 28 pts"
    elif compliance >= 95:
        d, label = 40, f"GST filing compliance {compliance:.0f}% → 40 pts (exemplary)"
    elif compliance >= 90:
        d, label = 32, f"GST filing compliance {compliance:.0f}% → 32 pts (good)"
    elif compliance >= 80:
        d, label = 20, f"GST filing compliance {compliance:.0f}% → 20 pts (acceptable)"
    else:
        d, label = 5, f"GST filing compliance {compliance:.0f}% → 5 pts (poor)"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=40,
                             benchmark="Benchmark: ≥95% compliance = 40pts, ≥90% = 32pts"))

    # ── GSTR-2A vs 3B Reconciliation (30 pts) ────────────────
    variance_pct = float(gst.get("gstr2a_variance_pct", -1) or -1)
    if variance_pct < 0:
        d, label = 20, "GSTR-2A/3B reconciliation data not available — neutral 20 pts"
    elif variance_pct <= 5:
        d, label = 30, f"GSTR-2A/3B variance {variance_pct:.1f}% → 30 pts (tight reconciliation)"
    elif variance_pct <= 15:
        d, label = 20, f"GSTR-2A/3B variance {variance_pct:.1f}% → 20 pts (acceptable gap)"
    else:
        d, label = 5, f"GSTR-2A/3B variance {variance_pct:.1f}% → 5 pts (significant discrepancy)"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=30,
                             benchmark="Benchmark: <5% variance = 30pts (suggests authentic transactions)"))

    # ── GST Turnover vs Bank Credits Correlation (20 pts) ────
    gst_turnover  = _val(gst,  "annual_turnover")
    bank_credits  = float(bank.get("annual_credits", 0) or 0)
    if gst_turnover > 0 and bank_credits > 0:
        ratio = min(gst_turnover, bank_credits) / max(gst_turnover, bank_credits)
        if ratio >= 0.85:
            d, label = 20, f"GST↔Bank correlation {ratio:.2f} → 20 pts (strong match)"
        elif ratio >= 0.70:
            d, label = 13, f"GST↔Bank correlation {ratio:.2f} → 13 pts (reasonable match)"
        else:
            d, label = 3, f"GST↔Bank correlation {ratio:.2f} → 3 pts (potential under-reporting)"
    else:
        d, label = 13, "GST↔Bank correlation not computable — neutral 13 pts"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=20,
                             benchmark="Benchmark: Correlation ≥0.85 = 20pts (low under-reporting risk)"))

    # ── EMI / Cheque Bounce Behaviour (10 pts) ───────────────
    bounces = int(bank.get("emi_bounces", 0) or 0)
    if bounces == 0:
        d, label = 10, "0 EMI/ECS bounces → 10 pts (clean banking behaviour)"
    elif bounces <= 2:
        d, label = 5, f"{bounces} EMI bounce(s) → 5 pts (occasional delay)"
    else:
        d, label = 0, f"{bounces} EMI bounces → 0 pts (repeat delinquency)"
    pts += d
    bd.append(ScoreBreakdown(label=label, points=d, max_points=10,
                             benchmark="Benchmark: 0 bounces = 10pts"))

    return _make_dim("GST Quality", 0.05, pts, 100, bd)


# ─────────────────────────────────────────────────────────────
# 5. Research-based Scores (Character, Conditions, Litigation, MCA)
# ─────────────────────────────────────────────────────────────

def score_from_research(research: Dict) -> "ResearchScores":
    """
    Derive the four research-based dimension scores from the research agent output.
    """
    from .models import ResearchScores

    flags = research.get("flags", [])
    tags  = research.get("tags", [])
    base  = research.get("risk_score", 70)

    # ── Character = Promoter Integrity ───────────────────────
    promoter_flags = [f for f in flags if f.get("category") in ("PROMOTER", "FRAUD")]
    critical_p = sum(1 for f in promoter_flags if f.get("severity") == "CRITICAL")
    high_p     = sum(1 for f in promoter_flags if f.get("severity") == "HIGH")
    medium_p   = sum(1 for f in promoter_flags if f.get("severity") == "MEDIUM")

    char_score = 100 - (critical_p * 40) - (high_p * 15) - (medium_p * 5)
    char_score = max(0, min(100, char_score))
    if "WILFUL_DEFAULTER" in tags or "AUTO_REJECT" in tags:
        char_score = 0

    char_dim = DimensionScore(
        name="Character", score=char_score, weight=0.20,
        weighted=round(char_score * 0.20, 2),
        color=score_to_color(char_score),
        breakdown=[ScoreBreakdown(
            label=f"Promoter integrity: {critical_p} CRITICAL, {high_p} HIGH, {medium_p} MEDIUM flags",
            points=char_score, max_points=100,
            benchmark="Research agent: RBI + MCA + News promoter signals"
        )]
    )

    # ── Conditions = Sector Outlook ──────────────────────────
    sector_flags = [f for f in flags if f.get("category") == "SECTOR"]
    sector_headwind = any("headwind" in t.lower() or "stress" in t.lower() for t in tags)
    cond_score = 80
    if sector_headwind:
        cond_score -= 20
    cond_score -= len(sector_flags) * 5
    cond_score = max(30, min(100, cond_score))

    cond_dim = DimensionScore(
        name="Conditions", score=cond_score, weight=0.10,
        weighted=round(cond_score * 0.10, 2),
        color=score_to_color(cond_score),
        breakdown=[ScoreBreakdown(
            label=f"Sector outlook: {len(sector_flags)} sector flags, headwind={'Yes' if sector_headwind else 'No'}",
            points=cond_score, max_points=100,
            benchmark="Research agent: news signals, sector tags"
        )]
    )

    # ── Litigation Risk ───────────────────────────────────────
    lit_flags = [f for f in flags if f.get("category") == "LITIGATION"]
    critical_l = sum(1 for f in lit_flags if f.get("severity") == "CRITICAL")
    high_l     = sum(1 for f in lit_flags if f.get("severity") == "HIGH")
    medium_l   = sum(1 for f in lit_flags if f.get("severity") == "MEDIUM")

    lit_score = 100 - (critical_l * 40) - (high_l * 20) - (medium_l * 8)
    lit_score = max(0, min(100, lit_score))

    lit_dim = DimensionScore(
        name="Litigation Risk", score=lit_score, weight=0.03,
        weighted=round(lit_score * 0.03, 2),
        color=score_to_color(lit_score),
        breakdown=[ScoreBreakdown(
            label=f"eCourts: {len(lit_flags)} litigation flags ({critical_l} CRITICAL, {high_l} HIGH)",
            points=lit_score, max_points=100,
            benchmark="Research agent: eCourts litigation check"
        )]
    )

    # ── MCA Compliance ───────────────────────────────────────
    mca_flags = [f for f in flags if f.get("source") == "MCA" or f.get("category") == "REGULATORY"]
    high_m    = sum(1 for f in mca_flags if f.get("severity") == "HIGH")
    medium_m  = sum(1 for f in mca_flags if f.get("severity") == "MEDIUM")

    mca_score = 100 - (high_m * 20) - (medium_m * 8)
    mca_score = max(0, min(100, mca_score))

    mca_dim = DimensionScore(
        name="MCA Compliance", score=mca_score, weight=0.02,
        weighted=round(mca_score * 0.02, 2),
        color=score_to_color(mca_score),
        breakdown=[ScoreBreakdown(
            label=f"MCA21: {len(mca_flags)} flags ({high_m} HIGH, {medium_m} MEDIUM)",
            points=mca_score, max_points=100,
            benchmark="Research agent: ROC filings, charge registry, director history"
        )]
    )

    from .models import ResearchScores
    return ResearchScores(
        character=char_dim,
        conditions=cond_dim,
        litigation_risk=lit_dim,
        mca_compliance=mca_dim,
    )
