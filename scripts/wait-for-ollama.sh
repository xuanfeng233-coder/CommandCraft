#!/bin/sh
# Wait for Ollama API to be ready and models to be available.
# Usage: ./wait-for-ollama.sh [OLLAMA_BASE_URL]

OLLAMA_URL="${1:-${OLLAMA_BASE_URL:-http://localhost:11434}}"
TIMEOUT=120
INTERVAL=3
ELAPSED=0

echo "[wait-for-ollama] Waiting for Ollama at $OLLAMA_URL ..."

# Phase 1: Wait for API to respond
while [ $ELAPSED -lt $TIMEOUT ]; do
    if curl -sf "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
        echo "[wait-for-ollama] Ollama API is up (${ELAPSED}s)"
        break
    fi
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "[wait-for-ollama] WARNING: Ollama not responding after ${TIMEOUT}s, starting anyway"
    exit 0
fi

# Phase 2: Check that required models are present
MODELS=$(curl -sf "$OLLAMA_URL/api/tags" 2>/dev/null)

check_model() {
    echo "$MODELS" | grep -q "\"$1" && echo "[wait-for-ollama] Model '$1' found" || \
        echo "[wait-for-ollama] WARNING: Model '$1' not found"
}

check_model "qwen3"
check_model "bge-m3"

echo "[wait-for-ollama] Ready, starting backend..."
