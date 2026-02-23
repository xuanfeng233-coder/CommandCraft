"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import chat, export, health, knowledge, settings, subscription
from backend.config import (
    CORS_ORIGINS,
    SUBSCRIPTION_API_KEY,
    SUBSCRIPTION_BASE_URL,
    SUBSCRIPTION_ENABLED,
    SUBSCRIPTION_MODEL,
)
from backend.models.database import session_db
from backend.subscription.database import subscription_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await session_db.init()
    await subscription_db.init()

    # Init subscription LLM client if configured
    if SUBSCRIPTION_ENABLED:
        from backend.subscription.llm_context import init_subscription_client
        init_subscription_client(
            api_key=SUBSCRIPTION_API_KEY,
            base_url=SUBSCRIPTION_BASE_URL,
            model=SUBSCRIPTION_MODEL,
        )
        logger.info("Subscription service enabled (model=%s)", SUBSCRIPTION_MODEL)
    else:
        logger.info("Subscription service disabled (SUBSCRIPTION_API_KEY not set)")

    # Check RAG index status
    try:
        from backend.rag.vector_store import vector_store
        status = vector_store.collections_exist()
        all_exist = all(status.values())
        if all_exist:
            logger.info("RAG indices ready: %s", status)
        else:
            missing = [k for k, v in status.items() if not v]
            logger.warning(
                "RAG indices missing: %s — run 'python scripts/build_index.py' to build",
                missing,
            )
            # Check if embedding model is available
            from backend.utils.embedding_client import embedding_client
            if embedding_client.is_available():
                logger.info("Embedding model available, auto-building indices...")
                from backend.rag.indexer import build_all_indices
                results = await build_all_indices()
                logger.info("Auto-built RAG indices: %s", results)
            else:
                logger.warning(
                    "Embedding model not available — install sentence-transformers and BAAI/bge-m3"
                )
    except Exception:
        logger.warning("RAG index check failed", exc_info=True)

    yield
    await subscription_db.close()
    await session_db.close()


app = FastAPI(
    title="Minecraft BE AI 命令生成器",
    description="基于云端 LLM 的 Minecraft 基岩版命令智能生成工具",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(export.router)
app.include_router(health.router)
app.include_router(knowledge.router)
app.include_router(settings.router)
app.include_router(subscription.router)
