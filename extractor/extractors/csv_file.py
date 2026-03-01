"""
extractors/csv_file.py
Extracts data from CSV files (GST returns, bank statements, CMA data, etc.)
Uses Python stdlib only — no extra install needed.
"""

import csv as csv_module


def extract_csv(file_path: str) -> list:
    """
    Reads every row from a CSV file.
    Converts each row to pipe-delimited string for LLM parsing.

    Handles:
        - UTF-8 with BOM (utf-8-sig) — common in Indian govt exports
        - Standard comma-separated
        - Files with header rows

    Returns:
        List with one dict containing keys:
        page, text, source, type, method, has_tables
    """
    source = file_path.split("/")[-1]
    rows   = []

    # utf-8-sig handles BOM character that some govt portals add
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv_module.reader(f)
        for row in reader:
            rows.append(" | ".join(str(c).strip() for c in row))

    return [{
        "page":       1,
        "text":       "[CSV DATA]\n" + "\n".join(rows),
        "source":     source,
        "type":       "csv",
        "method":     "csv_stdlib",
        "has_tables": True,
    }]