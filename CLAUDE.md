# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

An OpenAI-compatible LLM proxy stack running on an **NVIDIA DGX Spark (Blackwell GB10)** workstation with 128GB unified memory. It wraps local vLLM inference engines behind a LiteLLM proxy with full Langfuse v3 observability (tracing, cost tracking, analytics).

The four selectable chat models cannot run simultaneously — only one chat inference engine is active at a time due to GPU memory constraints. The `nemotron-3-embed-1b-nvfp4` embedding engine is small enough (~1.14B params) to run alongside whichever chat engine is active; it's wired into both `docker-compose.qwen3.8.yml` and `docker-compose.qwen3.6.yml`.

`docker-compose.qwen3.6.yml` is kept for rollback only — `docker-compose.qwen3.8.yml` is the default/primary stack (2026-08-23).

## Stack Management

### Starting the stack

```bash
# Default model (Qwen3.8-27B-NVFP4) — recommended
docker compose -f docker-compose.qwen3.8.yml up -d

# Qwen3.6-35B-A3B-NVFP4 (rollback)
docker compose -f docker-compose.qwen3.6.yml up -d

# Qwen3-Coder-Next-FP8 (80B MoE, coding-focused)
docker compose up -d

# Nemotron-3-Super-120B (general reasoning)
docker compose -f docker-compose.nemotron.yml up -d
```

### Full restart with cache clearing (the "Ritual")

```bash
./scripts/restart.sh              # restarts Qwen3.8 (default)
./scripts/restart.sh qwen3.8      # Qwen3.8-27B-NVFP4
./scripts/restart.sh qwen3.6      # Qwen3.6-35B-A3B-NVFP4 (rollback)
./scripts/restart.sh qwen         # Qwen3-Coder-Next-FP8
./scripts/restart.sh nemotron     # Nemotron-3-Super-120B
./scripts/restart.sh status       # show container health
./scripts/restart.sh clean        # stop all containers
```

The restart script drops system caches (`sync; echo 3 > /proc/sys/vm/drop_caches`) to free unified memory before starting a new engine. This requires `sudo`.

### Switching models

```bash
./scripts/model-switch.sh qwen3.8   # switch without full restart (default)
./scripts/model-switch.sh qwen3.6   # rollback
./scripts/model-switch.sh qwen
./scripts/model-switch.sh nemotron
./scripts/model-switch.sh status
```

**Note:** `model-switch.sh` skips the system cache drop; use `restart.sh` when memory pressure is suspected.

### Checking status

```bash
docker compose ps
docker compose logs -f <service>   # e.g. litellm, qwen3-6-35b-nvfp4-engine
```

## Configuration Files

| File | Purpose |
|------|---------|
| `litellm-config.yaml` | LiteLLM model routing, Redis cache, Langfuse OTEL callbacks |
| `docker-compose.yml` | Qwen3-Coder-Next-FP8 stack |
| `docker-compose.qwen3.8.yml` | Qwen3.8-27B-NVFP4 stack (default) |
| `docker-compose.qwen3.6.yml` | Qwen3.6-35B-A3B-NVFP4 stack (rollback) |
| `docker-compose.nemotron.yml` | Nemotron-3-Super-120B stack |
| `.env` | All secrets and credentials (copy from `.env.sample`) |
| `clickhouse-config.xml` | ClickHouse memory cap and server settings |
| `postgres-init/01_create_litellm_db.sql` | Creates the separate `litellm` database on first start |

## Architecture

```
Clients → LiteLLM Proxy (4000) → vLLM Engine (8301/8300/8200)
                ↓
          Langfuse OTEL → Langfuse Worker → ClickHouse + MinIO
                                 ↑
                   Redis (event queue + exact-match prompt cache)
                   PostgreSQL (two isolated DBs: langfuse + litellm)
```

- **LiteLLM** (`litellm-config.yaml`): Routes by model name alias, manages virtual keys and spend tracking via PostgreSQL `litellm` DB, caches exact-match prompts in Redis (1hr TTL).
- **vLLM engines**: Each compose file configures one engine with GPU-memory-tuned parameters. vLLM prefix caching handles partial prompt reuse; LiteLLM Redis cache short-circuits 100%-identical requests before they reach vLLM.
- **`docker-compose.qwen3.8.yml`'s PROVENANCE header** (top of that file) documents exactly which vLLM flags for Qwen3.8-27B-NVFP4 are verified against primary sources vs. carried over by analogy from the qwen3.6 file vs. explicitly unverified — read it before changing that file's flags, and before trusting any web search result about this specific model (some surfaced during initial research looked fabricated/unverifiable and were deliberately not used).
- **Langfuse v3**: Two-container split — `langfuse-web` (UI + ingestion API) and `langfuse-worker` (async writer). Worker reads events from Redis queue and writes to ClickHouse (traces) and MinIO (event payloads).
- **PostgreSQL**: Single shared instance with two isolated databases. `TZ=UTC` is required — non-UTC causes incorrect Langfuse query results.

## Cross-File Dependencies

These are relationships that require reading multiple files to understand and are easy to break silently:

**`litellm-config.yaml` is shared across all three compose stacks.** Every compose file mounts it at `/app/config.yaml`. Changing model aliases or routing there affects whichever stack is currently running.

**Three-way name binding for each model:** The vLLM `--served-model-name` flag sets the model name the engine advertises → `litellm-config.yaml` must reference it as `hosted_vllm/<served-model-name>` → the `api_base` must point to the correct Docker service name. If you add a new engine or rename a model, all three must stay in sync.

**`LANGFUSE_OTEL_HOST: http://langfuse:3000`** uses the container's `container_name: langfuse` (not the service name `langfuse-web`). LiteLLM communicates with Langfuse internally via this name.

**`scripts/super_v3_reasoning_parser.py`** is mounted into the Nemotron container as `/app/super_v3_reasoning_parser.py` and activated via `--reasoning-parser-plugin`. **`scripts/qwen3_reasoning_parser.py`** is vestigial — it is not mounted in any compose file; the built-in `--reasoning-parser qwen3` flag is used instead.

**Nemotron stack (`docker-compose.nemotron.yml`) includes Qdrant** (ports 6333/6334) as an optional vector database — this service is absent from the other two compose files.

## Startup Timing and Cache Behavior (Qwen3.8 / Qwen3.6)

First boot on a nightly image runs a FlashInfer fp8_gemm autotuning phase. On a cache-miss boot this takes ~10-35 minutes; the results persist in the `vllm-qwen38-compile-cache` (or `vllm-compile-cache` for the qwen3.6 rollback stack) volume at `/root/.cache/vllm`. Subsequent boots load the cache and complete in ~5-15 minutes total. This timing is carried over from qwen3.6's measured history — not yet independently confirmed for the qwen3.8 stack.

**Cache invalidation:** Changing `--gpu-memory-utilization`, `--max-num-batched-tokens`, `--max-model-len`, or the image version generates a new cache-key hash and forces a full re-tune on the next boot.

Verify cache behavior in logs:
```bash
docker compose -f docker-compose.qwen3.8.yml logs qwen3-8-27b-nvfp4-engine | grep -i "flashinfer.*cache"
```

If you see the cache load message on second boot, the persistent cache is working. If you see repeated "Tuning fp8_gemm" entries, the running nightly is too old (must be built after 2026-05-31, PR #44071).

## vLLM Image Versions

Each compose file pins a different vLLM image — do not swap these:

| Compose file | vLLM image | Notes |
|---|---|---|
| `docker-compose.qwen3.8.yml` | `vllm/vllm-openai:nightly` (ARM64) | Pulled/verified 2026-08-23 (digest `sha256:95bed119…`, vLLM `0.26.1rc1.dev1102+ge9d1398d9`) — confirmed via live registry introspection to register `Qwen3_5ForConditionalGeneration`, the architecture class this checkpoint's config.json declares |
| `docker-compose.qwen3.6.yml` | `vllm/vllm-openai:nightly` (ARM64) | Must be post-2026-05-31 for persistent FlashInfer autotune cache |
| `docker-compose.yml` | `vllm/vllm-openai:v0.19.1-cu130` | Pinned for GDN/Mamba stability |
| `docker-compose.nemotron.yml` | `vllm/vllm-openai:v0.18.1-cu130` | Nemotron requires v0.18.1, not v0.19.1 |

## Model Names and Aliases

### In LiteLLM (via API on port 4000)

| Alias | Backend | Purpose |
|-------|---------|---------|
| `qwen3.8-27b` | Qwen3.8-27B-NVFP4 (Unsloth) | **Default.** Direct access (262K context), vision-capable |
| `qwen3.6-35b-a3b` | Qwen3.6-35B-A3B-NVFP4 | Rollback alias — only reachable if `docker-compose.qwen3.6.yml` is running |
| `qwen3-coder-next` | Qwen3-Coder-Next-FP8 | 80B MoE coder (262K context) |
| `nemotron-super` | Nemotron-3-Super-120B | General reasoning (262K context) |
| `nemotron-3-embed-1b-nvfp4` | Nemotron-3-Embed-1B-NVFP4 | Text-only embedding, 2048-dim, NVFP4 (`/v1/embeddings`); requires manual `query:`/`passage:` input prefix |

> **Note:** The `anthropic/*` wildcard passthrough (added v1.4.0) routes all Claude model IDs — including future releases and any alias Claude Code/Desktop introduces — directly to Anthropic's real API via the proxy. A `default_fallbacks` entry sends failed requests to the local Qwen3.6 engine. This replaces the older approach of using individual `claude-sonnet-4-6` / `claude-haiku-4-6` proxy aliases (removed in v1.3.0).

## Key vLLM Flags by Model

- **Qwen3.8** (default): `--reasoning-parser qwen3`; `--speculative-config '{"method":"mtp","num_speculative_tokens":2}'` (no `moe_backend` key — this checkpoint is dense, not MoE); `--gpu-memory-utilization 0.4` (conservative carry-over from qwen3.6, not yet re-measured for this smaller/dense checkpoint); `--tool-call-parser qwen3_xml` (carried by analogy from qwen3.6, **unverified** for this model — first thing to check if Cline/Claude Code tool calls fail to parse); no `--quantization` flag (compressed-tensors NVFP4/FP8 auto-detected from checkpoint). See `docker-compose.qwen3.8.yml`'s PROVENANCE header for the full verified-vs-assumed breakdown.
- **Qwen3.6** (rollback): `--reasoning-parser qwen3` required (prevents thinking tokens leaking); `--speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'`; `--gpu-memory-utilization 0.4` (official NVIDIA spec); `--tool-call-parser qwen3_xml` (official NVIDIA spec); `--load-format fastsafetensors`
  - `--max-num-batched-tokens 8192` matches the official DGX Spark spec but reduces Cline large-context ingestion throughput vs. the previous value of `262144`. If Cline latency regresses noticeably under real traffic, raising this back toward `262144` is the first lever to pull.
  - `VLLM_NVFP4_GEMM_BACKEND=marlin` env var (not `--linear-backend marlin` — that flag crashes startup on this model due to FP8-quantized GDN attention projection layers).
- **Qwen3-Coder-Next**: `--mamba-ssm-cache-dtype float32` required for GDN/SSM layer stability; `--max-cudagraph-capture-size 128` prevents GDN Mamba OOM
- **Nemotron**: Uses custom reasoning parser plugin at `scripts/super_v3_reasoning_parser.py`; requires vLLM `v0.18.1` (not `v0.19.1`)

## Memory Budget

All containers share the GB10's 128GB unified memory pool (no separate VRAM). At `--gpu-memory-utilization 0.4`, the vLLM engine reserves ~49GB, leaving ~79GB for the observability stack (Postgres 768M, ClickHouse 3G, Redis 512MB app + 640M container, MinIO 512M, Langfuse web 1.5G, Langfuse worker 1.5G, LiteLLM 1G). This applies to both the qwen3.8 and qwen3.6 stacks, which use the same value; qwen3.8's actual KV cache headroom hasn't been measured yet (see that compose file's PROVENANCE header).

`langfuse-web` and `langfuse-worker` both use `NODE_OPTIONS: --max-old-space-size=1024` to cap V8's heap at 1024MB. Without this explicit cap, V8 ignores the Docker memory cgroup limit and OOMs under real trace-ingestion load — idle `docker stats` readings are not a reliable proxy for load-time memory usage.

## Access Points

| Service | URL |
|---------|-----|
| LiteLLM API | http://localhost:4000/v1 |
| LiteLLM UI | http://localhost:4000/ui |
| Langfuse UI | http://localhost:3000 |
| Qwen3.8 Engine (direct, default) | http://localhost:8301/v1 |
| Qwen3.6 Engine (direct, rollback — same port, mutually exclusive with 3.8) | http://localhost:8301/v1 |
| Embedding Engine (direct, Qwen3.8/3.6 stacks only) | http://localhost:8302/v1 |
| Qwen3-Coder Engine (direct) | http://localhost:8300/v1 |
| Nemotron Engine (direct) | http://localhost:8200/v1 |
| MinIO Console | http://localhost:9091 |

## Environment Setup

```bash
cp .env.sample .env
# Fill in all values — required keys:
# HF_TOKEN, LITELLM_MASTER_KEY, POSTGRES_PASSWORD, CLICKHOUSE_PASSWORD,
# MINIO_ROOT_PASSWORD, REDIS_AUTH, LANGFUSE_ENCRYPTION_KEY,
# LANGFUSE_SALT, NEXTAUTH_SECRET, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
```

`LITELLM_SALT_KEY` encrypts virtual key data at rest — never change it after virtual keys have been created.

## Testing the API

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "Hello"}]}'
```

```bash
curl http://localhost:4000/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "nemotron-3-embed-1b-nvfp4", "input": "query: Hello"}'
```

Engine health check (skip LiteLLM):
```bash
curl http://localhost:8301/health   # Qwen3.8 (default) or Qwen3.6 (rollback) — whichever stack is up
curl http://localhost:8302/health   # Embedding engine
curl http://localhost:8300/health   # Qwen3-Coder
curl http://localhost:8200/health   # Nemotron
```
