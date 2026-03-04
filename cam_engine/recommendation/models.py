"""
cam_engine/recommendation/models.py
=====================================
Pydantic models for loan amount and interest rate recommendation.
Every adjustment and premium is individually recorded so the CAM
can print a full derivation chain.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class Adjustment(BaseModel):
    """One multiplicative step in the amount derivation chain."""
    factor:  float   # e.g. 0.90
    reason:  str     # "D/E 1.26x — above 1x, below 2x"
    before:  float   # amount before this adjustment
    after:   float   # amount after this adjustment


class AmountRecommendation(BaseModel):
    """Full derivation of the recommended loan amount."""
    requested:    float
    wc_gap:       float              # working capital gap (ceiling)
    base:         float              # min(requested, wc_gap)
    adjustments:  List[Adjustment] = []
    final:        float              # recommended amount (rounded)
    decision:     str                # APPROVE | CONDITIONAL | REJECT
    coverage_ratio: float = 0.0     # collateral / requested (stored for rate engine)
    rejection_reason: Optional[str] = None


class Premium(BaseModel):
    """One additive component of the interest rate."""
    bps:    int      # basis points (e.g. 25 = 0.25%)
    reason: str      # "DSCR 1.84x — tight 1.25–1.5x band"
    source: str      # "FINANCIAL" | "RESEARCH" | "REGULATORY"


class RateRecommendation(BaseModel):
    """Full derivation of the recommended interest rate."""
    base_rate:         float          # e.g. 9.50
    premiums:          List[Premium] = []
    total_premium_bps: int            # sum of all premiums (capped)
    final_rate:        float          # base + total_premium/100
    rate_band:         str            # "9.50% + 1.00% = 10.50%"


class LoanRecommendation(BaseModel):
    """Complete recommendation — amount + rate + conditions."""
    amount:                AmountRecommendation
    rate:                  RateRecommendation
    decision:              str               # APPROVE | CONDITIONAL | REJECT
    recommended_amount_cr: float             # in crores
    requested_amount_cr:   float
    recommended_rate:      float
    conditions_precedent:  List[str] = []
    covenants:             List[str] = []
