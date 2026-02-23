"""RAG Retriever — pure code, no LLM.

Performs vector search over ChromaDB collections and returns assembled context.

Optimized for strong cloud LLMs:
- Smart command retrieval: common commands use exact lookup only
- Intent collection skipped (strong LLMs don't need it)
- Few-shot only for project output type
- Compact prompt format (name + syntax + params)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import (
    COMMON_COMMANDS,
    RAG_TOP_K_COMMANDS,
    RAG_TOP_K_FEW_SHOT,
    RAG_TOP_K_IDS,
    SIMILARITY_THRESHOLD,
)
from backend.knowledge.loader import knowledge_loader
from backend.rag.embedder import embedder
from backend.rag.vector_store import (
    COLLECTION_COMMANDS,
    COLLECTION_FEW_SHOT,
    COLLECTION_IDS,
    vector_store,
)

logger = logging.getLogger(__name__)


@dataclass
class RAGContext:
    """Assembled context from RAG retrieval."""

    command_docs: list[dict[str, Any]] = field(default_factory=list)
    id_entries: list[dict[str, Any]] = field(default_factory=list)
    few_shot_examples: list[dict[str, Any]] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Format all retrieved context as a prompt-ready string (full format)."""
        sections: list[str] = []

        if self.command_docs:
            cmd_names = [d.get("name", "") for d in self.command_docs if d.get("name")]
            if cmd_names:
                docs_text = knowledge_loader.format_command_docs_compact(cmd_names)
                sections.append(f"## 相关命令文档\n{docs_text}")

        if self.id_entries:
            id_lines = [f"- {entry.get('document', '')}" for entry in self.id_entries]
            sections.append("## 相关 ID\n" + "\n".join(id_lines))

        if self.few_shot_examples:
            fs_parts = ["## 参考示例\n"]
            for i, ex in enumerate(self.few_shot_examples, 1):
                user_input = ex.get("input", "")
                output_json = ex.get("output_json", "{}")
                if len(output_json) > 500:
                    output_json = output_json[:500] + "..."
                fs_parts.append(f"### 示例 {i}")
                fs_parts.append(f"用户需求: {user_input}")
                fs_parts.append(f"输出: ```json\n{output_json}\n```\n")
            sections.append("\n".join(fs_parts))

        return "\n\n".join(sections) if sections else "（无检索到的上下文）"

    def to_prompt_text_compact(self) -> str:
        """Compact format — minimal command docs, no intents, for strong LLMs."""
        sections: list[str] = []

        if self.command_docs:
            cmd_names = [d.get("name", "") for d in self.command_docs if d.get("name")]
            if cmd_names:
                docs_text = knowledge_loader.format_command_docs_minimal(cmd_names)
                if docs_text:
                    sections.append(f"## 相关命令文档\n{docs_text}")

        if self.id_entries:
            id_lines = [f"- {entry.get('document', '')}" for entry in self.id_entries]
            sections.append("## 相关 ID\n" + "\n".join(id_lines))

        if self.few_shot_examples:
            fs_parts = ["## 参考示例\n"]
            for i, ex in enumerate(self.few_shot_examples, 1):
                user_input = ex.get("input", "")
                output_json = ex.get("output_json", "{}")
                if len(output_json) > 500:
                    output_json = output_json[:500] + "..."
                fs_parts.append(f"### 示例 {i}")
                fs_parts.append(f"用户需求: {user_input}")
                fs_parts.append(f"输出: ```json\n{output_json}\n```\n")
            sections.append("\n".join(fs_parts))

        return "\n\n".join(sections) if sections else "（无检索到的上下文）"

    def to_summary(self) -> str:
        """Short summary of what was retrieved (for logging)."""
        parts = []
        if self.command_docs:
            names = [d.get("name", "?") for d in self.command_docs]
            parts.append(f"命令: {', '.join(names)}")
        if self.id_entries:
            parts.append(f"ID: {len(self.id_entries)} 条")
        if self.few_shot_examples:
            parts.append(f"示例: {len(self.few_shot_examples)} 条")
        return "; ".join(parts) if parts else "无匹配"


class RAGRetriever:
    """Retrieves context via ChromaDB vector search.

    Optimized strategies:
    - Common commands: exact lookup only (no vector search)
    - Uncommon commands: exact lookup + semantic search
    - Intents: skipped (strong LLMs don't need them)
    - Few-shot: only for project output type
    """

    async def retrieve_context(
        self,
        query: str,
        exact_command_names: list[str] | None = None,
        id_type_filter: str | None = None,
        output_type: str = "simple_command",
    ) -> RAGContext:
        """Main retrieval entry point.

        Args:
            query: The user's natural language request.
            exact_command_names: If already identified specific commands,
                include their docs directly.
            id_type_filter: Optional category filter for ID search.
            output_type: Task output type — controls few-shot retrieval.

        Returns:
            Assembled RAGContext with retrieved documents.
        """
        ctx = RAGContext()

        # Determine if we need embedding (for semantic search)
        needs_embedding = self._needs_semantic_search(
            exact_command_names, output_type,
        )

        query_embedding: list[float] | None = None
        if needs_embedding:
            try:
                query_embedding = await embedder.embed_single(query)
            except Exception as e:
                logger.error("Failed to embed query: %s", e)
                # Fallback: exact command docs only
                if exact_command_names:
                    for name in exact_command_names:
                        doc = knowledge_loader.get_command_doc(name)
                        if doc:
                            ctx.command_docs.append(doc)
                return ctx

        # 1. Smart command retrieval
        ctx.command_docs = await self._retrieve_commands_smart(
            query_embedding, exact_command_names,
        )

        # 2. ID retrieval (with reduced TOP_K)
        if query_embedding is not None:
            ctx.id_entries = await self._retrieve_ids(
                query_embedding, id_type_filter,
            )

        # 3. Intents: skipped — strong LLMs don't need them

        # 4. Few-shot: only for project type
        if output_type == "project" and query_embedding is not None:
            ctx.few_shot_examples = await self._retrieve_few_shot(query_embedding)

        logger.info("RAG retrieved: %s", ctx.to_summary())
        return ctx

    def _needs_semantic_search(
        self,
        exact_command_names: list[str] | None,
        output_type: str,
    ) -> bool:
        """Determine if we need to run embedding + vector search.

        Returns False when all commands are common (exact lookup suffices)
        and no few-shot is needed.
        """
        # Always need embedding for project (few-shot) or if no commands given
        if output_type == "project" or not exact_command_names:
            return True

        # If any command is uncommon, we need semantic search
        for name in exact_command_names:
            if name not in COMMON_COMMANDS:
                return True

        # All commands are common — still need embedding for ID search
        # but we can skip command vector search
        return True  # IDs still need embedding

    async def _retrieve_commands_smart(
        self,
        query_embedding: list[float] | None,
        exact_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Smart command retrieval based on command commonality.

        - Common commands: exact lookup only (no vector search)
        - Uncommon commands: exact lookup + semantic search supplement
        - No exact names: full semantic search (fallback)
        """
        seen_names: set[str] = set()
        result_docs: list[dict[str, Any]] = []

        if exact_names:
            has_uncommon = False
            for name in exact_names:
                doc = knowledge_loader.get_command_doc(name)
                if doc and name not in seen_names:
                    result_docs.append(doc)
                    seen_names.add(name)
                if name not in COMMON_COMMANDS:
                    has_uncommon = True

            # Only do semantic search if there are uncommon commands
            if has_uncommon and query_embedding is not None:
                remaining = RAG_TOP_K_COMMANDS - len(result_docs)
                if remaining > 0:
                    await self._semantic_search_commands(
                        query_embedding, result_docs, seen_names, remaining,
                    )
        elif query_embedding is not None:
            # No exact names — full semantic search
            await self._semantic_search_commands(
                query_embedding, result_docs, seen_names, RAG_TOP_K_COMMANDS,
            )

        return result_docs

    async def _semantic_search_commands(
        self,
        query_embedding: list[float],
        result_docs: list[dict[str, Any]],
        seen_names: set[str],
        max_results: int,
    ) -> None:
        """Run vector search for commands and append to result_docs."""
        try:
            results = vector_store.query(
                COLLECTION_COMMANDS,
                query_embedding,
                n_results=max_results + 3,  # fetch extra to filter duplicates
            )
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                if len(result_docs) >= len(seen_names) + max_results:
                    break
                distance = results["distances"][0][i]
                if distance > (1 - SIMILARITY_THRESHOLD):
                    continue
                meta = results["metadatas"][0][i]
                cmd_name = meta.get("name", "")
                if cmd_name and cmd_name not in seen_names:
                    doc = knowledge_loader.get_command_doc(cmd_name)
                    if doc:
                        result_docs.append(doc)
                        seen_names.add(cmd_name)
        except Exception as e:
            logger.warning("Semantic command search failed: %s", e)

    async def _retrieve_ids(
        self,
        query_embedding: list[float],
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant ID entries via semantic search."""
        try:
            where = {"category": category_filter} if category_filter else None
            results = vector_store.query(
                COLLECTION_IDS,
                query_embedding,
                n_results=RAG_TOP_K_IDS,
                where=where,
            )
            entries = []
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                distance = results["distances"][0][i]
                if distance > (1 - SIMILARITY_THRESHOLD):
                    continue
                entries.append({
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": distance,
                })
            return entries
        except Exception as e:
            logger.warning("ID retrieval failed: %s", e)
            return []

    async def _retrieve_few_shot(
        self,
        query_embedding: list[float],
    ) -> list[dict[str, Any]]:
        """Retrieve few-shot examples via semantic search (project type only)."""
        try:
            results = vector_store.query(
                COLLECTION_FEW_SHOT,
                query_embedding,
                n_results=RAG_TOP_K_FEW_SHOT,
            )
            entries = []
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                distance = results["distances"][0][i]
                if distance > (1 - SIMILARITY_THRESHOLD):
                    continue
                meta = results["metadatas"][0][i]
                entries.append({
                    "input": results["documents"][0][i],
                    "output_json": meta.get("output_json", "{}"),
                    "output_type": meta.get("output_type", ""),
                    "distance": distance,
                })
            return entries
        except Exception as e:
            logger.warning("Few-shot retrieval failed: %s", e)
            return []


# Singleton
rag_retriever = RAGRetriever()
