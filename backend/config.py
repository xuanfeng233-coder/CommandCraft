"""Application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root (won't override existing env vars)
load_dotenv(BASE_DIR / ".env")
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"

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

# RAG / Vector Search
CHROMADB_DIR = BASE_DIR / "data" / "chromadb"
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "16"))
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.45"))
RAG_TOP_K_COMMANDS = int(os.environ.get("RAG_TOP_K_COMMANDS", "3"))
RAG_TOP_K_IDS = int(os.environ.get("RAG_TOP_K_IDS", "5"))
RAG_TOP_K_INTENTS = int(os.environ.get("RAG_TOP_K_INTENTS", "0"))
RAG_TOP_K_FEW_SHOT = int(os.environ.get("RAG_TOP_K_FEW_SHOT", "1"))

# Common commands — strong cloud LLMs already know these well.
# Only exact-lookup (no vector search) is needed for these commands.
COMMON_COMMANDS: set[str] = {
    "give", "tp", "teleport", "effect", "kill", "summon", "enchant",
    "gamemode", "time", "weather", "xp", "clear", "tag", "msg", "tell",
    "say", "me", "testfor", "scoreboard", "execute", "fill", "setblock",
    "clone", "particle", "playsound", "replaceitem", "tellraw", "titleraw",
    "gamerule", "difficulty", "spawnpoint", "setworldspawn", "kick", "op",
    "deop", "whitelist", "list",
}

# Few-shot examples
FEW_SHOT_DIR = KNOWLEDGE_BASE_DIR / "few_shot"

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
SUBSCRIPTION_DB_PATH = BASE_DIR / "backend" / "data" / "subscriptions.db"
SUBSCRIPTION_API_KEY = os.environ.get("SUBSCRIPTION_API_KEY", "")
SUBSCRIPTION_BASE_URL = os.environ.get("SUBSCRIPTION_BASE_URL", "https://api.deepseek.com")
SUBSCRIPTION_MODEL = os.environ.get("SUBSCRIPTION_MODEL", "deepseek-chat")
SUBSCRIPTION_ENABLED = bool(SUBSCRIPTION_API_KEY)
