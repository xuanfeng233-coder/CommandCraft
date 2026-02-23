"""CLI script to build/rebuild RAG vector indices.

Usage (must use venv Python):
    venv\\Scripts\\python.exe scripts/build_index.py                     # Build all
    venv\\Scripts\\python.exe scripts/build_index.py --collection commands  # Build one
    venv\\Scripts\\python.exe scripts/build_index.py --force              # Force rebuild
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Build RAG vector indices")
    parser.add_argument(
        "--collection",
        choices=["commands", "ids", "intents", "few_shot"],
        help="Build only a specific collection (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild by deleting existing collections first",
    )
    args = parser.parse_args()

    from backend.rag.embedder import embedder
    from backend.rag.indexer import (
        build_all_indices,
        index_commands,
        index_few_shot,
        index_ids,
        index_intents,
    )
    from backend.rag.vector_store import vector_store

    # Check embedding model
    logger.info("Checking embedding model availability...")
    available = await embedder.check_model()
    if not available:
        logger.error(
            "Embedding model not available. Install: pip install sentence-transformers"
        )
        sys.exit(1)
    logger.info("Embedding model ready")

    if args.collection:
        # Build single collection
        name = args.collection
        if args.force:
            vector_store.delete_collection(name)

        indexers = {
            "commands": index_commands,
            "ids": index_ids,
            "intents": index_intents,
            "few_shot": index_few_shot,
        }
        count = await indexers[name]()
        logger.info("Indexed %d documents into '%s'", count, name)
    else:
        # Build all
        results = await build_all_indices(force=args.force)
        total = sum(results.values())
        logger.info("=== Indexing complete ===")
        for name, count in results.items():
            logger.info("  %s: %d documents", name, count)
        logger.info("  Total: %d documents", total)

    # Print collection stats
    status = vector_store.collections_exist()
    logger.info("=== Collection status ===")
    for name, exists in status.items():
        count = vector_store.collection_count(name)
        logger.info("  %s: %s (%d docs)", name, "OK" if exists else "EMPTY", count)


if __name__ == "__main__":
    asyncio.run(main())
