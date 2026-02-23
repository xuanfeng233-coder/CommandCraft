"""ChromaDB vector store wrapper for RAG subsystem."""

from __future__ import annotations

import logging
from typing import Any

import chromadb

from backend.config import CHROMADB_DIR

logger = logging.getLogger(__name__)

# Collection names
COLLECTION_COMMANDS = "commands"
COLLECTION_IDS = "ids"
COLLECTION_INTENTS = "intents"
COLLECTION_FEW_SHOT = "few_shot"

ALL_COLLECTIONS = [
    COLLECTION_COMMANDS,
    COLLECTION_IDS,
    COLLECTION_INTENTS,
    COLLECTION_FEW_SHOT,
]


class VectorStore:
    """Persistent ChromaDB vector store with 4 collections."""

    def __init__(self, persist_dir: str | None = None) -> None:
        self._persist_dir = persist_dir or str(CHROMADB_DIR)
        self._client: chromadb.ClientAPI | None = None

    @property
    def client(self) -> chromadb.ClientAPI:
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            logger.info("ChromaDB initialized at %s", self._persist_dir)
        return self._client

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        """Get or create a collection by name."""
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        collection_name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert documents into a collection."""
        col = self.get_or_create_collection(collection_name)
        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.debug(
            "Upserted %d docs into collection '%s'", len(ids), collection_name
        )

    def query(
        self,
        collection_name: str,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query a collection with a vector.

        Returns ChromaDB query result dict with keys:
            ids, documents, metadatas, distances
        """
        col = self.get_or_create_collection(collection_name)
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, col.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        return col.query(**kwargs)

    def collections_exist(self) -> dict[str, bool]:
        """Check which collections exist and have documents."""
        result = {}
        for name in ALL_COLLECTIONS:
            try:
                col = self.client.get_or_create_collection(name)
                result[name] = col.count() > 0
            except Exception:
                result[name] = False
        return result

    def collection_count(self, name: str) -> int:
        """Return the number of documents in a collection."""
        try:
            col = self.client.get_or_create_collection(name)
            return col.count()
        except Exception:
            return 0

    def delete_collection(self, name: str) -> None:
        """Delete a collection entirely."""
        try:
            self.client.delete_collection(name)
            logger.info("Deleted collection '%s'", name)
        except Exception as e:
            logger.warning("Failed to delete collection '%s': %s", name, e)


# Singleton
vector_store = VectorStore()
