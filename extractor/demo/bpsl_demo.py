"""
demo/bpsl_demo.py
Hardcoded BPSL (Bhushan Power and Steel Limited) demo data.
Used when no LLM API key is set — allows the full pipeline to run without any API call.

Data sourced from:
    - CARE Ratings Press Release, March 03, 2025
    - ICMAI CIRP Case Study (Performance Analysis of Bhushan Steel)
    - BSE / Wikipedia company profile
    - Business Standard news (May 2025 SC liquidation order)
"""


def get_demo_data() -> list:
    """
    Returns raw text pages simulating what pdfplumber / OCR would extract
    from real BPSL documents. These are the inputs to the LLM structuring step.
    """
    return [
        {
            "page":       1,
            "text":       BPSL_ANNUAL_REPORT_TEXT,
            "source":     "BPSL_Annual_Report_FY2024.pdf",
            "type":       "pdf_text",
            "method":     "pdfplumber",
            "has_tables": True,
        },
        {
            "page":       2,
            "text":       BPSL_CARE_RATINGS_TEXT,
            "source":     "CARE_Rating_BPSL_Mar2025.pdf",
            "type":       "pdf_text",
            "method":     "pdfplumber",
            "has_tables": False,
        },
        {
            "page":       3,
            "text":       BPSL_LEGAL_TEXT,
            "source":     "BPSL_eCourts_Legal_Summary.txt",
            "type":       "txt",
            "method":     "stdlib_open",
            "has_tables": False,
        },
    ]


def get_demo_structured() -> dict:
    """
    Returns pre-structured data as if Claude/GPT-4 had processed the documents.
    This bypasses the LLM API call entirely when no API key is available.
    """
    return {
        "parse_success": True,
        "provider":      "demo_bpsl",
        "fields": {

            # ── COMPANY PROFILE ──────────────────────────────
            "company_profile": {
                "legal_name":         "Bhushan Power and Steel Limited",
                "cin":                "U27100DL1999PLC108350",
                "sector":             "Iron & Steel",
                "incorporation_year": 1999,
                "registered_address": (
                    "4th Floor, A-2, NTH Complex, Shaheed Jeet Singh Marg, "
                    "USO Road, Qutab Institutional Area, South Delhi, New Delhi - 110067"
                ),
                "promoter_name":      "JSW Steel Limited (Sajjan Jindal Group) via Piombino Steel Ltd",
                "promoter_stake_pct": 83.28,
                "employee_count":     4094,
            },

            # ── INCOME STATEMENT ─────────────────────────────
            "income_statement": {
                "periods": ["FY2023", "FY2024", "9M_FY2025"],
                "total_revenue": {
                    "FY2023": {
                        "value": 20077, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "FY2024": {
                        "value": 21893, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "9M_FY2025_unaudited": {
                        "value": 16029, "unit": "crore INR", "confidence": "HIGH"
                    },
                },
                "ebitda": {
                    "FY2023": {
                        "value": 1806, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "FY2024": {
                        "value": 2765, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "9M_FY2025_unaudited": {
                        "value": 1882, "unit": "crore INR", "confidence": "HIGH"
                    },
                },
                "pat": {
                    "FY2023": {
                        "value": 160, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "FY2024": {
                        "value": 674, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "9M_FY2025_unaudited": {
                        "value": 219, "unit": "crore INR", "confidence": "HIGH"
                    },
                },
                "ebitda_margin_pct": {
                    "FY2023": {
                        "value": 8.99, "confidence": "HIGH",
                        "source": "Computed: 1806/20077"
                    },
                    "FY2024": {
                        "value": 12.63, "confidence": "HIGH",
                        "source": "Computed: 2765/21893"
                    },
                },
                "pat_margin_pct": {
                    "FY2023": {"value": 0.80, "confidence": "HIGH"},
                    "FY2024": {"value": 3.08, "confidence": "HIGH"},
                },
            },

            # ── BALANCE SHEET ─────────────────────────────────
            "balance_sheet": {
                "gearing_ratio": {
                    "FY2023": {"value": 0.54, "unit": "times", "confidence": "HIGH"},
                    "FY2024": {"value": 0.47, "unit": "times", "confidence": "HIGH"},
                },
                "cash_and_equivalents": {
                    "March_2024": {"value": 643, "unit": "crore INR", "confidence": "HIGH"},
                    "Dec_2024":   {"value": 424, "unit": "crore INR", "confidence": "HIGH"},
                },
                "total_debt": {
                    "term_loan_outstanding":  {
                        "value": 3750, "unit": "crore INR", "confidence": "HIGH"
                    },
                    "total_rated_facilities": {
                        "value": 14030, "unit": "crore INR", "confidence": "HIGH"
                    },
                },
            },

            # ── CREDIT METRICS ────────────────────────────────
            "credit_metrics": {
                "interest_coverage_ratio": {
                    "FY2023":     {"value": 2.40, "unit": "times", "confidence": "HIGH"},
                    "FY2024":     {"value": 3.04, "unit": "times", "confidence": "HIGH"},
                    "9M_FY2025":  {"value": 2.96, "unit": "times", "confidence": "HIGH"},
                },
                "existing_credit_facilities": [
                    {
                        "type":         "Term Loan",
                        "amount_crore": 3750,
                        "maturity":     "March 2030",
                        "rating":       "CARE AA; Stable",
                    },
                    {
                        "type":              "Fund-based Working Capital (CC/WCDL/OD)",
                        "amount_crore":      1100,
                        "utilisation_pct":   30,
                        "rating":            "CARE AA; Stable / CARE A1+",
                    },
                    {
                        "type":         "Non-Fund Based (BG/LC)",
                        "amount_crore": 7650,
                        "rating":       "CARE AA; Stable / CARE A1+",
                    },
                    {
                        "type":         "Commercial Paper",
                        "amount_crore": 1000,
                        "tenure":       "7-365 days",
                        "rating":       "CARE A1+",
                    },
                ],
            },

            # ── OPERATIONAL METRICS ───────────────────────────
            "operational_metrics": {
                "key_products": [
                    "Hot Rolled Coils (HRC)",
                    "Cold Rolled Steel (CRC)",
                    "Galvanised Sheets",
                    "Precision Tubes",
                    "Large Diameter Pipes",
                    "Sponge Iron",
                    "Bars and Wire Rods",
                ],
                "production_capacity":  "4.5 MTPA crude steel — Jharsuguda, Odisha (as of Dec 2024)",
                "sales_volume": {
                    "FY2023": {"value": 2.51, "unit": "MT", "confidence": "HIGH"},
                    "FY2024": {"value": 2.96, "unit": "MT", "confidence": "HIGH"},
                },
                "key_customers": [
                    "Automotive OEMs (Maruti, Tata Motors, M&M)",
                    "Infrastructure developers",
                    "Consumer durables manufacturers",
                ],
                "geographic_presence": [
                    "Jharsuguda, Odisha (integrated steelmaking)",
                    "Chandigarh (downstream processing)",
                    "Kolkata (downstream processing)",
                ],
            },

            # ── AUDIT QUALIFICATIONS ─────────────────────────
            # FY2024 audit was clean — no qualifications
            "audit_qualifications": [],

            # ── CONTINGENT LIABILITIES ───────────────────────
            "contingent_liabilities": [
                (
                    "Retrospective mining tax liability — quantum unquantified. "
                    "Supreme Court ruling empowers states to levy retrospective tax on mining. "
                    "BPSL has mining operations in Odisha."
                ),
                (
                    "ED asset attachment of Rs.4,025 crore — RESOLVED. "
                    "Supreme Court directed ED to hand over attached properties to JSW Steel (Dec 11, 2024)."
                ),
            ],

            # ── RED FLAGS (LLM-detected from narrative) ──────
            "red_flags_found": [
                (
                    "CRITICAL: Supreme Court ordered liquidation of BPSL on May 2, 2025. "
                    "JSW Steel's Rs.19,700 crore resolution plan rejected for IBC non-compliance. "
                    "Review petition filed by JSW — status quo maintained pending review."
                ),
                (
                    "Steel blended realisation declined 18% from FY24 (Rs.73,963/tonne) "
                    "to Q3FY25 (Rs.60,682/tonne) due to cheap Chinese steel imports."
                ),
                (
                    "PBILDT per tonne fell 34%: Rs.9,341 in FY24 → Rs.6,148 in Q3FY25. "
                    "Profitability under pressure from both lower realisations and ramp-up costs."
                ),
                (
                    "Cash balance declined 34%: Rs.643 crore (March 2024) → "
                    "Rs.424 crore (December 2024) — liquidity tightening."
                ),
                (
                    "Legacy bank fraud: Former promoter Sanjay Singal accused of "
                    "Rs.47,000 crore bank fraud across PNB, OBC, IDBI, UCO Bank. "
                    "CBI chargesheet filed. Current JSW management not implicated."
                ),
                (
                    "Forex exposure: Company imports coking coal and has "
                    "USD-denominated debt. Partial natural hedge via export revenues. "
                    "Hedging policy covers revenue account and 1-year debt service."
                ),
                (
                    "Unquantified retrospective mining tax contingent liability — "
                    "Odisha operations exposed. Quantum not yet determined by authorities."
                ),
            ],

            # ── POSITIVE FACTORS ─────────────────────────────
            "positive_factors": [
                "CARE AA; Stable rating — strong investment grade (reaffirmed March 2025)",
                "Parent: JSW Steel Limited (83.28%) — India's largest private steel producer",
                "JSW extended letter of comfort for all existing bank facilities",
                "Value-added product mix improving: CRC +24%, Pipes +54% in FY24",
                "Capacity expanded from 3.5 MTPA to 4.5 MTPA (Dec 2024)",
                "ED Rs.4,025 crore attachment resolved favourably — SC order Dec 2024",
                "Netrabandha iron ore mine (2 MTPA) expected to start Q1FY26 — raw material security",
                "Interest coverage at 3.04x in FY24 — above minimum threshold",
                "Gearing improved from 0.54x (FY23) to 0.47x (FY24)",
                "Working capital utilisation only 30% of Rs.1,100 crore limit — good buffer",
            ],

            # ── FIELDS NOT FOUND ─────────────────────────────
            "fields_not_found": [
                "GST filing data (GSTR-3B) — not available for listed companies; upload separately",
                "Bank statement — upload separately to enable circular trading check (CV_009)",
                "ITR details — upload ITR acknowledgement or Form 26AS",
                "Director KYC details and DIN numbers",
                "Shareholding pattern below promoter level (FII, DII, public breakdown)",
                "CIBIL / credit bureau report for promoter",
                "Current ratio — not reported in available documents",
                "DSCR (Debt Service Coverage Ratio) — compute from P&L + debt schedule",
            ],
        }
    }


# ─────────────────────────────────────────────────────────────
# Raw text strings — simulating pdfplumber / OCR extraction
# These are fed into the LLM as raw input in real mode
# In demo mode, get_demo_structured() bypasses LLM entirely
# ─────────────────────────────────────────────────────────────

BPSL_ANNUAL_REPORT_TEXT = """
BHUSHAN POWER AND STEEL LIMITED
Annual Report FY2023-24

COMPANY OVERVIEW
CIN: U27100DL1999PLC108350 | Incorporated: February 22, 1999
Registered Office: 4th Floor, A-2, NTH Complex, Shaheed Jeet Singh Marg,
USO Road, Qutab Institutional Area, South Delhi, New Delhi - 110067
Manufacturing: 4.50 MTPA integrated steel — Jharsuguda, Odisha (as of Dec 2024)
Parent Company: JSW Steel Limited — 83.28% stake via Piombino Steel Limited
Total Employees: 4,094 (December 2024)

FINANCIAL HIGHLIGHTS FY2023-24
[TABLE DATA]
Metric | FY2023 | FY2024 | 9M FY2025 (Unaudited)
Total Operating Income (Rs. Cr) | 20,077 | 21,893 | 16,029
PBILDT (Rs. Cr) | 1,806 | 2,765 | 1,882
PAT (Rs. Cr) | 160 | 674 | 219
Overall Gearing (times) | 0.54 | 0.47 | -
Interest Coverage (times) | 2.40 | 3.04 | 2.96
PBILDT per tonne (Rs.) | 7,197 | 9,341 | 6,148 (Q3FY25)

OPERATIONAL METRICS FY2024
Sales Volume: 2.96 MT (FY2023: 2.51 MT) — volume growth of 18%
Blended Sales Realisation: Rs.73,963/tonne (FY2023: Rs.79,989/tonne) — DECLINING
Cash and Equivalents: Rs.643 crore (March 2024), Rs.424 crore (December 2024)
Working Capital Limit: Rs.1,100 crore | Utilisation: ~30% as of December 2024
Term Loan Outstanding: Rs.3,750 crore | Repayment: March 2030

Q3 FY2025 UPDATE (UNAUDITED — AS OF DECEMBER 31, 2024)
Sales Realisation Q3FY25: Rs.60,682/tonne — declined due to Chinese steel imports
PBILDT/tonne Q2FY25: Rs.5,824 | Q3FY25: Rs.6,148
Industry context: Record cheap Chinese steel imports pressuring domestic prices in H2FY25

CAPACITY EXPANSION
Capacity ramp-up completed in Q3FY25 — now at 4.5 MTPA (expanded from 3.5 MTPA)
Downstream assets: ~1.8 MTPA including cold rolling, tubes, pipes
Netrabandha iron ore mine (Odisha) — 2 MTPA — expected to commence Q1FY26

HISTORICAL BACKGROUND
Incorporated 1999 | Originally promoted by Sanjay Singal (Brij Bhushan group)
CIRP initiated: July 26, 2017 under Insolvency and Bankruptcy Code
Peak debt at CIRP: Rs.46,062 crore (March 2016)
NCLT approved JSW resolution plan: Rs.19,700 crore (September 2019)
Acquisition completed by JSW via Piombino Steel Limited: March 26, 2021
Former promoter Sanjay Singal: CBI chargesheet for Rs.47,000 crore bank fraud
Banks defrauded: Punjab National Bank, Oriental Bank of Commerce, IDBI Bank, UCO Bank
"""

BPSL_CARE_RATINGS_TEXT = """
CARE RATINGS LIMITED — PRESS RELEASE
Date: March 03, 2025
Company: Bhushan Power and Steel Limited

RATING ASSIGNED
Long Term / Short Term Bank Facilities: Rs.14,030 crore — CARE AA; Stable / CARE A1+
Commercial Paper: Rs.1,000 crore — CARE A1+
Rating Action: REAFFIRMED

RATIONALE
The reaffirmation factors the ramp-up of the additional 1 MTPA capacity and the strong
parentage of JSW Steel Limited (83.28% via Piombino Steel Limited). JSWSL has
demonstrated strong commitment and extended letter of comfort for existing bank facilities.

KEY STRENGTHS
1. Strategic subsidiary of JSW Steel — extends market reach to eastern and northern India
2. Access to JSW's supplier network — better raw material procurement terms
3. JSW Odisha iron ore mines — partial raw material security for BPSL
4. Value-added product mix improving: CRC volumes up 24%, Pipes up 54% in FY24
5. PBILDT/tonne improved to Rs.9,341 in FY24 from Rs.7,197 in FY23
6. Netrabandha iron ore mine — 2 MTPA capacity — expected to start Q1FY26

KEY WEAKNESSES / RATING CONSTRAINTS
1. Cyclical steel industry — demand tied to automotive, infra, consumer durables
2. Blended realisation declined: Rs.73,963/tonne (FY24) → Rs.60,682/tonne (Q3FY25)
3. PBILDT/tonne fell: Rs.9,341 (FY24) → Rs.5,824 (Q2FY25) → Rs.6,148 (Q3FY25)
4. Forex risk: imports coking coal + USD-denominated debt (partially hedged)
5. Unquantified retrospective mining tax — SC ruling on state mining levy powers

NEGATIVE RATING TRIGGERS
- Net debt to PBILDT exceeding 3.0x on sustained basis
- Overall gearing exceeding 1.50x from debt-funded capex
- Weakening of JSW Steel linkages or JSW credit profile deterioration

LIQUIDITY: ADEQUATE
Cash balance March 2024: Rs.643 crore | December 2024: Rs.424 crore
Rs.4,500 crore repayment due March 2024 — repaid via Rs.4,000 crore new loan + accruals
Fund-based working capital limit: Rs.1,100 crore | Utilisation: ~30% (last 12 months)
"""

BPSL_LEGAL_TEXT = """
LEGAL INTELLIGENCE SUMMARY — BHUSHAN POWER AND STEEL LIMITED
Prepared from: e-Courts portal, Supreme Court orders, news intelligence

CASE 1: CBI Bank Fraud — Former Promoter
Court: CBI Special Court, Rouse Avenue District Courts, New Delhi
Parties: Central Bureau of Investigation vs Sanjay Singal and associates
Alleged fraud quantum: Rs.47,000 crore across multiple PSU banks
Banks involved: Punjab National Bank (Rs.3,805 crore), OBC, IDBI Bank, UCO Bank
Status: ONGOING — chargesheet filed, trial in progress
Current JSW management: NOT implicated — charges against former promoter only

CASE 2: Enforcement Directorate Asset Attachment — RESOLVED
Attached assets: Rs.4,025 crore of BPSL properties (plant, land, equipment)
Attachment basis: Prevention of Money Laundering Act (PMLA)
Supreme Court order date: December 11, 2024
SC ruling: Directed Enforcement Directorate to hand over attached properties to
           JSW Steel (as successful resolution applicant)
Current status: RESOLVED FAVOURABLY for BPSL / JSW Steel

CASE 3: SUPREME COURT — RESOLUTION PLAN VALIDITY [*** CRITICAL ***]
Petitioners: Former promoter Sanjay Singal + certain Committee of Creditors members
Issue: Challenge to legality of JSW Steel's Rs.19,700 crore resolution plan under IBC
Contention: Resolution plan violated Section 30(2) and Section 31(2) of IBC
Supreme Court ruling date: May 2, 2025
SC RULING: REJECTED JSW Steel's resolution plan. Ordered BPSL liquidation under IBC.
Post-ruling action: JSW Steel filed review petition on May 26, 2025
Current status: Supreme Court granted STATUS QUO — liquidation order stayed pending review
Review window: 30 days from May 26, 2025
RISK LEVEL: CRITICAL — existential uncertainty. If review petition fails,
            BPSL will be liquidated and all debt obligations become NPAs.

CASE 4: Retrospective Mining Tax — CONTINGENT LIABILITY
Background: Supreme Court ruling (2024) empowers state governments to levy
            retrospective tax on mining operations going back several years
BPSL exposure: Mining operations in Odisha — iron ore and coal
Current status: CONTINGENT — state authorities have not yet issued demand
Quantum: UNQUANTIFIED — could be significant given years of operations
Risk level: MEDIUM — real liability but quantum and timing uncertain
"""