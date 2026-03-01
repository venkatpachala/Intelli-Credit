"""
build_vectordb.py
Standalone entry point to build the vector database from input documents.

Usage:
  python build_vectordb.py --folder input                     # Build the DB
  python build_vectordb.py --folder input --clear             # Rebuild from scratch
  python build_vectordb.py --query "Salesforce revenue FY2024"  # Test retrieval
  python build_vectordb.py --stats                            # Show collection stats
"""

import argparse
import json
import os
import sys

# Ensure imports work from extractor root
sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(
        description="Build and query the RAG vector database"
    )
    parser.add_argument("--folder", type=str, default="input",
                        help="Input folder containing documents (default: input)")
    parser.add_argument("--clear", action="store_true",
                        help="Clear existing vector store before ingesting")
    parser.add_argument("--query", type=str, default=None,
                        help="Run a test retrieval query")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Number of results for query (default: 5)")
    parser.add_argument("--stats", action="store_true",
                        help="Show vector store statistics")
    parser.add_argument("--filter", type=str, default=None,
                        help='Filter by doc_type (e.g. "legal_filing")')

    args = parser.parse_args()

    # ── QUERY MODE ────────────────────────────────────────────
    if args.query:
        from vectordb.embedder import get_embedder
        from vectordb.store import VectorStore

        print(f"\n{'='*60}")
        print(f"  RAG RETRIEVAL QUERY")
        print(f"{'='*60}")
        print(f"  Query: {args.query}")
        if args.filter:
            print(f"  Filter: doc_type = {args.filter}")
        print(f"  Top-K: {args.top_k}")
        print(f"{'='*60}\n")

        embedder = get_embedder()
        store = VectorStore(dimension=embedder.DIMENSIONS)

        # Generate query embedding
        query_vec = embedder.embed_query(args.query)

        # Search
        where = {"doc_type": args.filter} if args.filter else None
        results = store.query(query_vec, n_results=args.top_k, where=where)

        if not results:
            print("  No results found.")
            return

        for i, r in enumerate(results, 1):
            print(f"  ── Result {i} ({'relevance: ' + str(r['relevance'])}) ──")
            print(f"  Source: {r['metadata'].get('source', '?')}")
            print(f"  Type:   {r['metadata'].get('doc_type', '?')}")
            print(f"  Section:{r['metadata'].get('section_type', '?')}")
            # Show first 300 chars of text
            text_preview = r["text"][:300].replace("\n", " ")
            print(f"  Text:   {text_preview}...")
            print()

        return

    # ── STATS MODE ────────────────────────────────────────────
    if args.stats:
        from vectordb.store import VectorStore

        store = VectorStore()
        stats = store.get_stats()

        print(f"\n{'='*60}")
        print(f"  VECTOR STORE STATISTICS")
        print(f"{'='*60}")
        print(f"  Total chunks   : {stats['total_chunks']}")
        print(f"  Unique sources : {stats['unique_sources']}")
        print(f"  Sources        : {', '.join(stats['sources'])}")
        print(f"  Document types : {', '.join(stats['doc_types'])}")
        print(f"{'='*60}\n")
        return

    # ── INGEST MODE ───────────────────────────────────────────
    from vectordb.ingest import ingest_folder

    result = ingest_folder(args.folder, clear_existing=args.clear)

    # Save summary as JSON
    summary_path = os.path.join("output", "vectordb_ingestion_summary.json")
    os.makedirs("output", exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
