# Architecture

## System Overview

This project implements an OpenAI-compatible LLM inference infrastructure with Langfuse v3 observability,
specifically designed for the **NVIDIA DGX Spark (Blackwell GB10)** workstation.

> **Hardware:** NVIDIA DGX Spark workstation with GB10 Superchip (128 GB unified memory)
> based on NVIDIA Blackwell architecture, optimized for large language model inference.

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           External Services                                │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │   Clients  │  │   SDKs       │  │   Scripts        │  │   Other      │ │
│  │  (API)     │  │  (Langfuse)  │  │  (Monitoring)    │  │   Services   │ │
│  └──────┬─────┘  └──────┬───────┘  └────────┬─────────┘  └──────┬───────┘ │
│         │                │                   │                   │         │
│         └────────────────┼───────────────────┼───────────────────┘         │
│                          │                   │                             │
│                    ┌─────▼─────┐    ┌───────▼────────┐                    │
│                    │  Langfuse │    │   LiteLLM      │                    │
│                    │   Web UI  │    │    Proxy       │                    │
│                    │  (3000)   │    │   (4000)       │                    │
│                    └─────┬─────┘    └───────┬────────┘                    │
│                          │                   │                             │
│                          └───────────────────┼─────────────────────────────┘
│                                              │
│                    ┌─────────────────────────┼─────────────────────────────┐
│                    │                         │                             │
│          ┌─────────▼─────────┐   ┌───────────▼────────────┐               │
│          │  Langfuse Worker  │   │  Qwen3.8/3.6 Engine    │               │
│          │  (Async Events)   │   │  (vLLM, 8301 —         │               │
│          │                   │   │   mutually exclusive)  │               │
│          └─────────┬─────────┘   └───────────┬────────────┘               │
│                    │                         │                             │
│          ┌─────────▼─────────┐   ┌───────────▼────────────┐               │
│          │  Langfuse Web     │   │   Embedding Engine     │               │
│          │  (Observability)  │   │   (vLLM, 8302)         │               │
│          └─────────┬─────────┘   └────────────────────────┘               │
│                    │             ┌────────────────────────┐               │
│          ┌─────────▼─────────┐   │   Qwen3-Coder Engine   │               │
│          │  PostgreSQL       │   │   (vLLM, 8300)         │               │
│          │  (Langfuse +      │   └────────────────────────┘               │
│          │   LiteLLM DBs)    │                                            │
│          └─────────┬─────────┘                                            │
│                    │                                                      │
│          ┌─────────▼─────────┐   ┌────────────────────────┐               │
│          │  ClickHouse       │   │   Nemotron Engine      │               │
│          │  (Analytics)      │   │   (vLLM, 8200)         │               │
│          └─────────┬─────────┘   └────────────────────────┘               │
│                    │                                                      │
│          ┌─────────▼─────────┐   ┌────────────────────────┐               │
│          │  Redis            │   │   MinIO                │               │
│          │  (Event Queue)    │   │   (Blob Storage)       │               │
│          └───────────────────┘   └────────────────────────┘               │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### Langfuse Services (Observability)

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| Langfuse Web | `langfuse/langfuse:3` | 3000 | Web UI + public ingestion API |
| Langfuse Worker | `langfuse/langfuse-worker:3` | 3030 | Async event processor |
| PostgreSQL | `postgres:16-alpine` | 5432 | Auth, projects, API keys, config |
| ClickHouse | `clickhouse/clickhouse-server` | 8123 | Traces, observations, scores |
| Redis | `redis:7-alpine` | 6379 | Event queue + cache |
| MinIO | `minio/minio` | 9090 | S3-compatible blob storage |

### Inference Engines

| Service | Image | Port | Model | Quantization |
|---------|-------|------|-------|--------------|
| Qwen3.8 Engine (experimental) | `vllm/vllm-openai:nightly` | 8301 | Qwen3.8-27B-NVFP4 | NVFP4+FP8 (compressed-tensors) |
| Qwen3.6 Engine (default) | `vllm/vllm-openai:nightly` | 8301 | Qwen3.6-35B-A3B-NVFP4 | NVFP4 (ModelOpt) |
| Embedding Engine | `vllm/vllm-openai:nightly` | 8302 | nemotron-3-embed-1b-nvfp4 | NVFP4 |
| Qwen3-Coder Engine | `vllm/vllm-openai:v0.19.1-cu130` | 8300 | Qwen3-Coder-Next-FP8 | FP8 |
| Nemotron Engine | `vllm/vllm-openai:v0.18.1-cu130` | 8200 | Nemotron-3-Super-120B | NVFP4 |

> **Note:** Each compose stack pins a different vLLM image — do not swap these. Nemotron requires `v0.18.1` (not `v0.19.1`), and Qwen3-Coder uses `v0.19.1` for GDN/Mamba stability. The Qwen3.8 and Qwen3.6 stacks both use `nightly` for FlashInfer persistent cache support and share port 8301 — only one runs at a time, same as every other pair of chat engines here.

### Proxy Layer

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| LiteLLM | `ghcr.io/berriai/litellm:main-latest` | 4000 | OpenAI-compatible API + routing |

## Network Architecture

### Bridge Network

All services connect via a Docker bridge network called `ai-bridge`:

- Services can communicate using their service names as hostnames
- External services only expose necessary ports
- Internal services (PostgreSQL, ClickHouse native, Redis) bind to 127.0.0.1

### Port Assignment

| Port | Service | Accessibility | Purpose |
|------|---------|---------------|---------|
| 3000 | Langfuse Web | External | Web UI, API |
| 4000 | LiteLLM | External | OpenAI-compatible API |
| 8301 | Qwen3.6 Engine (default) / Qwen3.8 Engine (experimental) | External | Direct vLLM access — mutually exclusive, whichever stack is running |
| 8302 | Embedding Engine | External | Direct vLLM access (embeddings) |
| 8300 | Qwen3-Coder Engine | External | Direct vLLM access (Qwen3-Coder) |
| 8200 | Nemotron Engine | External | Direct vLLM access |
| 9090 | MinIO S3 API | External | Blob storage API |
| 9091 | MinIO Console | External | MinIO admin UI |
| 5432 | PostgreSQL | Local only | Database access |
| 8123 | ClickHouse HTTP | Local only | ClickHouse HTTP API |
| 9000 | ClickHouse Native | Local only | ClickHouse native protocol |
| 6379 | Redis | Local only | Redis access |
| 3030 | Langfuse Worker | Local only | Worker health checks |

## Data Flow

1. **Client Request** → LiteLLM Proxy (4000)
2. **LiteLLM** → Routes to appropriate vLLM engine (8301, 8300, or 8200)
3. **vLLM** → Generates response with model
4. **Response** → Back to client
5. **Langfuse OTEL** → Captures trace data from LiteLLM
6. **Events** → Queued in Redis, processed by Langfuse Worker
7. **Data** → Stored in ClickHouse (traces) and MinIO (event payloads)

## Model Details

### Qwen3.8-27B-NVFP4 (EXPERIMENTAL — see throughput note in Model Comparison below)

- **Size**: 27B total parameters, dense (not MoE — all params active)
- **Architecture**: Hybrid Gated-DeltaNet + Gated-Attention, with vision encoder
- **Quantization**: compressed-tensors NVFP4 + FP8 (mixed)
- **Context**: 262K tokens native
- **GPU Memory**: ~22.13GB weights confirmed via boot log (plus KV cache; `--gpu-memory-utilization 0.6`)
- **Vision Support**: Yes
- **Reasoning**: Native thinking tokens with `--reasoning-parser qwen3`
- **Special**: `--tool-call-parser qwen3_xml` (carried over from qwen3.6 by analogy, unverified for this
  model), `--load-format fastsafetensors`, no `--quantization`/`--moe-backend` flags needed (dense,
  auto-detected quantization). See `docker-compose.qwen3.8.yml`'s PROVENANCE header for full detail.

### Qwen3.6-35B-A3B-NVFP4 (DEFAULT)

- **Size**: 35B total parameters, 3B active (MoE)
- **Architecture**: Hybrid Attention + MoE
- **Quantization**: NVFP4 (NVIDIA ModelOpt)
- **Context**: 262K tokens (131K default in LiteLLM)
- **GPU Memory**: ~26GB weights (plus KV cache)
- **Vision Support**: No (text-only)
- **Reasoning**: Native thinking tokens with `--reasoning-parser qwen3`
- **Special**: `--tool-call-parser qwen3_xml` (matches the official vLLM recipe, confirmed 2026-09-02), `--load-format fastsafetensors`, `--default-chat-template-kwargs '{"enable_thinking":false}'` (2026-09-02 — disables the reasoning pass by default so it can't consume the output token budget on long, multi-requirement tickets)

### nemotron-3-embed-1b-nvfp4 (Embedding)

- **Size**: 1.14B parameters (pruned Ministral-3-3B-based encoder)
- **Output**: 2048-dimensional vectors
- **Context**: 4096 tokens (configured; model supports up to 32768)
- **GPU Memory**: ~1-2GB (NVFP4 quantized)
- **Vision Support**: No (text-only; requires manual `query:`/`passage:` input prefix)
- **Concurrent**: Runs alongside chat engine on same GPU

### Qwen3-Coder-Next-FP8

- **Size**: 80B total parameters, 3B active
- **Architecture**: Gated DeltaNet (GDN) + Gated Attention + MoE
- **Quantization**: FP8
- **Context**: 262K tokens
- **GPU Memory**: ~118GB required
- **Special**: 512 experts, 10 active per forward pass

### Nemotron-3-Super-120B-A12B-NVFP4

- **Size**: 120B total parameters, 12B active
- **Architecture**: MoE with 512 experts
- **Quantization**: NVFP4 (NVIDIA 4-bit)
- **Context**: 262K tokens
- **GPU Memory**: ~80GB required
- **Special**: Requires reasoning parser plugin

## Docker Volumes

| Volume | Purpose |
|--------|---------|
| `langfuse-postgres-data` | PostgreSQL database files |
| `langfuse-clickhouse-data` | ClickHouse data and metadata |
| `langfuse-clickhouse-logs` | ClickHouse server logs |
| `langfuse-minio-data` | MinIO object storage |
| `langfuse-redis-data` | Redis RDB/AOF data |
| `vllm-compile-cache` | torch.compile + FlashInfer autotune configs (qwen3.6 rollback engine) |
| `vllm-flashinfer-cache` | FlashInfer JIT kernel workspace (qwen3.6 rollback engine) |
| `vllm-triton-cache` | Triton kernel cache (qwen3.6 rollback engine) |
| `vllm-qwen38-compile-cache` | torch.compile + FlashInfer autotune configs (qwen3.8 default engine) |
| `vllm-qwen38-flashinfer-cache` | FlashInfer JIT kernel workspace (qwen3.8 default engine) |
| `vllm-qwen38-triton-cache` | Triton kernel cache (qwen3.8 default engine) |
| `vllm-embed-compile-cache` | Embedding engine compile cache (shared by both qwen3.8 and qwen3.6 stacks) |