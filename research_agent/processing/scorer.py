"""
processing/scorer.py
====================
Compute the final risk score from aggregated flags.

Scoring model
-------------
Base score : 100
Each ResearchFlag has a score_impact (negative value).
Auto-reject : if any CRITICAL flag scores -100 (RBI wilful defaulter).

Final score is clamped to [0, 100].
"""

from __future__ import annotations

from typing import List, Tuple

from core.output_contract import ResearchFlag, Severity


def compute_score(
    flags: List[ResearchFlag],
    settings,
) -> Tuple[int, bool]:
    """
    Compute (risk_score, auto_reject).

    Parameters
    ----------
    flags    : All ResearchFlag objects from all sources combined.
    settings : App settings (provides base_score).

    Returns
    -------
    risk_score  : int  — 0 to 100
    auto_reject : bool — True if any flag is CRITICAL with score_impact <= -100
    """
    auto_reject = False
    total_deduction = 0

    for flag in flags:
        # Check for hard auto-reject (e.g. RBI wilful defaulter)
        if flag.severity == Severity.CRITICAL and flag.score_impact <= -100:
            auto_reject = True

        # Weight deduction by confidence
        weighted = abs(flag.score_impact) * flag.confidence
        total_deduction += weighted

    raw_score  = settings.base_score - int(total_deduction)
    risk_score = max(0, min(100, raw_score))

    return risk_score, auto_reject
