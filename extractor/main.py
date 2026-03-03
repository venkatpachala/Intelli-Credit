"""
╔══════════════════════════════════════════════════════════╗
║     AI CREDIT DECISIONING ENGINE — EXTRACTOR PIPELINE   ║
║     Supports: PDF (text + scanned), DOCX, XLSX, CSV      ║
╚══════════════════════════════════════════════════════════╝

Usage:
    python main.py --folder input
    python main.py --folder data/bhushan --company "Bhushan Steel"
    python main.py --demo   ← runs with BPSL demo data (no file needed)

Output:
    Saves structured JSON to output/extracted_<company>.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass  # dotenv not installed, rely on system env vars


from core.detector    import detect_format
from core.router      import route_to_extractor
from core.llm         import LLMStructurer
from validators.cross import CrossValidator
from output.builder   import build_final_json
from demo.bpsl_demo   import get_demo_data


def run_pipeline(input_folder: str = "input", company_hint: str = None, demo: bool = False):
    print("\n" + "═"*60)
    print("  AI CREDIT EXTRACTOR — STARTING PIPELINE")
    print("═"*60)

    # ── DEMO MODE ────────────────────────────────────────────
    if demo:
        print("\n[MODE] Running in DEMO mode (Bhushan Power & Steel)")
        raw_texts = get_demo_data()
        company_hint = "Bhushan Power and Steel Limited"
        source_name = "DEMO"
    else:
        if not os.path.exists(input_folder):
            os.makedirs(input_folder)
            print(f"\n[INFO] Created folder: '{input_folder}'")
            print(f"[INFO] Please place your documents (PDF, CSV, DOCX) in this folder and run the script again.")
            sys.exit(0)

        files_in_folder = [f for f in os.listdir(input_folder) if os.path.isfile(os.path.join(input_folder, f))]
        
        if not files_in_folder:
            print(f"\n[ERROR] No files found in folder: '{input_folder}'")
            print(f"[ERROR] Please add files to '{input_folder}' and try again.")
            sys.exit(1)

        raw_texts = []
        source_name = input_folder

        print(f"\n[INFO] Found {len(files_in_folder)} file(s) in '{input_folder}' folder.")

        for i, file_name in enumerate(files_in_folder, start=1):
            file_path = os.path.join(input_folder, file_name)
            
            # ── STEP 1: DETECT FORMAT ─────────────────────────────
            print(f"\n[1/5] ({i}/{len(files_in_folder)}) Detecting format for: {file_name}")
            fmt = detect_format(file_path)
            print(f"      → Format detected: {fmt.upper()}")

            if fmt == "unknown":
                print(f"      → Skipping {file_name} (Unsupported format)")
                continue

            # ── STEP 2: EXTRACT RAW TEXT ──────────────────────────
            print(f"[2/5] ({i}/{len(files_in_folder)}) Extracting raw text...")
            try:
                extracted_pages = route_to_extractor(file_path, fmt)
                raw_texts.extend(extracted_pages)
                total_chars = sum(len(t["text"]) for t in extracted_pages)
                print(f"      → Extracted {total_chars:,} characters from {len(extracted_pages)} page(s)/sheet(s)")
            except Exception as e:
                print(f"      → [ERROR] Failed to extract from {file_name}: {e}")

        if not raw_texts:
            print("\n[ERROR] No valid text could be extracted from any files in the folder.")
            sys.exit(1)

        total_combined_chars = sum(len(t["text"]) for t in raw_texts)
        print(f"\n      → SUMMARY: Total {total_combined_chars:,} characters extracted across all {len(files_in_folder)} file(s).")

    # ── STEP 3: LLM STRUCTURING ───────────────────────────────
    print(f"\n[3/5] Sending combined text to LLM for structured extraction...")
    llm = LLMStructurer()
    structured = llm.extract(raw_texts, company_hint=company_hint)
    print(f"      → LLM returned {len(structured.get('fields', {}))} top-level fields")

    # ── STEP 4: CROSS-VALIDATION ──────────────────────────────
    print(f"\n[4/5] Running cross-validation checks...")
    validator = CrossValidator()
    validation_results = validator.run(structured)
    passed = sum(1 for c in validation_results if c["result"].startswith("PASS"))
    total  = len(validation_results)
    print(f"      → {passed}/{total} checks passed")

    # ── STEP 5: BUILD FINAL JSON ──────────────────────────────
    print(f"\n[5/5] Building final JSON output...")
    final = build_final_json(
        raw_texts        = raw_texts,
        structured       = structured,
        validation       = validation_results,
        source_file      = source_name,
        company_hint     = company_hint,
    )

    # ── SAVE OUTPUT ───────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    safe_name = (company_hint or "extracted").replace(" ", "_").replace("/", "_")[:40]
    out_path  = f"output/{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(final, f, indent=2)

    # ── PRINT SUMMARY ─────────────────────────────────────────
    print("\n" + "═"*60)
    print("  EXTRACTION COMPLETE")
    print("═"*60)
    rf = final.get("risk_flags", {})
    print(f"  Risk Flags   : {rf.get('total',0)} total  "
          f"({rf.get('CRITICAL',0)} CRITICAL, {rf.get('HIGH',0)} HIGH)")
    print(f"  Decision     : {final.get('credit_recommendation',{}).get('decision','N/A')}")
    print(f"  Output saved : {out_path}")
    print("═"*60 + "\n")

    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Credit Extractor Pipeline")
    parser.add_argument("--folder",  type=str, default="input", help="Folder containing documents (PDF/DOCX/XLSX/CSV)")
    parser.add_argument("--company", type=str, help="Company name hint for LLM context")
    parser.add_argument("--demo",    action="store_true", help="Run with BPSL demo data")
    args = parser.parse_args()

    run_pipeline(
        input_folder = args.folder,
        company_hint = args.company,
        demo         = args.demo,
    )
