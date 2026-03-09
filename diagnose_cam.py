"""
Quick diagnostic: run generate_cam() directly with minimal test data
to see the exact error message.
"""
import sys, os, json, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'cam_engine'))

# Minimal test extraction data
extraction = {
    "company_profile": {"legal_name": "Test Co Pvt Ltd", "sector": "Manufacturing", "promoter_stake_pct": 74.0},
    "income_statement": {
        "periods": ["FY22", "FY23", "FY24"],
        "total_revenue": {"FY22": {"value": 418.20}, "FY23": {"value": 472.60}, "FY24": {"value": 525.00}},
        "ebitda":        {"FY22": {"value": 38.20},  "FY23": {"value": 44.50},  "FY24": {"value": 52.30}},
        "pat":           {"FY22": {"value": 8.70},   "FY23": {"value": 11.30},  "FY24": {"value": 13.85}},
        "finance_charges":{"FY22":{"value": 8.40},   "FY23": {"value": 9.10},   "FY24": {"value": 9.80}},
    },
    "balance_sheet": {
        "net_worth":   {"FY22": {"value": 85.0}, "FY23": {"value": 96.0}, "FY24": {"value": 110.0}},
        "total_assets": 280.0,
        "current_assets": 195.4,
        "current_liabilities": 82.3,
    },
    "credit_metrics": {"dscr": 2.25, "debt_equity": 1.42},
    "collateral_data": [{"type": "Land & Building", "market_value": 40.0, "distress_value": 28.0, "charge": "First Charge"}],
    "risk_flags": {"flags": []},
    "cash_flow": {"cfo": {"FY22": {"value": 12.0}, "FY23": {"value": 14.5}, "FY24": {"value": 16.8}}},
    "gst_data": {"annual_turnover": 520.0, "bank_credits": 480.0, "filing_compliance_pct": 91.7},
}

research = {
    "flags": [],
    "tags": ["MSME", "Manufacturing"],
    "risk_score": 70,
    "risk_band": "MEDIUM",
}

req = {
    "company_name": "Test Co Pvt Ltd",
    "cin": "U28910MH2015PTC999999",
    "gstin": "27AABCT1234A1Z5",
    "industry": "Manufacturing",
    "promoters": [{"name": "Rajesh Kumar", "din": "12345678", "pan": "ABCPK1234D", "shareholding_pct": 74.0}],
    "loan": {"type": "Cash Credit (CC)", "amount_inr": 25000000, "tenor_months": 36},
    "qualitative": {},
}

print("=" * 60)
print("Running generate_cam() diagnostic...")
print("=" * 60)

try:
    from main import generate_cam
    result = generate_cam(
        case_id    = "TEST_DIAG_001",
        extraction = extraction,
        research   = research,
        req        = req,
        output_dir = "cam_engine/output",
    )
    print("\n✅ generate_cam() SUCCEEDED")
    print(f"   Decision  : {result.get('decision')}")
    print(f"   Score     : {result.get('composite_score')}/100")
    print(f"   DOCX path : {result.get('docx_path')}")
    print(f"   PDF  path : {result.get('pdf_path')}")
    print(f"   Doc error : {result.get('doc_error', 'none')}")
except Exception as e:
    print(f"\n❌ generate_cam() FAILED:")
    print(f"   Error: {type(e).__name__}: {e}")
    print("\nFull traceback:")
    traceback.print_exc()
