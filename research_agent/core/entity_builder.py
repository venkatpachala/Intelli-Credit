"""
core/entity_builder.py
=======================
Converts a validated ResearchRequest into an EntityProfile.

Responsibilities:
  - Map input fields to internal canonical model
  - Infer city from CIN state code
  - Infer sector from NIC code embedded in CIN
  - Build disambiguation tokens for news relevance filtering
"""

from __future__ import annotations

from core.entity_profile import EntityProfile, LoanProfile, PromoterProfile, QualitativeNoteProfile
from core.input_contract import ResearchRequest

# ── CIN State Code → City mapping ────────────────────────────
# CIN characters 8-9 are the state code (e.g. MH = Maharashtra)
_STATE_CODE_TO_CITY: dict[str, str] = {
    "MH": "Mumbai",
    "DL": "New Delhi",
    "KA": "Bengaluru",
    "TN": "Chennai",
    "GJ": "Ahmedabad",
    "WB": "Kolkata",
    "TS": "Hyderabad",
    "AP": "Hyderabad",
    "RJ": "Jaipur",
    "UP": "Lucknow",
    "HR": "Gurugram",
    "PB": "Chandigarh",
    "MP": "Bhopal",
    "OR": "Bhubaneswar",
    "KL": "Kochi",
    "BR": "Patna",
    "JH": "Ranchi",
    "HP": "Shimla",
    "UK": "Dehradun",
    "GA": "Panaji",
    "CH": "Chandigarh",
}

# ── NIC code range → Sector mapping ──────────────────────────
# CIN characters 2-6 are the NIC activity code
_NIC_TO_SECTOR: list[tuple[range, str]] = [
    (range(1000, 3000),    "Agriculture"),
    (range(5000, 10000),   "Mining & Quarrying"),
    (range(10000, 33000),  "Manufacturing"),
    (range(33000, 35000),  "Electricity & Utilities"),
    (range(35000, 39000),  "Water & Waste Management"),
    (range(41000, 44000),  "Construction"),
    (range(45000, 48000),  "Wholesale & Retail Trade"),
    (range(49000, 54000),  "Transport & Logistics"),
    (range(55000, 57000),  "Hospitality"),
    (range(58000, 64000),  "Information & Communication"),
    (range(64000, 67000),  "Financial Services"),
    (range(68000, 69000),  "Real Estate"),
    (range(69000, 76000),  "Professional Services"),
    (range(77000, 83000),  "Administrative Services"),
    (range(85000, 86000),  "Education"),
    (range(86000, 89000),  "Healthcare"),
    (range(90000, 94000),  "Arts & Entertainment"),
    (range(94000, 97000),  "Other Services"),
]


def _infer_city(cin: str) -> str | None:
    """Extract state code from CIN (chars 8–9) → city."""
    try:
        state_code = cin[7:9]    # e.g. "MH"
        return _STATE_CODE_TO_CITY.get(state_code)
    except Exception:
        return None


def _infer_sector(cin: str) -> str | None:
    """Extract NIC code from CIN (chars 2–6) → sector."""
    try:
        nic_code = int(cin[1:6])
        for code_range, sector in _NIC_TO_SECTOR:
            if nic_code in code_range:
                return sector
    except (ValueError, IndexError):
        pass
    return None


def _clean_search_name(legal_name: str) -> str:
    """
    Strip common suffixes to get a shorter, news-friendly search name.
    'Shree Ram Textiles Pvt Ltd' → 'Shree Ram Textiles'
    """
    suffixes = [
        "Private Limited", "Pvt Ltd", "Pvt. Ltd.", "Pvt. Ltd",
        "Limited", "Ltd.", "Ltd", "LLP", "OPC", "Partnership",
    ]
    name = legal_name.strip()
    for suffix in suffixes:
        if name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)].strip().rstrip(",").strip()
            break
    return name


def build_entity_profile(request: ResearchRequest) -> EntityProfile:
    """
    Convert a validated ResearchRequest → EntityProfile.

    Parameters
    ----------
    request : ResearchRequest
        Validated inbound payload from the API layer.

    Returns
    -------
    EntityProfile
        Internal canonical entity ready to be consumed by all sources.
    """
    city   = _infer_city(request.cin)
    sector = _infer_sector(request.cin)

    # Build disambiguation tokens for news relevance filtering
    tokens: list[str] = []
    if city:
        tokens.append(city)
    if sector:
        tokens.append(sector)
    # Add CIN state prefix as extra token
    tokens.append(request.cin[7:9])   # e.g. "MH"

    promoters = [
        PromoterProfile(
            name=p.name,
            din=p.din,
            pan=p.pan,
            designation=p.designation,
            shareholding_pct=p.shareholding_pct,
        )
        for p in request.promoters
    ]

    loan = LoanProfile(
        amount=request.loan.amount,
        purpose=request.loan.purpose,
        loan_type=request.loan.loan_type,
        tenor_months=request.loan.tenor_months,
    )

    notes = [
        QualitativeNoteProfile(
            author=n.author,
            date=n.date,
            content=n.content
        )
        for n in request.qualitative_notes
    ]

    return EntityProfile(
        case_id=request.case_id,
        legal_name=request.company_name,
        search_name=_clean_search_name(request.company_name),
        cin=request.cin,
        pan=request.pan,
        gstin=request.gstin,
        promoters=promoters,
        loan=loan,
        qualitative_notes=notes,
        sector=sector,
        city=city,
        disambiguation_tokens=tokens,
    )
