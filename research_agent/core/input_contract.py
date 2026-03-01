"""
core/input_contract.py
======================
Pydantic models for validating inbound JSON from the ingestion layer.

Key rules enforced here:
  - case_id, company_name, cin, gstin, pan are ALL mandatory
  - At least one promoter is required
  - Loan block is fully required
  - PAN / CIN / GSTIN are regex-validated for Indian formats
"""

from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────────────────────

class QualitativeNoteInput(BaseModel):
    author:  str = Field(..., description="Name or role of the person providing the note, e.g., 'Credit Officer'")
    date:    str = Field(..., description="Date of the observation (e.g. YYYY-MM-DD)")
    content: str = Field(..., description="Free-text qualitative observation")

class PromoterInput(BaseModel):
    name:             str   = Field(..., min_length=2,
                                    description="Full name of the promoter/director")
    din:              str   = Field(..., description="8-digit Director Identification Number")
    designation:      str   = Field(..., description="e.g. 'Managing Director', 'Director'")
    shareholding_pct: float = Field(..., ge=0.0, le=100.0,
                                    description="Shareholding percentage (0–100)")
    pan:              str | None = Field(None, description="Promoter PAN (optional)")

    @field_validator("din")
    @classmethod
    def validate_din(cls, v: str) -> str:
        if not re.fullmatch(r"\d{8}", v.strip()):
            raise ValueError(f"DIN must be exactly 8 digits, got: {v!r}")
        return v.strip()

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v.strip().upper()):
            raise ValueError(f"Invalid PAN format: {v!r}")
        return v.strip().upper()


class LoanInput(BaseModel):
    amount:       int = Field(..., gt=0,
                              description="Loan amount in INR (e.g. 100000000 = ₹1 Cr)")
    purpose:      str = Field(..., min_length=5,
                              description="Free-text purpose of the loan")
    loan_type:    str = Field(..., description="e.g. 'working_capital', 'term_loan'")
    tenor_months: int = Field(..., gt=0, le=360,
                              description="Loan tenor in months (max 30 years)")


# ─────────────────────────────────────────────────────────────
# Root Input Contract
# ─────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    """
    Validated input from the ingestion layer.

    Mandatory fields
    ----------------
    case_id, company_name, cin, gstin, pan, promoters (≥1), loan, ingestion_version
    """

    case_id:           str          = Field(..., min_length=3,
                                            description="Unique loan-case reference ID")
    company_name:      str          = Field(..., min_length=3,
                                            description="Full registered legal name")
    cin:               str          = Field(...,
                                            description="Corporate Identity Number (mandatory)")
    gstin:             str          = Field(...,
                                            description="GST Identification Number (mandatory)")
    pan:               str          = Field(...,
                                            description="Company PAN (mandatory)")
    promoters:         List[PromoterInput] = Field(..., min_length=1,
                                            description="At least one promoter required")
    loan:              LoanInput    = Field(..., description="Loan details block")
    qualitative_notes: List[QualitativeNoteInput] = Field(default_factory=list,
                                            description="Primary insights from site visits or management interviews")
    ingestion_version: str          = Field(...,
                                            description="Schema version, e.g. UCES_v1")

    # ── Validators ───────────────────────────────────────────

    @field_validator("cin")
    @classmethod
    def validate_cin(cls, v: str) -> str:
        """
        CIN format: L/U + 5 digits + 2 alpha state + 4 digit year
                    + PTC/LLC/etc + 6 digits
        Example: U17100MH2010PTC123456
        """
        pattern = r"[LUlu]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}"
        if not re.fullmatch(pattern, v.strip().upper()):
            raise ValueError(
                f"Invalid CIN format: {v!r}. "
                "Expected format: U17100MH2010PTC123456"
            )
        return v.strip().upper()

    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, v: str) -> str:
        """
        GSTIN: 2 digit state + 10 char PAN + 1 entity num + Z + 1 checksum
        Example: 27AAACS1234A1Z5
        """
        if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]", v.strip().upper()):
            raise ValueError(
                f"Invalid GSTIN format: {v!r}. "
                "Expected format: 27AAACS1234A1Z5"
            )
        return v.strip().upper()

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v.strip().upper()):
            raise ValueError(
                f"Invalid PAN format: {v!r}. "
                "Expected format: AAACS1234A"
            )
        return v.strip().upper()

    @model_validator(mode="after")
    def validate_gstin_pan_consistency(self) -> "ResearchRequest":
        """
        GSTIN characters 3–12 must match the company PAN.
        Example: GSTIN 27AAACS1234A1Z5 → embedded PAN = AAACS1234A
        """
        if self.gstin and self.pan:
            embedded_pan = self.gstin[2:12]
            if embedded_pan.upper() != self.pan.upper():
                raise ValueError(
                    f"GSTIN ({self.gstin}) does not match company PAN ({self.pan}). "
                    f"Characters 3–12 of GSTIN must equal the PAN."
                )
        return self

    @model_validator(mode="after")
    def validate_promoter_shareholding(self) -> "ResearchRequest":
        """Total shareholding across all promoters must not exceed 100%."""
        total = sum(p.shareholding_pct for p in self.promoters)
        if total > 100.0:
            raise ValueError(
                f"Total promoter shareholding ({total:.1f}%) exceeds 100%. "
                "Please check the shareholding_pct values."
            )
        return self
