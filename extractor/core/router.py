"""
core/router.py
Routes each file to its correct extractor based on detected format.
Returns a standard list of page dicts:
    [{"page": 1, "text": "...", "source": "filename", "type": "pdf_text"}, ...]
"""

from extractors.pdf_text    import extract_pdf_text
from extractors.pdf_scanned import extract_pdf_scanned
from extractors.docx        import extract_docx
from extractors.excel       import extract_excel
from extractors.csv_file    import extract_csv
from extractors.txt_file    import extract_txt


def route_to_extractor(file_path: str, fmt: str) -> list:
    """
    Dispatches to the right extractor based on format string.

    All extractors return List[dict] with keys:
        page   : int   — page / sheet / row-block number
        text   : str   — raw extracted text
        source : str   — original filename
        type   : str   — extractor type used
        method : str   — 'pdfplumber' / 'tesseract' / 'openpyxl' etc.
    """
    dispatch = {
        "pdf_text":    extract_pdf_text,
        "pdf_scanned": extract_pdf_scanned,
        "docx":        extract_docx,
        "xlsx":        extract_excel,
        "csv":         extract_csv,
        "txt":         extract_txt,
    }

    extractor = dispatch.get(fmt)
    if extractor is None:
        raise ValueError(
            f"No extractor available for format: '{fmt}'. "
            f"Supported: {list(dispatch.keys())}"
        )

    return extractor(file_path)