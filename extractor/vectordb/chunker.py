"""
vectordb/chunker.py
Smart document chunker designed for Indian financial documents.
Handles messy tables, mixed Hindi/English, and preserves financial sections.
"""

import re


# Financial section headings common in Indian and global annual reports
# NOTE: No inline (?i) flags — we use re.IGNORECASE at match time
SECTION_MARKERS = [
    # Indian financial document headings
    r"^(balance\s*sheet|profit\s*and\s*loss|cash\s*flow\s*statement)",
    r"^(notes\s*to\s*(the\s*)?financial\s*statements)",
    r"^(schedule|annexure|appendix)\s+[A-Z0-9]",
    r"^(director['']?s?\s*report|auditor['']?s?\s*report)",
    r"^(management\s*discussion|chairman['']?s?\s*message)",
    r"^(corporate\s*governance|related\s*party\s*transactions)",
    r"^(significant\s*accounting\s*policies)",
    r"^(standalone|consolidated)\s+(financial\s*)?statements?",
    # Credit-specific sections
    r"^(credit\s*rating|risk\s*factors|contingent\s*liabilities)",
    r"^(key\s*rating\s*(strengths|risks|weaknesses))",
    r"^(negative|positive)\s*rating\s*triggers?",
    r"^(legal|litigation|regulatory)\s*(proceedings|exposure|update)?",
    r"^(shareholding\s*pattern|promoter\s*holding)",
    # Generic document structure
    r"^(section|chapter|part|item)\s+\d",
    r"^(agenda\s*item|meeting|headline|case|note)\s+\d",
    r"^[═]{10,}",   # section dividers
    r"^[─]{10,}",
]

TABLE_MARKERS = [
    r"\[TABLE DATA\]",
    r"\[CSV DATA\]",
    r"\[SHEET:",
    r"^\s*\|.*\|.*\|",  # pipe-delimited table rows
]


def chunk_document(text: str, metadata: dict, chunk_size: int = 1000,
                   overlap: int = 200) -> list:
    """
    Split document text into chunks suitable for embedding.

    Strategy:
    1. Split on section boundaries first (preserves logical sections)
    2. If a section exceeds chunk_size, split on paragraph boundaries
    3. Keep tables intact as single chunks when possible
    4. Add overlap between consecutive chunks for context continuity

    Args:
        text: Full document text
        metadata: Base metadata dict (source, type, etc.)
        chunk_size: Target chunk size in characters (default 1000)
        overlap: Overlap between consecutive chunks (default 200)

    Returns:
        List of dicts with keys: text, metadata
    """
    if not text or not text.strip():
        return []

    # Step 1: Split into sections
    sections = _split_on_sections(text)

    # Step 2: Process each section
    chunks = []
    for section in sections:
        section_text = section["text"].strip()
        if not section_text:
            continue

        # Detect section type for metadata
        section_type = _classify_section(section_text)
        section_meta = {
            **metadata,
            "section": section.get("heading", ""),
            "section_type": section_type,
        }

        # If section fits in one chunk, keep it whole
        if len(section_text) <= chunk_size * 1.3:  # 30% tolerance
            chunks.append({
                "text": section_text,
                "metadata": section_meta,
            })
        else:
            # Split large sections into overlapping chunks
            sub_chunks = _split_with_overlap(section_text, chunk_size, overlap)
            for i, sub in enumerate(sub_chunks):
                chunks.append({
                    "text": sub,
                    "metadata": {
                        **section_meta,
                        "chunk_part": f"{i + 1}/{len(sub_chunks)}",
                    },
                })

    # Step 3: Add chunk IDs
    for i, chunk in enumerate(chunks):
        chunk["metadata"]["chunk_id"] = f"{metadata.get('source', 'unknown')}__chunk_{i:04d}"

    return chunks


def _split_on_sections(text: str) -> list:
    """Split text at section headings, keeping the heading with its section."""
    combined_pattern = "|".join(f"({m})" for m in SECTION_MARKERS)
    lines = text.split("\n")

    sections = []
    current_lines = []
    current_heading = ""

    for line in lines:
        is_section_break = bool(re.match(combined_pattern, line.strip(), re.IGNORECASE))

        if is_section_break and current_lines:
            sections.append({
                "heading": current_heading,
                "text": "\n".join(current_lines),
            })
            current_lines = [line]
            current_heading = line.strip()[:80]
        else:
            if not current_heading and line.strip():
                current_heading = line.strip()[:80]
            current_lines.append(line)

    # Don't forget the last section
    if current_lines:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_lines),
        })

    # If no sections found, return the whole text as one section
    if not sections:
        sections = [{"heading": "", "text": text}]

    return sections


def _split_with_overlap(text: str, chunk_size: int, overlap: int) -> list:
    """Split text into overlapping chunks, preferring paragraph boundaries."""
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current = ""

    for para in paragraphs:
        # If adding this paragraph would exceed the limit
        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            # Start new chunk with overlap from previous
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:] + "\n\n" + para
            else:
                current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    # Handle case where a single paragraph exceeds chunk_size
    final_chunks = []
    for chunk in chunks:
        if len(chunk) > chunk_size * 2:
            # Force-split at sentence boundaries
            for sub in _force_split(chunk, chunk_size, overlap):
                final_chunks.append(sub)
        else:
            final_chunks.append(chunk)

    return final_chunks


def _force_split(text: str, chunk_size: int, overlap: int) -> list:
    """Force-split very long text at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            current = current[-overlap:] + " " + sentence if overlap else sentence
        else:
            current = current + " " + sentence if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _classify_section(text: str) -> str:
    """Classify section type for metadata tagging."""
    text_lower = text[:500].lower()

    if any(kw in text_lower for kw in ["balance sheet", "total assets", "total liabilities"]):
        return "balance_sheet"
    if any(kw in text_lower for kw in ["profit and loss", "income statement", "revenue", "ebitda"]):
        return "income_statement"
    if any(kw in text_lower for kw in ["cash flow", "operating cash", "free cash"]):
        return "cash_flow"
    if any(kw in text_lower for kw in ["director", "board", "meeting", "resolution"]):
        return "governance"
    if any(kw in text_lower for kw in ["audit", "auditor", "qualification"]):
        return "audit"
    if any(kw in text_lower for kw in ["legal", "litigation", "lawsuit", "court"]):
        return "legal"
    if any(kw in text_lower for kw in ["rating", "moody", "s&p", "fitch", "credit"]):
        return "credit_rating"
    if any(kw in text_lower for kw in ["shareholder", "shareholding", "promoter"]):
        return "shareholding"
    if any(kw in text_lower for kw in ["gst", "itr", "tax", "filing"]):
        return "tax_filings"
    if any(kw in text_lower for kw in ["news", "headline", "report", "sector"]):
        return "news"
    if any(kw in text_lower for kw in ["site visit", "due diligence", "observation"]):
        return "primary_insight"
    if any(kw in text_lower for kw in ["table data", "csv data", "sheet:"]):
        return "tabular_data"

    return "general"
