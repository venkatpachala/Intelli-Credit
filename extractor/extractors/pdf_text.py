"""
extractors/pdf_text.py
Extracts text AND tables from digital (non-scanned) PDFs using pdfplumber.

Install:
    pip install pdfplumber
"""


def extract_pdf_text(file_path: str) -> list:
    """
    Extracts text page by page from a digital PDF.
    Also pulls tables as pipe-delimited text so the LLM can read them naturally.

    Returns:
        List of dicts — one per page — each with keys:
        page, text, source, type, method, has_tables
    """
    import os
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber not installed.\n"
            "Run: pip install pdfplumber"
        )

    results = []
    source  = os.path.basename(file_path)

    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            # ── Extract prose text ────────────────────────────
            page_text = page.extract_text() or ""

            # ── Extract tables → pipe-delimited string ────────
            table_text = ""
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                for row in table:
                    clean_row = [str(cell).strip() if cell else "" for cell in row]
                    table_text += " | ".join(clean_row) + "\n"

            # ── Combine prose + tables ────────────────────────
            combined = page_text
            if table_text.strip():
                combined += "\n\n[TABLE DATA]\n" + table_text

            results.append({
                "page":       i,
                "text":       combined.strip(),
                "source":     source,
                "type":       "pdf_text",
                "method":     "pdfplumber",
                "has_tables": bool(table_text.strip()),
            })

    return results