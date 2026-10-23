#!/usr/bin/env bash
# Run docker compose on the Qwen3.8-Flash-Next stack with AGW_LANGFUSE_BASIC_AUTH
# derived from .env (the compose file's :? guard requires it for every command,
# including config/ps/logs/down).
#   ./scripts/flash-next-compose.sh up -d | ps | logs -f qwen3-8-flash-next-fp4-engine | down
# Secrets are never echoed. Refuses to run when the Langfuse keys are empty,
# because the one-liner would then yield "Og==" (base64 of ":") and silently
# break agentgateway's Langfuse auth.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${LANGFUSE_PUBLIC_KEY:-}" || -z "${LANGFUSE_SECRET_KEY:-}" ]]; then
    echo "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY empty in .env - refusing (agentgateway traces would fail auth)" >&2
    exit 1
fi

export AGW_LANGFUSE_BASIC_AUTH
AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)

mkdir -p agentgateway/data
exec docker compose -f docker-compose.qwen3.8-flash-next.yml "$@"
