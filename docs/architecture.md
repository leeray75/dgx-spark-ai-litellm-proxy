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
│          │  Langfuse Worker  │   │   Qwen3 Engine         │               │
│          │  (Async Events)   │   │   (vLLM, 8301)         │               │
│          └─────────┬─────────┘   └────────────────────────┘               │
│                    │                                                      │
│          ┌─────────▼─────────┐   ┌────────────────────────┐               │
│          │  Langfuse Web     │   │   Qwen3-Coder Engine   │               │
│          │  (Observability)  │   │   (vLLM, 8300)         │               │
│          └─────────┬─────────┘   └────────────────────────┘               │
│                    │             ┌────────────────────────┐               │
│          ┌─────────▼─────────┐   │   Nemotron Engine      │               │
│          │  PostgreSQL       │   │   (vLLM, 8200)         │               │
│          │  (Langfuse +      │   └────────────────────────┘               │
│          │   LiteLLM DBs)    │                                            │
│          └─────────┬─────────┘                                            │
│                    │                                                      │
│          ┌─────────▼─────────┐   ┌────────────────────────┐               │
│          │  ClickHouse       │   │   Qdrant (optional)    │               │
│          │  (Analytics)      │   │   (Vector DB)          │               │
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
| Qwen3 Engine | `vllm/vllm-openai:v0.19.1-cu130` | 8301 | Qwen3.6-27B-FP8 | FP8 |
| Qwen3-Coder Engine | `vllm/vllm-openai:v0.19.1-cu130` | 8300 | Qwen3-Coder-Next-FP8 | FP8 |
| Nemotron Engine | `vllm/vllm-openai:v0.18.1-cu130` | 8200 | Nemotron-3-Super-120B | NVFP4 |

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
| 8301 | Qwen3 Engine | External | Direct vLLM access (Qwen3.6) |
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

### Qwen3.6-27B-FP8 (DEFAULT)

- **Size**: 27B total parameters (dense)
- **Architecture**: Gated DeltaNet (GDN) + Gated Attention
- **Quantization**: FP8
- **Context**: 262K tokens
- **GPU Memory**: ~111GB required
- **Vision Support**: Native multimodal (vision + text)
- **Reasoning**: Native thinking tokens with `--reasoning-parser qwen3`
- **Special**: MTP (Multi-step Predictive Training) support

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
- **Context**: 128K tokens
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
| `qdrant-storage` | Qdrant vector database |