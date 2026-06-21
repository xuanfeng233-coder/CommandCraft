"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    auth,
    build,
    chat,
    export,
    health,
    internal_admin,
    knowledge,
    settings,
    subscription,
)
from backend.auth.database import auth_db
from backend.config import (
    AUTH_INACTIVE_DELETE_DAYS,
    BUILD_CHAT_MODEL,
    BUILD_MODEL,
    CORS_ORIGINS,
    SUBSCRIPTION_API_KEY,
    SUBSCRIPTION_BASE_URL,
    SUBSCRIPTION_ENABLED,
    SUBSCRIPTION_MODEL,
    WXPAY_API_KEY,
    WXPAY_BASE_URL,
    WXPAY_ENABLED,
)
from backend.models.database import session_db
from backend.subscription.database import subscription_db
from backend.subscription.wxpay_client import init_wxpay_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await session_db.init()
    await subscription_db.init()

    # Init auth DB (shares connection with subscription DB)
    await auth_db.init(db=subscription_db.db)

    # Init project manager for build mode
    from backend.build.project_manager import project_manager
    await project_manager.init()

    # Init subscription LLM client if configured
    if SUBSCRIPTION_ENABLED:
        from backend.subscription.llm_context import (
            init_subscription_client, init_build_client, init_build_chat_client,
        )
        init_subscription_client(
            api_key=SUBSCRIPTION_API_KEY,
            base_url=SUBSCRIPTION_BASE_URL,
            model=SUBSCRIPTION_MODEL,
        )
        init_build_client(
            api_key=SUBSCRIPTION_API_KEY,
            base_url=SUBSCRIPTION_BASE_URL,
            model=BUILD_MODEL,
        )
        init_build_chat_client(
            api_key=SUBSCRIPTION_API_KEY,
            base_url=SUBSCRIPTION_BASE_URL,
            model=BUILD_CHAT_MODEL,
        )
        logger.info("Subscription service enabled (model=%s)", SUBSCRIPTION_MODEL)
        logger.info("Build mode enabled (reasoner=%s, chat=%s)", BUILD_MODEL, BUILD_CHAT_MODEL)
    else:
        logger.info("Subscription service disabled (SUBSCRIPTION_API_KEY not set)")

    # Init WXpay client
    wxpay_client_instance = None
    if WXPAY_ENABLED:
        wxpay_client_instance = init_wxpay_client(
            base_url=WXPAY_BASE_URL, api_key=WXPAY_API_KEY,
        )
        await wxpay_client_instance.init()
        logger.info("WXpay enabled (base_url=%s)", WXPAY_BASE_URL)
    else:
        logger.info("WXpay disabled (WXPAY_API_KEY not set)")

    # Init wiki knowledge search index
    from backend.knowledge.wiki_search import wiki_searcher
    wiki_searcher.init()

    # Cleanup inactive users on startup
    inactive_ids = await auth_db.get_inactive_user_ids(AUTH_INACTIVE_DELETE_DAYS)
    if inactive_ids:
        await session_db.cleanup_by_user_ids(inactive_ids)
        cleaned = await auth_db.cleanup_inactive_users(AUTH_INACTIVE_DELETE_DAYS)
        logger.info("Startup cleanup: removed %d inactive users", cleaned)
    await auth_db.cleanup_expired_sessions()

    # Start periodic cleanup task
    import asyncio

    async def _periodic_cleanup():
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                expired = await auth_db.cleanup_expired_sessions()
                inactive_ids = await auth_db.get_inactive_user_ids(AUTH_INACTIVE_DELETE_DAYS)
                removed = 0
                if inactive_ids:
                    await session_db.cleanup_by_user_ids(inactive_ids)
                    removed = await auth_db.cleanup_inactive_users(AUTH_INACTIVE_DELETE_DAYS)
                if expired or removed:
                    logger.info("Periodic cleanup: %d expired sessions, %d inactive users", expired, removed)
            except Exception:
                logger.warning("Periodic cleanup failed", exc_info=True)

    asyncio.create_task(_periodic_cleanup())

    yield

    await project_manager.close()
    if wxpay_client_instance is not None:
        await wxpay_client_instance.close()
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

app.include_router(auth.router)
app.include_router(build.router)
app.include_router(chat.router)
app.include_router(export.router)
app.include_router(health.router)
app.include_router(internal_admin.router)
app.include_router(knowledge.router)
app.include_router(settings.router)
app.include_router(subscription.router)
