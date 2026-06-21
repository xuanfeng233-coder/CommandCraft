"""Application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root (won't override existing env vars)
load_dotenv(BASE_DIR / ".env")
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"
KNOWLEDGE_BASE_BEDROCK_DIR = KNOWLEDGE_BASE_DIR / "bedrock"
KNOWLEDGE_BASE_JAVA_DIR = KNOWLEDGE_BASE_DIR / "java"

# Model parameters
MODEL_TEMPERATURE = float(os.environ.get("MODEL_TEMPERATURE", "0.6"))
MAIN_AGENT_MAX_TOKENS = int(os.environ.get("MAIN_AGENT_MAX_TOKENS", "4096"))
ANALYSIS_AGENT_MAX_TOKENS = int(os.environ.get("ANALYSIS_AGENT_MAX_TOKENS", "4096"))
COMMAND_GENERATOR_MAX_TOKENS = int(os.environ.get("COMMAND_GENERATOR_MAX_TOKENS", "8192"))
SUBTASK_GENERATOR_MAX_TOKENS = int(os.environ.get("SUBTASK_GENERATOR_MAX_TOKENS", "16384"))
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", "5"))
MAX_VALIDATION_RETRIES = int(os.environ.get("MAX_VALIDATION_RETRIES", "1"))
TASK_AGENT_MAX_TOKENS = int(os.environ.get("TASK_AGENT_MAX_TOKENS", "8192"))
SUMMARY_MAX_TOKENS = int(os.environ.get("SUMMARY_MAX_TOKENS", "8192"))
DECOMPOSE_MAX_TOKENS = int(os.environ.get("DECOMPOSE_MAX_TOKENS", "4096"))
MAX_PARALLEL_TASKS = int(os.environ.get("MAX_PARALLEL_TASKS", "8"))
SESSION_STATE_TTL = int(os.environ.get("SESSION_STATE_TTL", "600"))  # seconds

# LLM 韧性
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "60"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_RETRY_BASE_DELAY = float(os.environ.get("LLM_RETRY_BASE_DELAY", "0.5"))
MODEL_CATALOG_TTL = int(os.environ.get("MODEL_CATALOG_TTL", "21600"))  # 6h

# Server
API_HOST = "0.0.0.0"
API_PORT = int(os.environ.get("API_PORT", "8000"))

_cors_env = os.environ.get("CORS_ORIGINS")
CORS_ORIGINS: list[str] = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else ["http://localhost:5173", "http://127.0.0.1:5173"]
)

# Database
DATABASE_PATH = BASE_DIR / "data" / "sessions.db"

# Session
MAX_CONTEXT_MESSAGES = int(os.environ.get("MAX_CONTEXT_MESSAGES", "10"))

# Subscription
SUBSCRIPTION_DB_PATH = Path(
    os.environ.get("SUBSCRIPTION_DB_PATH", str(BASE_DIR / "backend" / "data" / "subscriptions.db"))
)
SUBSCRIPTION_API_KEY = os.environ.get("SUBSCRIPTION_API_KEY", "")
SUBSCRIPTION_BASE_URL = os.environ.get("SUBSCRIPTION_BASE_URL", "https://api.deepseek.com")
SUBSCRIPTION_MODEL = os.environ.get("SUBSCRIPTION_MODEL", "deepseek-chat")
SUBSCRIPTION_ENABLED = bool(SUBSCRIPTION_API_KEY)

# WXpay (WeChat Pay bridge) — see INTEGRATION.md
WXPAY_BASE_URL = os.environ.get("WXPAY_BASE_URL", "http://127.0.0.1:8000")
WXPAY_API_KEY = os.environ.get("WXPAY_API_KEY", "")
WXPAY_WEBHOOK_SECRET = os.environ.get("WXPAY_WEBHOOK_SECRET", "")
# Public webhook URL the WXpay process POSTs to. Empty disables webhook (poll-only).
WXPAY_CALLBACK_URL = os.environ.get("WXPAY_CALLBACK_URL", "")
WXPAY_ORDER_TTL_SECONDS = int(os.environ.get("WXPAY_ORDER_TTL_SECONDS", "1800"))
WXPAY_ENABLED = bool(WXPAY_API_KEY)

# Build Mode
BUILD_PROJECTS_DIR = BASE_DIR / "backend" / "data" / "build_projects"
BUILD_MODEL = os.environ.get("BUILD_MODEL", "deepseek-reasoner")
BUILD_CHAT_MODEL = os.environ.get("BUILD_CHAT_MODEL", "deepseek-chat")
BUILD_AGENT_MAX_TOKENS = int(os.environ.get("BUILD_AGENT_MAX_TOKENS", "16384"))
BUILD_SEARCH_MAX_RESULTS = int(os.environ.get("BUILD_SEARCH_MAX_RESULTS", "5"))
BUILD_SESSION_TTL = int(os.environ.get("BUILD_SESSION_TTL", "3600"))
BUILD_MAX_REVIEW_RETRIES = int(os.environ.get("BUILD_MAX_REVIEW_RETRIES", "2"))

# Auth
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "true").lower() == "true"
AUTH_SESSION_TTL_DAYS = int(os.environ.get("AUTH_SESSION_TTL_DAYS", "30"))
AUTH_MAX_DEVICES = int(os.environ.get("AUTH_MAX_DEVICES", "3"))
AUTH_INACTIVE_DELETE_DAYS = int(os.environ.get("AUTH_INACTIVE_DELETE_DAYS", "60"))

# SSO — BraynLabs as identity provider
BRAYNLABS_URL = os.environ.get("BRAYNLABS_URL", "https://braynlabs.cn")
SSO_CLIENT_ID = os.environ.get("SSO_CLIENT_ID", "commandcraft")
SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", "")

# Internal admin — called by BraynLabs admin panel (loopback, shared-secret).
# When unset, /api/internal/admin/* returns 503.
INTERNAL_ADMIN_TOKEN = os.environ.get("INTERNAL_ADMIN_TOKEN", "")

# Wiki Knowledge Base
WIKI_DIR = KNOWLEDGE_BASE_BEDROCK_DIR / "wiki"
WIKI_DB_PATH = WIKI_DIR / "wiki.db"
WIKI_ARTICLES_DIR = WIKI_DIR / "articles"
WIKI_SEARCH_MAX_RESULTS = int(os.environ.get("WIKI_SEARCH_MAX_RESULTS", "3"))
