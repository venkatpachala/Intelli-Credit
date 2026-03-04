"""
cam_engine/document/pdf_converter.py
=======================================
Converts .docx → .pdf.

Strategy (tries in order):
  1. docx2pdf       (works on Windows / macOS with MS Word installed)
  2. LibreOffice    (works on Linux / Docker)
  3. Returns None   (graceful degradation — no crash)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional


def convert_to_pdf(docx_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Convert a .docx file to PDF.

    Parameters
    ----------
    docx_path   : Absolute path to the source .docx file.
    output_path : Optional target path for the .pdf. Defaults to same
                  directory with .pdf extension.

    Returns
    -------
    str  — path to the generated PDF, or None if conversion failed.
    """
    docx_path = Path(docx_path)
    if not docx_path.exists():
        print(f"[pdf_converter] Source file not found: {docx_path}", file=sys.stderr)
        return None

    if output_path is None:
        output_path = str(docx_path.with_suffix(".pdf"))

    # ── Strategy 1: docx2pdf (Windows / macOS) ──────────────
    try:
        from docx2pdf import convert
        convert(str(docx_path), output_path)
        if Path(output_path).exists():
            print(f"[pdf_converter] PDF created via docx2pdf: {output_path}")
            return output_path
    except ImportError:
        pass   # Not installed
    except Exception as e:
        print(f"[pdf_converter] docx2pdf failed: {e}", file=sys.stderr)

    # ── Strategy 2: LibreOffice (Linux / Docker) ─────────────
    try:
        out_dir = str(Path(output_path).parent)
        result  = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", out_dir,
                str(docx_path),
            ],
            capture_output=True,
            timeout=60,
        )
        # LibreOffice names the output after the input filename
        expected = Path(out_dir) / (docx_path.stem + ".pdf")
        if result.returncode == 0 and expected.exists():
            if str(expected) != output_path:
                expected.rename(output_path)
            print(f"[pdf_converter] PDF created via LibreOffice: {output_path}")
            return output_path
        else:
            print(f"[pdf_converter] LibreOffice failed: {result.stderr.decode()[:200]}", file=sys.stderr)
    except FileNotFoundError:
        pass   # LibreOffice not installed
    except subprocess.TimeoutExpired:
        print("[pdf_converter] LibreOffice timed out.", file=sys.stderr)
    except Exception as e:
        print(f"[pdf_converter] LibreOffice error: {e}", file=sys.stderr)

    # ── Graceful degradation ─────────────────────────────────
    print("[pdf_converter] PDF conversion unavailable. DOCX file is the final output.",
          file=sys.stderr)
    return None
