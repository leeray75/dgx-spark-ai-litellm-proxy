#!/usr/bin/env bash
# Start the agentgateway trial next to litellm-proxy.
# Derives the Langfuse OTLP Basic auth header from .env's Langfuse keys at
# launch time, so no extra secret has to be stored.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

export AGW_LANGFUSE_BASIC_AUTH
AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)

mkdir -p agentgateway/data
docker compose -f docker-compose.agentgateway.yml up -d "$@"
