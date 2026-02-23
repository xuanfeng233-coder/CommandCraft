"""Embedding wrapper for RAG subsystem using sentence-transformers."""

from __future__ import annotations

import logging

from backend.utils.embedding_client import embedding_client

logger = logging.getLogger(__name__)


class Embedder:
    """Wraps embedding_client methods for RAG use."""

    async def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        return await embedding_client.embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        return await embedding_client.embed_batch(texts)

    async def check_model(self) -> bool:
        """Check if the embedding model is available."""
        return embedding_client.is_available()


# Singleton
embedder = Embedder()
