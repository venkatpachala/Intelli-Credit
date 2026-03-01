"""
core/entity_profile.py
======================
EntityProfile is the internal canonical representation of a loan applicant.
It is built from InputContract by entity_builder.py and consumed by all 5 sources.

All sources depend on this model — do NOT rename public attributes or methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class QualitativeNoteProfile:
    """Qualitative notes from due diligence or site visits."""
    author:  str
    date:    str
    content: str


@dataclass
class PromoterProfile:
    """A single director / promoter of the borrowing company."""
    name:             str
    din:              Optional[str]   = None
    pan:              Optional[str]   = None
    designation:      Optional[str]   = None
    shareholding_pct: float           = 0.0


@dataclass
class LoanProfile:
    """Details of the loan being applied for."""
    amount:        int    = 0
    purpose:       str    = ""
    loan_type:     str    = ""
    tenor_months:  int    = 0


@dataclass
class EntityProfile:
    """
    Canonical, source-agnostic representation of the borrowing entity.

    Attributes
    ----------
    case_id          : Unique loan application reference
    legal_name       : Full registered legal name (used for DB / RBI lookup)
    search_name      : Shorter name used in news/web queries (strip "Pvt Ltd" etc.)
    cin              : Corporate Identity Number (mandatory)
    pan              : Company PAN (mandatory)
    gstin            : GSTIN (mandatory)
    promoters        : List of directors / key persons
    loan             : Loan profile
    sector           : Inferred industry sector (populated by entity_builder)
    city             : Registered city (populated from CIN state code)
    disambiguation_tokens : Extra tokens (city, sector) used to verify news relevance
    """

    case_id:      str
    legal_name:   str
    search_name:  str
    cin:          str
    pan:          str
    gstin:        str
    promoters:    List[PromoterProfile] = field(default_factory=list)
    loan:         LoanProfile           = field(default_factory=LoanProfile)
    qualitative_notes: List[QualitativeNoteProfile] = field(default_factory=list)
    sector:       Optional[str]         = None
    city:         Optional[str]         = None
    disambiguation_tokens: List[str]    = field(default_factory=list)

    # ── Convenience helpers ───────────────────────────────────

    def primary_promoter(self) -> Optional[PromoterProfile]:
        """Return the promoter with the highest shareholding."""
        if not self.promoters:
            return None
        return max(self.promoters, key=lambda p: p.shareholding_pct)

    def all_promoter_names(self) -> List[str]:
        """Return all promoter names (for relevance filtering in news)."""
        return [p.name for p in self.promoters]

    def all_dins(self) -> List[str]:
        """Return all DINs that are not None."""
        return [p.din for p in self.promoters if p.din]

    def all_pans(self) -> List[str]:
        """Return company PAN + all promoter PANs."""
        pans = [self.pan] if self.pan else []
        pans += [p.pan for p in self.promoters if p.pan]
        return pans
