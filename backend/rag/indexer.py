"""RAG indexer — builds vector search indices from the knowledge base."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.knowledge.loader import knowledge_loader
from backend.rag.embedder import embedder
from backend.rag.vector_store import (
    COLLECTION_COMMANDS,
    COLLECTION_FEW_SHOT,
    COLLECTION_IDS,
    COLLECTION_INTENTS,
    vector_store,
)

logger = logging.getLogger(__name__)


def _command_to_text(doc: dict[str, Any]) -> str:
    """Serialize a command JSON doc into Chinese descriptive text for embedding."""
    name = doc.get("name", "")
    desc = doc.get("description", "")
    syntax = doc.get("syntax", "")
    category = doc.get("category", "")
    use_cases = doc.get("common_use_cases", [])

    parts = [f"命令: /{name}", f"描述: {desc}", f"分类: {category}"]
    if syntax:
        parts.append(f"语法: {syntax}")
    if use_cases:
        parts.append(f"常见场景: {', '.join(use_cases)}")

    # Add parameter names for searchability
    params = doc.get("parameters", [])
    if params:
        param_names = [p.get("name", "") for p in params]
        parts.append(f"参数: {', '.join(param_names)}")

    # Add example descriptions
    examples = doc.get("examples", [])
    for ex in examples[:3]:
        ex_desc = ex.get("description", "")
        if ex_desc:
            parts.append(f"示例: {ex_desc}")

    return "\n".join(parts)


def _id_entry_to_text(entry: dict[str, Any], category: str) -> str:
    """Serialize an ID entry into text for embedding."""
    id_val = entry.get("id", "")
    name = entry.get("name", id_val)
    desc = entry.get("description", "")
    sub_cat = entry.get("category", entry.get("sub_category", ""))

    text = f"{id_val} ({name})"
    if desc:
        text += f": {desc}"
    text += f". 类型: {category}"
    if sub_cat:
        text += f"/{sub_cat}"
    return text


def _intent_scenario_to_text(scenario: dict[str, Any], category_name: str) -> str:
    """Serialize an intent scenario into text for embedding."""
    keywords = scenario.get("keywords", [])
    cmd = scenario.get("correct_command", "")
    explanation = scenario.get("explanation", "")
    example = scenario.get("usage_example", "")

    parts = [
        f"意图类别: {category_name}",
        f"关键词: {', '.join(keywords)}",
        f"正确命令: {cmd}",
    ]
    if explanation:
        parts.append(f"说明: {explanation}")
    if example:
        parts.append(f"用法: {example}")

    mistake = scenario.get("common_mistake")
    if mistake:
        parts.append(
            f"常见误用: 不要用 /{mistake['wrong']}（{mistake['reason']}）"
        )

    return "\n".join(parts)


async def index_commands() -> int:
    """Index all command documents into the 'commands' collection.

    Returns the number of documents indexed.
    """
    all_docs = knowledge_loader.enumerate_all_commands()
    if not all_docs:
        logger.warning("No command documents found to index")
        return 0

    texts = [_command_to_text(doc) for doc in all_docs]
    ids = [f"cmd_{doc.get('name', str(i))}" for i, doc in enumerate(all_docs)]
    metadatas = [
        {
            "name": doc.get("name", ""),
            "category": doc.get("category", ""),
            "description": doc.get("description", ""),
        }
        for doc in all_docs
    ]

    logger.info("Embedding %d command documents...", len(texts))
    embeddings = await embedder.embed_batch(texts)

    vector_store.upsert(
        COLLECTION_COMMANDS,
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    logger.info("Indexed %d commands into '%s'", len(texts), COLLECTION_COMMANDS)
    return len(texts)


async def index_ids() -> int:
    """Index all ID entries into the 'ids' collection.

    Returns the number of documents indexed.
    """
    all_ids = knowledge_loader.enumerate_all_ids()
    if not all_ids:
        logger.warning("No ID files found to index")
        return 0

    texts: list[str] = []
    ids: list[str] = []
    metadatas: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for category, entries in all_ids.items():
        for i, entry in enumerate(entries):
            id_val = entry.get("id", str(i))
            doc_id = f"id_{category}_{id_val}"
            # Deduplicate: skip if already seen
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            text = _id_entry_to_text(entry, category)
            texts.append(text)
            ids.append(doc_id)
            metadatas.append({
                "id": id_val,
                "category": category,
                "name": entry.get("name", id_val),
            })

    logger.info("Embedding %d ID entries...", len(texts))
    embeddings = await embedder.embed_batch(texts)

    vector_store.upsert(
        COLLECTION_IDS,
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    logger.info("Indexed %d IDs into '%s'", len(texts), COLLECTION_IDS)
    return len(texts)


async def index_intents() -> int:
    """Index intent scenarios + disambiguation rules into the 'intents' collection.

    Returns the number of documents indexed.
    """
    intent_map = knowledge_loader.load_intent_map()
    if not intent_map:
        logger.warning("No intent map found to index")
        return 0

    texts: list[str] = []
    ids: list[str] = []
    metadatas: list[dict[str, Any]] = []

    # Index scenarios
    for cat in intent_map.get("intent_categories", []):
        cat_name = cat.get("category", "")
        for j, sc in enumerate(cat.get("scenarios", [])):
            text = _intent_scenario_to_text(sc, cat_name)
            doc_id = f"intent_{cat_name}_{j}"
            texts.append(text)
            ids.append(doc_id)
            metadatas.append({
                "category": cat_name,
                "correct_command": sc.get("correct_command", ""),
                "doc_type": "scenario",
            })

    # Index disambiguation rules
    for i, rule in enumerate(intent_map.get("disambiguation_rules", [])):
        word = rule.get("ambiguous_word", "")
        decision = rule.get("decision_rule", "")
        text = f"歧义词: {word}\n消歧规则: {decision}"
        texts.append(text)
        ids.append(f"disambig_{i}")
        metadatas.append({
            "category": "disambiguation",
            "doc_type": "disambiguation",
        })

    if not texts:
        return 0

    logger.info("Embedding %d intent entries...", len(texts))
    embeddings = await embedder.embed_batch(texts)

    vector_store.upsert(
        COLLECTION_INTENTS,
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    logger.info("Indexed %d intents into '%s'", len(texts), COLLECTION_INTENTS)
    return len(texts)


async def index_few_shot() -> int:
    """Index few-shot examples into the 'few_shot' collection.

    Embeds the user input text; stores full output JSON in metadata.
    Returns the number of documents indexed.
    """
    few_shot_dir = knowledge_loader.base_dir / "few_shot"
    if not few_shot_dir.exists():
        logger.warning("Few-shot directory not found: %s", few_shot_dir)
        return 0

    texts: list[str] = []
    ids: list[str] = []
    metadatas: list[dict[str, Any]] = []

    type_map = {
        "command": "simple_command",
        "execute": "execute_chain",
        "rawtext": "rawtext",
        "selector": "selector",
        "project": "project",
    }

    for fs_file in few_shot_dir.glob("*.json"):
        agent_type = fs_file.stem  # e.g., "command", "execute"
        try:
            with open(fs_file, encoding="utf-8") as f:
                examples = json.load(f)
            if not isinstance(examples, list):
                continue
        except (json.JSONDecodeError, OSError):
            continue

        output_type = type_map.get(agent_type, agent_type)

        for i, ex in enumerate(examples):
            user_input = ex.get("input", "")
            if not user_input:
                continue

            # Embed the user input for semantic matching
            texts.append(user_input)
            ids.append(f"fs_{agent_type}_{i}")

            # Store output JSON and metadata
            output_str = json.dumps(ex.get("output", {}), ensure_ascii=False)
            # Truncate very long outputs for metadata (ChromaDB has limits)
            if len(output_str) > 4000:
                output_str = output_str[:4000]

            metadatas.append({
                "agent_type": agent_type,
                "output_type": output_type,
                "output_json": output_str,
                "commands_used": ",".join(ex.get("commands_used", [])),
            })

    if not texts:
        return 0

    logger.info("Embedding %d few-shot examples...", len(texts))
    embeddings = await embedder.embed_batch(texts)

    vector_store.upsert(
        COLLECTION_FEW_SHOT,
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    logger.info("Indexed %d few-shot examples into '%s'", len(texts), COLLECTION_FEW_SHOT)
    return len(texts)


async def build_all_indices(force: bool = False) -> dict[str, int]:
    """Build all 4 vector indices.

    Args:
        force: If True, delete existing collections before rebuilding.

    Returns:
        Dict mapping collection name to number of documents indexed.
    """
    if force:
        for name in [COLLECTION_COMMANDS, COLLECTION_IDS, COLLECTION_INTENTS, COLLECTION_FEW_SHOT]:
            vector_store.delete_collection(name)

    results = {}
    results[COLLECTION_COMMANDS] = await index_commands()
    results[COLLECTION_IDS] = await index_ids()
    results[COLLECTION_INTENTS] = await index_intents()
    results[COLLECTION_FEW_SHOT] = await index_few_shot()

    total = sum(results.values())
    logger.info("RAG indexing complete: %d total documents across %d collections", total, len(results))
    return results
