"""
vectordb/embedder.py
Embedding provider with automatic fallback.
Primary: Gemini gemini-embedding-001 (3072-dim)
Fallback: HuggingFace Inference API (768-dim, multilingual)

All config is read from .env:
    EMBEDDING_PROVIDER=gemini|huggingface
    GEMINI_EMBEDDING_MODEL=gemini-embedding-001
    HF_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
"""

import os
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# ── Factory ──────────────────────────────────────────────────

def get_embedder():
    """
    Returns the appropriate embedder based on .env config.
    Falls back to HuggingFace if Gemini key is missing.
    """
    provider = os.getenv("EMBEDDING_PROVIDER", "gemini").lower()

    if provider == "huggingface":
        return HuggingFaceEmbedder()

    # Default: try Gemini, fall back to HuggingFace
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        return GeminiEmbedder()
    else:
        print("    [Embedder] GEMINI_API_KEY not found, falling back to HuggingFace")
        return HuggingFaceEmbedder()


# ── Gemini Embedder ──────────────────────────────────────────

class GeminiEmbedder:
    """
    Generates embeddings using Gemini embedding model.
    3072-dimensional vectors (gemini-embedding-001), supports multilingual.
    """

    def __init__(self):
        self.model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.BATCH_SIZE = 100
        self.DIMENSIONS = 3072

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found in environment.\n"
                "Set it in your .env file: GEMINI_API_KEY=your-key"
            )

        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
        except ImportError:
            raise ImportError(
                "google-genai not installed.\n"
                "Run: pip install google-genai"
            )

        print(f"    [Embedder] Using Gemini {self.model} ({self.DIMENSIONS}D vectors)")

    def embed_texts(self, texts: list) -> list:
        """Embed a list of texts. Returns list of embedding vectors."""
        if not texts:
            return []

        all_embeddings = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_num = (i // self.BATCH_SIZE) + 1
            total_batches = (len(texts) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
            embeddings = self._embed_batch(batch, batch_num, total_batches)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def embed_query(self, query: str) -> list:
        """Embed a single query string."""
        result = self._embed_batch([query], 1, 1)
        return result[0]

    def _embed_batch(self, texts: list, batch_num: int, total: int,
                     max_retries: int = 3) -> list:
        """Embed a single batch with retry logic."""
        truncated = [t[:8000] if len(t) > 8000 else t for t in texts]

        for attempt in range(max_retries):
            try:
                response = self.client.models.embed_content(
                    model=self.model,
                    contents=truncated,
                )
                vectors = [e.values for e in response.embeddings]

                if batch_num == 1 or batch_num == total:
                    print(f"    [Embedder] Batch {batch_num}/{total}: "
                          f"{len(vectors)} embeddings generated")
                return vectors

            except Exception as e:
                wait = 2 ** attempt
                print(f"    [Embedder] Batch {batch_num} failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    print(f"    [Embedder] Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"Embedding failed after {max_retries} attempts: {e}"
                    )


# ── HuggingFace Embedder ─────────────────────────────────────

class HuggingFaceEmbedder:
    """
    Generates embeddings using HuggingFace Inference API.
    768-dimensional vectors, multilingual (Hindi + English).
    Uses sentence-transformers/paraphrase-multilingual-mpnet-base-v2 by default.
    """

    def __init__(self):
        self.model = os.getenv(
            "HF_EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
        )
        self.api_key = os.getenv("HUGGINGFACE_API_KEY")
        self.BATCH_SIZE = 50  # HF API has smaller batch limits
        # Auto-detect dimension based on model
        if "bge-large" in self.model:
            self.DIMENSIONS = 1024
        elif "bge-base" in self.model:
            self.DIMENSIONS = 768
        else:
            self.DIMENSIONS = 768

        if not self.api_key or self.api_key == "your-huggingface-api-key-here":
            raise ValueError(
                "HUGGINGFACE_API_KEY not found or not set.\n"
                "Set it in your .env file: HUGGINGFACE_API_KEY=hf_..."
            )

        self.api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self.model}"
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

        print(f"    [Embedder] Using HuggingFace {self.model.split('/')[-1]} ({self.DIMENSIONS}D vectors)")

    def embed_texts(self, texts: list) -> list:
        """Embed a list of texts. Returns list of embedding vectors."""
        if not texts:
            return []

        all_embeddings = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_num = (i // self.BATCH_SIZE) + 1
            total_batches = (len(texts) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
            embeddings = self._embed_batch(batch, batch_num, total_batches)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def embed_query(self, query: str) -> list:
        """Embed a single query string."""
        result = self._embed_batch([query], 1, 1)
        return result[0]

    def _embed_batch(self, texts: list, batch_num: int, total: int,
                     max_retries: int = 3) -> list:
        """Embed a single batch via HF Inference API with retry logic."""
        import requests

        # Truncate to ~512 tokens ≈ 2000 chars for sentence-transformers
        truncated = [t[:2000] if len(t) > 2000 else t for t in texts]

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url,
                    headers=self.headers,
                    json={"inputs": truncated, "options": {"wait_for_model": True}},
                    timeout=60,
                )
                response.raise_for_status()
                embeddings = response.json()

                # HF returns nested lists — each embedding is a list of floats
                # For sentence-transformers, the response is already the right shape
                vectors = []
                for emb in embeddings:
                    if isinstance(emb[0], list):
                        # Model returned token-level embeddings — mean pool
                        import numpy as np
                        vec = np.mean(emb, axis=0).tolist()
                        vectors.append(vec)
                    else:
                        vectors.append(emb)

                if batch_num == 1 or batch_num == total:
                    print(f"    [Embedder] Batch {batch_num}/{total}: "
                          f"{len(vectors)} embeddings generated")
                return vectors

            except Exception as e:
                wait = 2 ** attempt
                print(f"    [Embedder] HF batch {batch_num} failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    print(f"    [Embedder] Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"HF embedding failed after {max_retries} attempts: {e}"
                    )
