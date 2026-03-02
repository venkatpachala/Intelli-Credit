"""
processing/tagger.py
====================
Assigns human-readable tags to the ResearchOutput based on
the flags raised and the risk band computed.

Tags are short strings used by the frontend to filter/display results,
e.g. ["AUTO_REJECT", "WILFUL_DEFAULTER", "LITIGATION_RISK", "HIGH_RISK"]
"""

from __future__ import annotations

from typing import List

from core.entity_profile import EntityProfile
from core.output_contract import (
    DataSource, FlagCategory, ResearchFlag, RiskBand, Severity,
)


def assign_tags(
    flags: List[ResearchFlag],
    entity: EntityProfile,
    risk_band: RiskBand,
) -> List[str]:
    """
    Derive a sorted, deduplicated list of string tags.

    Parameters
    ----------
    flags     : All merged flags from all sources.
    entity    : EntityProfile (used for loan context).
    risk_band : Computed RiskBand from scorer.

    Returns
    -------
    List[str] of unique tags, sorted alphabetically.
    """
    tags: set[str] = set()

    # ── Risk band tags ────────────────────────────────────────
    tags.add(f"{risk_band.value}_BAND")

    # ── Auto-reject ───────────────────────────────────────────
    for flag in flags:
        if flag.severity == Severity.CRITICAL and flag.score_impact <= -100:
            tags.add("AUTO_REJECT")
            tags.add("WILFUL_DEFAULTER")

    # ── Flag-based tags ───────────────────────────────────────
    categories_seen = {f.category for f in flags}
    sources_seen    = {f.source   for f in flags}

    if FlagCategory.FRAUD in categories_seen:
        tags.add("FRAUD_RISK")
    if FlagCategory.LITIGATION in categories_seen:
        tags.add("LITIGATION_RISK")
    if FlagCategory.FINANCIAL in categories_seen:
        tags.add("FINANCIAL_RISK")
    if FlagCategory.REGULATORY in categories_seen:
        tags.add("REGULATORY_RISK")
    if FlagCategory.PROMOTER in categories_seen:
        tags.add("PROMOTER_CONCERN")

    # ── Source-based tags ─────────────────────────────────────
    if DataSource.RBI in sources_seen:
        tags.add("RBI_FLAGGED")
    if DataSource.ECOURTS in sources_seen:
        tags.add("COURT_CASES_FOUND")
    if DataSource.NEWS in sources_seen:
        tags.add("NEWS_SIGNALS_FOUND")
    if DataSource.GSTN in sources_seen:
        tags.add("GST_ISSUE")

    # ── Severity summary tags ─────────────────────────────────
    critical_count = sum(1 for f in flags if f.severity == Severity.CRITICAL)
    high_count     = sum(1 for f in flags if f.severity == Severity.HIGH)

    if critical_count >= 1:
        tags.add("HAS_CRITICAL_FLAGS")
    if high_count >= 2:
        tags.add("MULTIPLE_HIGH_FLAGS")

    # ── Verification required tag ─────────────────────────────
    if any(f.requires_verification for f in flags):
        tags.add("MANUAL_VERIFICATION_REQUIRED")

    # ── Loan-size context ─────────────────────────────────────
    if entity.loan.amount >= 100_000_000:      # ≥ ₹1 Cr
        tags.add("LARGE_TICKET")
    if entity.loan.amount >= 500_000_000:      # ≥ ₹5 Cr
        tags.add("VERY_LARGE_TICKET")

    # ── Clean band ────────────────────────────────────────────
    if not flags:
        tags.add("CLEAN_PROFILE")

    return sorted(tags)
