"""Local embedding client using sentence-transformers (BAAI/bge-m3).

Replaces Ollama bge-m3 embedding.  Produces identical vectors so existing
ChromaDB indices remain valid — no re-indexing needed.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import EMBEDDING_MODEL_NAME, EMBEDDING_BATCH_SIZE

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Lazy-loading sentence-transformers wrapper."""

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME) -> None:
        self._model_name = model_name
        self._model: Any = None  # SentenceTransformer instance

    def _load_model(self) -> None:
        """Load the model on first use (downloads ~2.4 GB on first run)."""
        if self._model is not None:
            return
        logger.info("Loading embedding model '%s' ...", self._model_name)
        from sentence_transformers import SentenceTransformer
        try:
            self._model = SentenceTransformer(self._model_name, local_files_only=True)
        except OSError:
            logger.info("Local cache not found, downloading model (first run only, ~2.4 GB)...")
            self._model = SentenceTransformer(self._model_name)
        logger.info("Embedding model loaded successfully (dim=%d)", self._model.get_sentence_embedding_dimension())

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        self._load_model()
        if not text or not text.strip():
            text = "(empty)"
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> list[list[float]]:
        """Embed a batch of texts."""
        self._load_model()
        # Sanitize empty strings
        sanitized = [t if t.strip() else "(empty)" for t in texts]
        vectors = self._model.encode(
            sanitized,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(sanitized) > 50,
        )
        return [v.tolist() for v in vectors]

    def is_available(self) -> bool:
        """Check if the embedding model can be loaded."""
        try:
            self._load_model()
            return True
        except Exception as e:
            logger.warning("Embedding model not available: %s", e)
            return False


# Singleton
embedding_client = EmbeddingClient()
