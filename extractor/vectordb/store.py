"""
vectordb/store.py
FAISS-based persistent vector store for RAG retrieval.
Fast, handles millions of vectors, industry standard.
Metadata stored in a JSON sidecar file.

Dimension is dynamic — set by the embedder:
    Gemini gemini-embedding-001 → 3072
    HuggingFace multilingual    → 768
"""

import json
import os

import faiss
import numpy as np


# Store path relative to extractor root
STORE_DIR = os.path.join(os.path.dirname(__file__), "faiss_store")


class VectorStore:
    """
    Persistent FAISS vector store with JSON metadata sidecar.
    Uses IndexFlatIP (Inner Product on normalized vectors = cosine similarity).

    Files on disk:
    - faiss_store/index.faiss  — the FAISS index
    - faiss_store/metadata.json — chunk texts + metadata
    """

    def __init__(self, dimension: int = None):
        """
        Args:
            dimension: Embedding dimension. If None, reads from existing index
                       or defaults to 3072 (Gemini). Set to 768 for HuggingFace.
        """
        os.makedirs(STORE_DIR, exist_ok=True)

        self._index_path = os.path.join(STORE_DIR, "index.faiss")
        self._meta_path  = os.path.join(STORE_DIR, "metadata.json")

        # Load existing or create new
        if os.path.exists(self._index_path) and os.path.exists(self._meta_path):
            self.index = faiss.read_index(self._index_path)
            self.dimension = self.index.d  # Read dimension from existing index
            with open(self._meta_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self.dimension = dimension or 3072
            self.index = faiss.IndexFlatIP(self.dimension)
            self._data = {"documents": [], "metadatas": [], "ids": []}

        print(f"    [VectorStore] FAISS index — {self.index.ntotal} existing vectors ({self.index.d}D)")

    def add_documents(self, chunks: list, embeddings: list):
        """
        Add chunks with embeddings to the FAISS index.

        Args:
            chunks: List of dicts with keys: text, metadata
            embeddings: List of embedding vectors
        """
        if not chunks:
            return

        # Normalize embeddings for cosine similarity via inner product
        vectors = np.array(embeddings, dtype=np.float32)
        faiss.normalize_L2(vectors)

        # Add to FAISS index
        self.index.add(vectors)

        # Store metadata
        for chunk in chunks:
            self._data["ids"].append(chunk["metadata"]["chunk_id"])
            self._data["documents"].append(chunk["text"])
            meta = {}
            for k, v in chunk["metadata"].items():
                meta[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v
            self._data["metadatas"].append(meta)

        # Persist to disk
        self._save()

        print(f"    [VectorStore] Added {len(chunks)} chunks. "
              f"Total: {self.index.ntotal}")

    def query(self, query_embedding: list, n_results: int = 5,
              where: dict = None) -> list:
        """
        Similarity search using cosine similarity.

        Args:
            query_embedding: Query vector (dimension must match index)
            n_results: Number of results to return
            where: Optional metadata filter (e.g. {"doc_type": "legal"})

        Returns:
            List of dicts with: text, metadata, relevance (0-1, higher = better)
        """
        if self.index.ntotal == 0:
            return []

        # Normalize query vector
        q_vec = np.array([query_embedding], dtype=np.float32)
        faiss.normalize_L2(q_vec)

        # Search more results if filtering, to ensure we get enough after filter
        search_k = n_results * 5 if where else n_results
        search_k = min(search_k, self.index.ntotal)

        scores, indices = self.index.search(q_vec, search_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for empty slots
                continue

            meta = self._data["metadatas"][idx]

            # Apply metadata filter
            if where:
                match = all(meta.get(k) == v for k, v in where.items())
                if not match:
                    continue

            results.append({
                "text": self._data["documents"][idx],
                "metadata": meta,
                "relevance": round(float(score), 4),
            })

            if len(results) >= n_results:
                break

        return results

    def get_stats(self) -> dict:
        """Return collection statistics."""
        sources = set()
        doc_types = set()
        for meta in self._data["metadatas"]:
            sources.add(meta.get("source", "unknown"))
            doc_types.add(meta.get("doc_type", "unknown"))

        return {
            "total_chunks": self.index.ntotal,
            "unique_sources": len(sources),
            "sources": sorted(sources),
            "doc_types": sorted(doc_types),
            "dimension": self.dimension,
        }

    def clear(self):
        """Delete all data and reset the index."""
        self.index = faiss.IndexFlatIP(self.dimension)
        self._data = {"documents": [], "metadatas": [], "ids": []}
        self._save()
        print("    [VectorStore] Index cleared.")

    def _save(self):
        """Persist index and metadata to disk."""
        faiss.write_index(self.index, self._index_path)
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
