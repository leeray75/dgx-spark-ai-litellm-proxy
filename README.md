# AI LLM Proxy - Qwen3.8-Flash-Next-FP4-Local, Qwen3.8-27B-NVFP4, Qwen3.6-35B-A3B-NVFP4, Qwen3-Coder-Next-FP8 & Nemotron-3-Super-120B

An OpenAI-compatible LLM proxy running on **NVIDIA DGX Spark (Blackwell GB10)** with Langfuse v3 observability.

> **Hardware:** NVIDIA DGX Spark workstation with GB10 Superchip (128 GB unified memory) and NVIDIA Blackwell architecture GPUs.

## Features

- **Multi-Model Support**: Switch between Qwen3.8-Flash-Next-FP4-Local (default since 2026-10-22, vision-capable), Qwen3.8-27B-NVFP4 (rollback), Qwen3.6-35B-A3B-NVFP4 (retired rollback — see CHANGELOG.md), Qwen3-Coder-Next-FP8 (80B), and Nemotron-3-Super-120B (NVFP4)
- **Text Embedding**: `nemotron-3-embed-1b-nvfp4` (NVFP4-quantized) for text embeddings (2048-dim)
- **OpenAI-Compatible API**: Drop-in replacement for OpenAI API calls
- **Langfuse v3 Observability**: Full traceability, cost tracking, and analytics
- **vLLM Inference**: High-performance GPU inference with FlashAttention-3 support
- **LiteLLM Proxy**: Virtual key management, spend tracking, rate limiting
- **agentgateway (trial)**: Second OpenAI/Anthropic-compatible gateway on port 4100 alongside LiteLLM, same key, traces to Langfuse over OTLP

## Architecture

```
               ┌────────────────────────────────────────────────┐
               │  Clients: Claude Code, Goose, Cline, SDKs, ... │
               └───────┬────────────────────────────────┬───────┘
                       │ OpenAI + Anthropic APIs        │
          ┌────────────▼─────────────┐   ┌──────────────▼───────────┐
          │ LiteLLM Proxy      :4000 │   │ agentgateway (trial)     │
          │ virtual keys, spend,     │   │ API :4100  UI :4101      │
          │ routing, Redis cache     │   │ same key as LiteLLM      │
          └─┬──────────┬─────────────┘   └─────────────┬──────────┬─┘
            │          │                               │          │
            │          └───────────────┬───────────────┘          │
            │                          │ inference                │
            │       ┌──────────────────┼──────────────────┐       │
            │       │                  │                  │       │
            │ ┌─────▼──────────┐ ┌─────▼──────────┐ ┌─────▼─────┐ │
            │ │ Qwen3.8-Flash- │ │ Embedding      │ │ Anthropic │ │
            │ │ Next engine    │ │ engine  :8302  │ │ API       │ │
            │ │ :8301 (b12x)   │ │ Nemotron-3-    │ │ claude-*  │ │
            │ │                │ │ Embed-1B       │ │ (cloud)   │ │
            │ └────────────────┘ └────────────────┘ └───────────┘ │
            │ traces (Langfuse SDK)             traces (OTLP)     │
 ┌──────────▼─────────────────────────────────────────────────────▼──────────┐
 │ Langfuse v3                                                               │
 │  Web UI + ingestion :3000 ──► Redis queue ──► Worker :3030 ──► ClickHouse │
 │                                                                 + MinIO   │
 │                                                                           │
 │  PostgreSQL :5432     ClickHouse :8123     Redis :6379      MinIO :9090   │
 │  langfuse + litellm   traces, scores       queue + LiteLLM  event payloads│
 │  databases                                 prompt cache     console :9091 │
 └───────────────────────────────────────────────────────────────────────────┘
```

This is the default stack (`docker-compose.qwen3.8-flash-next.yml`, started with `./scripts/flash-next-compose.sh up -d`).
Only one chat engine runs at a time. The other compose files swap the engine box and leave the rest in place:

| Stack | Chat engine | Port |
|---|---|---|
| `docker-compose.qwen3.8.yml` (rollback) | Qwen3.8-27B-NVFP4 (+ embedding engine, `local-image-gen-mcp` behind agentgateway's `/mcp/image-gen`) | 8301 |
| `docker-compose.qwen3.6.yml` (retired rollback) | Qwen3.6-35B-A3B-NVFP4 (+ embedding engine) | 8301 |
| `docker-compose.yml` | Qwen3-Coder-Next-FP8 | 8300 |
| `docker-compose.nemotron.yml` | Nemotron-3-Super-120B (+ Qdrant 6333/6334) | 8200 |

Under the 27B and qwen3.6 stacks agentgateway runs from the standalone `docker-compose.agentgateway.yml`.

## Prerequisites

- Docker Desktop or Docker Engine (v24+)
- Docker Compose (v2.20+)
- NVIDIA Container Toolkit (for GPU support)
- Minimum 128GB RAM recommended
- HuggingFace token with read access to models

## Quick Start

1. **Clone or copy this repository**

2. **Create .env file**:
   ```bash
   cp .env.sample .env
   # Edit .env and fill in all required values
   ```

3. **Start the stack**:
   ```bash
   # Start with Qwen3.8-Flash-Next-FP4-Local (default) — via the wrapper, which derives
   # AGW_LANGFUSE_BASIC_AUTH from .env (see docs/setup.md for the preconditions)
   ./scripts/flash-next-compose.sh up -d

   # Or start with Qwen3.8-27B-NVFP4 (rollback; restore the ROLLBACK blocks in
   # litellm-config.yaml and agentgateway/config.yaml first)
   docker compose -f docker-compose.qwen3.8.yml up -d

   # Or start with Qwen3.6-35B-A3B-NVFP4 (retired rollback)
   docker compose -f docker-compose.qwen3.6.yml up -d

   # Or start with Qwen3-Coder-Next-FP8
   docker compose up -d

   # Or start with Nemotron-3-Super-120B
   docker compose -f docker-compose.nemotron.yml up -d
   ```

4. **Verify services**:
   ```bash
   docker compose ps
   ```

## Scripts

### model-switch.sh

Switch between models:

```bash
# Switch to Qwen3.8-Flash-Next-FP4-Local (DEFAULT; aliases: qwen3.8-flash, flash-next)
./scripts/model-switch.sh flash

# Switch to Qwen3.8-27B-NVFP4 (ROLLBACK — prints a warning about the ROLLBACK config blocks)
./scripts/model-switch.sh qwen3.8

# Switch to Qwen3.6-35B-A3B-NVFP4 (retired rollback)
./scripts/model-switch.sh qwen3.6

# Switch to Qwen3-Coder-Next-FP8
./scripts/model-switch.sh qwen

# Switch to Nemotron-3-Super-120B
./scripts/model-switch.sh nemotron

# Check current status
./scripts/model-switch.sh status

# Preview any switch without executing it (prints every mutating command)
DRY_RUN=1 ./scripts/model-switch.sh flash
```

### restart.sh

Full stack restart with system cache clearing (for NVIDIA DGX Spark Blackwell GB10):

```bash
# Restart with Qwen3.8-Flash-Next-FP4-Local (default)
./scripts/restart.sh

# Restart with Qwen3.8-27B-NVFP4 (rollback)
./scripts/restart.sh qwen3.8

# Restart with Qwen3.6-35B-A3B-NVFP4 (retired rollback)
./scripts/restart.sh qwen3.6

# Restart with Qwen3-Coder-Next-FP8
./scripts/restart.sh qwen

# Restart with Nemotron-3-Super-120B
./scripts/restart.sh nemotron

# Check container status
./scripts/restart.sh status

# Stop all containers
./scripts/restart.sh clean
```

> **Note:** The restart script includes the "Ritual" — clearing system caches via `sudo sync; echo 3 > /proc/sys/vm/drop_caches` — to ensure optimal performance on DGX Spark. For Flash-Next it is required, not just nice to have: vLLM refuses to start unless `MemFree` is about 105 GiB or more (see `docs/troubleshooting.md`). `model-switch.sh flash` has no cache drop and aborts with the exact command if `MemFree` is too low. `local-image-gen-mcp` stays off while Flash-Next runs.

### eval-agentic-tasks.py

Agentic coding evaluation of the served model through agentgateway: small repository tasks, harness-style tools (no shell), sandboxed test runs and hidden-test grading.

```bash
python3 scripts/eval-agentic-tasks.py --self-test     # check the tasks (no model calls)
python3 scripts/eval-agentic-tasks.py --repeats 1     # one attempt per task (~30-45 min)
```

`scripts/eval-hard-problems.py` is the older single-prompt variant (no tools).

## Access Points

| Service | URL | Port |
|---------|-----|------|
| Langfuse UI | http://localhost:3000 | 3000 |
| LiteLLM API | http://localhost:4000/v1 | 4000 |
| LiteLLM UI | http://localhost:4000/ui | 4000 |
| Qwen3.8-Flash-Next Engine (default) / Qwen3.8-27B / Qwen3.6 (rollbacks) | http://localhost:8301/v1 | 8301 |
| agentgateway (trial; part of the Flash-Next stack) | http://localhost:4100/v1 | 4100 |
| Embedding Engine | http://localhost:8302/v1 | 8302 |
| Qwen3-Coder Engine | http://localhost:8300/v1 | 8300 |
| Nemotron Engine | http://localhost:8200/v1 | 8200 |
| MinIO Console | http://localhost:9091 | 9091 |

## Using the API

### OpenAI Compatible

```bash
# Qwen3.8-Flash-Next-FP4-Local (default)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.8-flash-next",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Qwen3.6-35B-A3B-NVFP4 (retired rollback)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.6-35b-a3b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Qwen3-Coder-Next-FP8
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3-coder-next",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Nemotron-3-Super-120B
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "nemotron-super",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'
```

### Embedding API

```bash
# Text embedding — inputs must be prefixed with "query:" or "passage:"
curl http://localhost:4000/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "nemotron-3-embed-1b-nvfp4", "input": "query: Hello"}'
```

## Stopping Services

```bash
# Stop all containers
docker compose down

# Stop and remove volumes (deletes all data!)
docker compose down -v
```

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues.

## Documentation

- [Architecture](docs/architecture.md)
- [Setup Guide](docs/setup.md)
- [Models](docs/models.md)
- [Troubleshooting](docs/troubleshooting.md)
- [AI Agent Configuration](docs/agents.md)

## AI Agents & Clients

The LiteLLM proxy provides an OpenAI-compatible API and works with many AI agents and tools:

| Agent/Tool | API Model | Port | Purpose |
|------------|-----------|------|---------|
| Cline Code | `qwen3.8-flash-next` (default), `qwen3.6-35b-a3b` (retired rollback), `qwen3-coder-next`, `nemotron-super` | 4000 | VS Code AI assistant |
| Claude Code | `qwen3.8-flash-next` (default), `qwen3.6-35b-a3b` (retired rollback), `qwen3-coder-next`, `nemotron-super` | 4000 | CLI AI coding assistant |
| Cursor IDE | `qwen3.8-flash-next` (default), `qwen3.6-35b-a3b` (retired rollback), `qwen3-coder-next`, `nemotron-super` | 4000 | AI-powered code editor |
| Continue | `qwen3.8-flash-next` (default), `qwen3.6-35b-a3b` (retired rollback), `qwen3-coder-next`, `nemotron-super` | 4000 | Open-source AI assistant |
| Codeium | `qwen3.8-flash-next` (default), `qwen3.6-35b-a3b` (retired rollback), `qwen3-coder-next`, `nemotron-super` | 4000 | AI coding assistant |
| OpenWebUI | Direct endpoint | 3000 | Web-based LLM interface |
| OpenAI SDK | `qwen3.8-flash-next` (default), `qwen3.6-35b-a3b` (retired rollback), `qwen3-coder-next`, `nemotron-super` | 4000 | Python/JavaScript clients |

**Full documentation:** See [AI Agent Configuration](docs/agents.md) for detailed setup guides.

> **Claude Code:** its `/model` picker only lists IDs starting with `claude`/`anthropic`, so pick `claude-qwen3.8-flash-next` there (same engine).
>
> **Note:** All agents support the same backend models — Qwen3.8-Flash-Next-FP4-Local (default; the `qwen3.8-27b` aliases were removed 2026-10-22), Qwen3.6-35B-A3B-NVFP4 (retired rollback — see CHANGELOG.md), Qwen3-Coder-Next-FP8, and Nemotron-3-Super-120B. Only one chat engine runs at a time.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

MIT