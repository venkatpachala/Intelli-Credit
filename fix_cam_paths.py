"""
fix_cam_paths.py
Regenerates DOCX+PDF for all cam_ready cases where file paths are missing.
Run from project root: python fix_cam_paths.py
"""
import sqlite3, json, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / "cam_engine"))

from document.builder import CAMBuilder
from document.pdf_converter import convert_to_pdf


def fix_case(case_id, cam_data, company_name):
    output_dir = Path("backend/cam_output") / case_id
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    docx_path = str(output_dir / f"CAM_{case_id}_{ts}.docx")
    pdf_path  = docx_path.replace(".docx", ".pdf")

    try:
        builder = CAMBuilder()
        doc     = builder.build(cam_data)
        doc.save(docx_path)
        docx_size = Path(docx_path).stat().st_size
        print(f"  [OK] DOCX: {docx_path} ({docx_size} bytes)")
    except Exception as e:
        print(f"  [FAIL] DOCX build failed: {e}")
        return None, None

    try:
        result    = convert_to_pdf(docx_path, pdf_path)
        final_pdf = result if (result and Path(result).exists()) else docx_path
        pdf_size  = Path(final_pdf).stat().st_size
        print(f"  [OK] PDF : {final_pdf} ({pdf_size} bytes)")
    except Exception as e:
        print(f"  [WARN] PDF conversion failed, using DOCX: {e}")
        final_pdf = docx_path

    return docx_path, final_pdf


def main():
    conn = sqlite3.connect("backend/data.db")
    conn.row_factory = sqlite3.Row

    cases = conn.execute(
        "SELECT id, company_name, cam_json FROM cases "
        "WHERE cam_json IS NOT NULL AND (cam_pdf_path IS NULL OR cam_docx_path IS NULL)"
    ).fetchall()

    print(f"Found {len(cases)} case(s) needing file path fix...")
    print()

    ok_count = 0
    for c in cases:
        case_id  = c["id"]
        company  = c["company_name"]
        cam_json = c["cam_json"]

        print(f"Processing: {case_id} -- {company}")

        try:
            cam_data = json.loads(cam_json)
        except Exception as e:
            print(f"  [FAIL] Bad cam_json: {e}")
            continue

        docx_path, pdf_path = fix_case(case_id, cam_data, company)

        if docx_path:
            conn.execute(
                "UPDATE cases SET cam_docx_path=?, cam_pdf_path=? WHERE id=?",
                (docx_path, pdf_path, case_id)
            )
            conn.commit()
            ok_count += 1
            print(f"  [DB] Updated paths for {case_id}")
        print()

    conn.close()
    print(f"Done! Fixed {ok_count}/{len(cases)} cases.")


if __name__ == "__main__":
    main()
