import os
import struct


def detect_format(file_path: str) -> str:
    """
    Returns one of:
        'pdf_text'    → digital PDF with extractable text
        'pdf_scanned' → image-based PDF, needs OCR
        'docx'        → Microsoft Word document
        'xlsx'        → Microsoft Excel workbook
        'csv'         → Comma-separated values
        'txt'         → Plain text file
        'unknown'     → Cannot determine
    """
    ext = os.path.splitext(file_path)[1].lower()

    # ── CSV and TXT: purely extension-based ─────────────────
    if ext == ".csv":
        return "csv"
    if ext == ".txt":
        return "txt"

    # ── Read magic bytes (first 8 bytes of file) ─────────────
    with open(file_path, "rb") as f:
        magic = f.read(8)

    # ── DOCX / XLSX: both are ZIP files with magic PK ────────
    if magic[:2] == b"PK":
        # Distinguish DOCX vs XLSX by internal structure
        import zipfile
        try:
            with zipfile.ZipFile(file_path) as z:
                names = z.namelist()
            if any("word/" in n for n in names):
                return "docx"
            if any("xl/" in n for n in names):
                return "xlsx"
        except Exception:
            pass
        return "unknown"

    # ── PDF: magic bytes %PDF ─────────────────────────────────
    if magic[:4] == b"%PDF":
        return _classify_pdf(file_path)

    return "unknown"


def _classify_pdf(file_path: str) -> str:
    """
    Distinguishes text-based PDF from scanned PDF.
    Strategy: try pdfplumber first. If it extracts < 50 chars per page
    on average (from sampled pages), it's likely a scanned document.
    Also checks for Hindi/Devanagari content.
    """
    try:
        import pdfplumber
        total_chars    = 0
        sampled_count  = 0
        has_hindi      = False

        with pdfplumber.open(file_path) as pdf:
            # Sample up to first 10 pages for better accuracy
            sample_pages = pdf.pages[:10]
            sampled_count = len(sample_pages)
            for page in sample_pages:
                text = page.extract_text() or ""
                stripped = text.strip()
                total_chars += len(stripped)

                # Check for Hindi/Devanagari script
                if not has_hindi and _contains_hindi(stripped):
                    has_hindi = True

        avg_chars_per_page = total_chars / max(sampled_count, 1)

        if has_hindi:
            print(f"      [Detector] Hindi/Devanagari text detected in PDF")

        # Heuristic: < 50 chars/page on average = almost certainly scanned
        if avg_chars_per_page < 50:
            return "pdf_scanned"
        return "pdf_text"

    except ImportError:
        # pdfplumber not installed — fall back to extension
        print("[WARN] pdfplumber not installed. Assuming text PDF.")
        return "pdf_text"
    except Exception as e:
        print(f"[WARN] PDF classification error: {e}. Assuming text PDF.")
        return "pdf_text"


def _contains_hindi(text: str) -> bool:
    """
    Checks if text contains Hindi / Devanagari characters.
    Devanagari Unicode range: U+0900 to U+097F
    Also checks for extended Devanagari: U+A8E0 to U+A8FF
    """
    if not text:
        return False

    for char in text:
        code = ord(char)
        # Devanagari block
        if 0x0900 <= code <= 0x097F:
            return True
        # Devanagari Extended block
        if 0xA8E0 <= code <= 0xA8FF:
            return True
        # Vedic Extensions
        if 0x1CD0 <= code <= 0x1CFF:
            return True

    return False


def detect_language(text: str) -> str:
    """
    Returns the detected language of the text.
    Currently supports: 'hindi', 'english', 'mixed', 'unknown'
    """
    if not text or not text.strip():
        return "unknown"

    has_hindi = _contains_hindi(text)

    # Check for substantial Latin characters (English)
    latin_count = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total_alpha = sum(1 for c in text if c.isalpha())

    if total_alpha == 0:
        return "unknown"

    latin_ratio = latin_count / total_alpha

    if has_hindi and latin_ratio > 0.3:
        return "mixed"  # Hindi + English
    elif has_hindi:
        return "hindi"
    elif latin_ratio > 0.5:
        return "english"

    return "unknown"