"""
vectordb/ingest.py
Orchestrates the ingestion pipeline: Extract → Chunk → Embed → Store.
Reuses the existing extractor modules for raw text extraction.
"""

import os
import sys
import json

# Ensure extractor root is on sys.path so core.* imports work
_extractor_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _extractor_root not in sys.path:
    sys.path.insert(0, _extractor_root)

from core.detector import detect_format
from core.router import route_to_extractor
from vectordb.chunker import chunk_document
from vectordb.embedder import get_embedder
from vectordb.store import VectorStore


# Map detected format to a human-readable document type
DOC_TYPE_MAP = {
    "pdf_text":    "annual_report",
    "pdf_scanned": "annual_report",
    "docx":        "legal_document",
    "xlsx":        "financial_statement",
    "csv":         "structured_data",
    "txt":         "text_document",
}


def ingest_folder(folder_path: str, clear_existing: bool = False) -> dict:
    """
    Ingest all documents in a folder into the vector store.

    Steps:
    1. Detect file format
    2. Extract raw text using existing extractors
    3. Chunk text into embedding-ready pieces
    4. Generate embeddings via Gemini
    5. Store in ChromaDB

    Args:
        folder_path: Path to folder containing documents
        clear_existing: If True, clear vector store before ingesting

    Returns:
        dict with ingestion summary stats
    """
    # Initialize components
    embedder = get_embedder()
    store = VectorStore(dimension=embedder.DIMENSIONS)

    if clear_existing:
        store.clear()

    if not os.path.isdir(folder_path):
        print(f"[ERROR] Folder not found: {folder_path}")
        return {"error": f"Folder not found: {folder_path}"}

    files = sorted([
        f for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
        and not f.startswith(".")
    ])

    if not files:
        print("[WARN] No files found in folder.")
        return {"files_processed": 0}

    print(f"\n{'='*60}")
    print(f"  VECTOR DB INGESTION — {len(files)} file(s)")
    print(f"{'='*60}\n")

    total_chunks = 0
    file_stats = []

    for i, filename in enumerate(files, 1):
        file_path = os.path.join(folder_path, filename)
        print(f"[{i}/{len(files)}] Processing: {filename}")

        try:
            # Step 1: Detect format
            fmt = detect_format(file_path)
            print(f"    Format: {fmt}")

            # Infer document type from filename for better metadata
            doc_type = _infer_doc_type(filename, fmt)

            # Step 2: Extract raw text
            pages = route_to_extractor(file_path, fmt)
            print(f"    Extracted: {len(pages)} page(s)")

            # Step 3: Chunk each page
            all_chunks = []
            for page in pages:
                metadata = {
                    "source": filename,
                    "page": page.get("page", 1),
                    "doc_type": doc_type,
                    "format": fmt,
                    "method": page.get("method", "unknown"),
                }
                chunks = chunk_document(page.get("text", ""), metadata)
                all_chunks.extend(chunks)

            print(f"    Chunked: {len(all_chunks)} chunks")

            if not all_chunks:
                print(f"    [SKIP] No content to embed.")
                continue

            # Step 4: Generate embeddings
            texts = [c["text"] for c in all_chunks]
            embeddings = embedder.embed_texts(texts)

            # Step 5: Store in ChromaDB
            store.add_documents(all_chunks, embeddings)

            total_chunks += len(all_chunks)
            file_stats.append({
                "file": filename,
                "format": fmt,
                "doc_type": doc_type,
                "pages": len(pages),
                "chunks": len(all_chunks),
                "status": "OK",
            })

        except Exception as e:
            print(f"    [ERROR] {e}")
            file_stats.append({
                "file": filename,
                "error": str(e),
                "status": "FAILED",
            })

    # Also ingest structured JSON output if it exists
    _ingest_json_outputs(store, embedder)

    # Print summary
    stats = store.get_stats()
    print(f"\n{'='*60}")
    print(f"  INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Files processed : {len(file_stats)}")
    print(f"  Total chunks    : {stats['total_chunks']}")
    print(f"  Unique sources  : {stats['unique_sources']}")
    print(f"  Document types  : {', '.join(stats['doc_types'])}")
    print(f"{'='*60}\n")

    return {
        "files_processed": len(file_stats),
        "total_chunks": stats["total_chunks"],
        "file_details": file_stats,
        "store_stats": stats,
    }


def _infer_doc_type(filename: str, fmt: str) -> str:
    """Infer document type from filename keywords."""
    name_lower = filename.lower()

    if any(kw in name_lower for kw in ["annual", "report", "ar_"]):
        return "annual_report"
    if any(kw in name_lower for kw in ["rating", "credit"]):
        return "rating_report"
    if any(kw in name_lower for kw in ["legal", "ecourt", "lawsuit", "litigation"]):
        return "legal_filing"
    if any(kw in name_lower for kw in ["news", "intelligence", "article"]):
        return "news_report"
    if any(kw in name_lower for kw in ["board", "minute", "meeting"]):
        return "board_minutes"
    if any(kw in name_lower for kw in ["shareholder", "shareholding", "pattern"]):
        return "shareholding"
    if any(kw in name_lower for kw in ["gst", "itr", "tax", "bank"]):
        return "structured_financial"
    if any(kw in name_lower for kw in ["site", "visit", "diligence", "interview"]):
        return "primary_insight"
    if any(kw in name_lower for kw in ["credit_manager", "note", "daily"]):
        return "credit_notes"

    return DOC_TYPE_MAP.get(fmt, "other")


def _ingest_json_outputs(store: VectorStore, embedder):
    """Also ingest any structured JSON outputs for RAG retrieval."""
    output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    if not os.path.isdir(output_dir):
        return

    json_files = [f for f in os.listdir(output_dir) if f.endswith(".json")]
    if not json_files:
        return

    print(f"\n[BONUS] Ingesting {len(json_files)} structured JSON output(s)...")

    for jf in json_files:
        try:
            with open(os.path.join(output_dir, jf), "r", encoding="utf-8") as f:
                data = json.load(f)

            # Convert each top-level key into a chunk
            chunks = []
            for key, value in data.items():
                text = f"[STRUCTURED OUTPUT: {key}]\n{json.dumps(value, indent=2)}"
                chunks.append({
                    "text": text[:8000],  # Truncate if needed
                    "metadata": {
                        "source": jf,
                        "doc_type": "structured_output",
                        "section": key,
                        "section_type": key,
                        "chunk_id": f"{jf}__{key}",
                    },
                })

            if chunks:
                texts = [c["text"] for c in chunks]
                embeddings = embedder.embed_texts(texts)
                store.add_documents(chunks, embeddings)
                print(f"    {jf}: {len(chunks)} sections ingested")

        except Exception as e:
            print(f"    {jf}: ERROR — {e}")
