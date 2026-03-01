"""
extractors/pdf_scanned.py
Handles IMAGE-based / scanned PDFs using OCR.

Supports two engines (configured via OCR_ENGINE in .env):
    easyocr    — RECOMMENDED. No system deps. Supports Hindi, English, and 80+ languages.
    tesseract  — Legacy. Requires Tesseract + Poppler installed as system dependencies.

.env config:
    OCR_ENGINE=easyocr
    OCR_LANGUAGES=en,hi
    OCR_DPI=300
"""

import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def extract_pdf_scanned(file_path: str) -> list:
    """
    Converts each PDF page to a high-res image, runs OCR on each image.
    Returns same format as extract_pdf_text for full pipeline compatibility.

    Returns:
        List of dicts — one per page — each with keys:
        page, text, source, type, method, has_tables, ocr_confidence
    """
    ocr_engine = os.getenv("OCR_ENGINE", "easyocr").lower()

    if ocr_engine == "tesseract":
        return _extract_with_tesseract(file_path)
    else:
        return _extract_with_easyocr(file_path)


# ── EasyOCR Engine (RECOMMENDED) ────────────────────────────

def _extract_with_easyocr(file_path: str) -> list:
    """
    Uses EasyOCR for text recognition. No system dependencies needed.
    Supports Hindi, English, and 80+ languages out of the box.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise ImportError(
            "pdf2image not installed.\n"
            "Run: pip install pdf2image\n"
            "Also install poppler: https://github.com/ossamamehmood/Poppler-windows/releases"
        )

    try:
        import easyocr
    except ImportError:
        raise ImportError(
            "easyocr not installed.\n"
            "Run: pip install easyocr"
        )

    import numpy as np

    # Read config from .env
    lang_str = os.getenv("OCR_LANGUAGES", "en,hi")
    languages = [l.strip() for l in lang_str.split(",")]
    dpi = int(os.getenv("OCR_DPI", "300"))

    source = os.path.basename(file_path)
    results = []

    print(f"      [OCR] Engine: EasyOCR | Languages: {languages} | DPI: {dpi}")
    print(f"      [OCR] Converting PDF pages to images...")

    images = convert_from_path(file_path, dpi=dpi)

    print(f"      [OCR] Initializing EasyOCR reader ({', '.join(languages)})...")
    reader = easyocr.Reader(languages, gpu=False, verbose=False)

    print(f"      [OCR] Running OCR on {len(images)} page(s)...")

    for i, image in enumerate(images, start=1):
        # Pre-process image
        image = _preprocess_image(image)

        # Convert PIL Image to numpy array for EasyOCR
        img_array = np.array(image)

        # Run EasyOCR
        ocr_results = reader.readtext(img_array)

        # Extract text and confidence
        page_texts = []
        confidences = []
        for (bbox, text, conf) in ocr_results:
            page_texts.append(text)
            confidences.append(conf)

        full_text = "\n".join(page_texts)
        avg_conf = round(sum(confidences) / len(confidences) * 100) if confidences else 0

        results.append({
            "page":           i,
            "text":           full_text.strip(),
            "source":         source,
            "type":           "pdf_scanned",
            "method":         "easyocr",
            "has_tables":     False,
            "ocr_confidence": avg_conf,
        })
        print(f"      [OCR] Page {i}/{len(images)} — confidence: {avg_conf}%")

    return results


# ── Tesseract Engine (Legacy) ────────────────────────────────

def _extract_with_tesseract(file_path: str) -> list:
    """
    Legacy OCR using pytesseract + pdf2image.
    Requires system deps: tesseract-ocr, poppler-utils.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise ImportError(
            "pdf2image not installed.\n"
            "Run: pip install pdf2image\n"
            "Also run: sudo apt-get install poppler-utils"
        )

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ImportError(
            "pytesseract or Pillow not installed.\n"
            "Run: pip install pytesseract Pillow\n"
            "Also run: sudo apt-get install tesseract-ocr"
        )

    dpi = int(os.getenv("OCR_DPI", "300"))
    lang_str = os.getenv("OCR_LANGUAGES", "en")
    # Convert to Tesseract format: en,hi -> eng+hin
    tess_lang_map = {"en": "eng", "hi": "hin", "ta": "tam", "mr": "mar", "bn": "ben"}
    tess_langs = "+".join(
        tess_lang_map.get(l.strip(), l.strip())
        for l in lang_str.split(",")
    )

    source = os.path.basename(file_path)
    results = []

    print(f"      [OCR] Engine: Tesseract | Languages: {tess_langs} | DPI: {dpi}")
    print(f"      [OCR] Converting PDF pages to images...")
    images = convert_from_path(file_path, dpi=dpi)
    print(f"      [OCR] Running Tesseract OCR on {len(images)} page(s)...")

    for i, image in enumerate(images, start=1):
        image = _preprocess_image(image)
        text = pytesseract.image_to_string(
            image, lang=tess_langs, config="--psm 6"
        )
        confidence = _get_tesseract_confidence(image, tess_langs)

        results.append({
            "page":           i,
            "text":           text.strip(),
            "source":         source,
            "type":           "pdf_scanned",
            "method":         "tesseract_ocr",
            "has_tables":     False,
            "ocr_confidence": confidence,
        })
        print(f"      [OCR] Page {i}/{len(images)} — confidence: {confidence}%")

    return results


# ── Shared Helpers ───────────────────────────────────────────

def _preprocess_image(image):
    """
    Pre-processes image before OCR to improve accuracy.
    Steps: grayscale → sharpen → boost contrast.
    """
    from PIL import ImageEnhance, ImageFilter

    image = image.convert("L")                  # Convert to grayscale
    image = image.filter(ImageFilter.SHARPEN)   # Sharpen edges
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)               # Boost contrast 2x

    return image


def _get_tesseract_confidence(image, lang: str = "eng") -> int:
    """
    Returns average Tesseract confidence score for the page (0–100).
    Returns -1 if confidence scoring fails.
    """
    try:
        import pytesseract
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            lang=lang,
            config="--psm 6"
        )
        confidences = [
            int(c) for c in data["conf"]
            if str(c).isdigit() and int(c) > 0
        ]
        if confidences:
            return round(sum(confidences) / len(confidences))
    except Exception:
        pass
    return -1