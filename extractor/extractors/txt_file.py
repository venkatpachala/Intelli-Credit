"""
extractors/txt_file.py
Extracts text from plain .txt files.
Used for: news summaries, eCourts copy-paste, MCA XML converted to text,
          analyst notes, management interview transcripts.
Uses Python stdlib only — no extra install needed.
"""


def extract_txt(file_path: str) -> list:
    """
    Reads the entire text file as a single page.
    Uses errors='replace' to handle any encoding issues gracefully.

    Returns:
        List with one dict containing keys:
        page, text, source, type, method, has_tables
    """
    source = file_path.split("/")[-1]

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    return [{
        "page":       1,
        "text":       text.strip(),
        "source":     source,
        "type":       "txt",
        "method":     "stdlib_open",
        "has_tables": False,
    }]