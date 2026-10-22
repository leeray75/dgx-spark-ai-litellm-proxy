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
│          │  Langfuse Worker  │   │  Flash-Next/27B/3.6    │               │
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
| Qwen3.8-Flash-Next Engine (default since 2026-10-22) | `eugr/spark-vllm-b12x@sha256:03a95654…` (pinned) | 8301 | Qwen3.8-Flash-Next-FP4-Local | NVFP4 `csf` (modelopt_mixed) |
| Qwen3.8-27B Engine (rollback) | `vllm/vllm-openai:nightly` | 8301 | Qwen3.8-27B-NVFP4 | NVFP4+FP8 (compressed-tensors) |
| Qwen3.6 Engine (retired rollback) | `vllm/vllm-openai:nightly` | 8301 | Qwen3.6-35B-A3B-NVFP4 | NVFP4 (ModelOpt) |
| Embedding Engine | `vllm/vllm-openai:nightly` | 8302 | nemotron-3-embed-1b-nvfp4 | NVFP4 |
| Qwen3-Coder Engine | `vllm/vllm-openai:v0.19.1-cu130` | 8300 | Qwen3-Coder-Next-FP8 | FP8 |
| Nemotron Engine | `vllm/vllm-openai:v0.18.1-cu130` | 8200 | Nemotron-3-Super-120B | NVFP4 |

> **Note:** Each compose stack pins a different vLLM image — do not swap these. Nemotron requires `v0.18.1` (not `v0.19.1`), and Qwen3-Coder uses `v0.19.1` for GDN/Mamba stability. The Qwen3.8-27B and Qwen3.6 stacks both use `nightly` for FlashInfer persistent cache support. The Flash-Next stack (default) needs the community `eugr/spark-vllm-b12x` image (upstream vLLM cannot load its NVFP4 `csf` scale encoding), pinned by digest; its embedding engine still uses `nightly`. All three chat engines share port 8301 — only one runs at a time, same as every other pair of chat engines here. The Flash-Next compose file also contains its own agentgateway (ports 4100/4101); it is run through `scripts/flash-next-compose.sh`, which derives `AGW_LANGFUSE_BASIC_AUTH` from `.env`.

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
| 8301 | Qwen3.8-Flash-Next Engine (default) / Qwen3.8-27B (rollback) / Qwen3.6 (retired rollback) | External | Direct vLLM access — mutually exclusive, whichever stack is running |
| 4100 | agentgateway | External | OpenAI/Anthropic-compatible API + MCP (`/mcp/image-gen`), same key as LiteLLM; part of the Flash-Next stack (UI on 127.0.0.1:4101) |
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

### Qwen3.8-Flash-Next-FP4-Local (DEFAULT since 2026-10-22)

- **Size**: 125B total / ~6B active parameters (MoE: 512 experts, 10 routed + 1 shared), plus a 51B n-gram (PLE) embedding table that stays on NVMe (`VLLM_PLE_TABLE_MEMORY=disk`) and a 4B MTP head
- **Architecture**: 48 layers (36 Gated DeltaNet + 12 Qwen Sparse Attention), vision encoder included
- **Serving**: community `eugr/spark-vllm-b12x` image with b12x kernels, NVIDIA's DGX Spark recipe, `--gpu-memory-utilization 0.80`, FP8 KV cache, MTP with 4 speculative tokens, `--tool-call-parser qwen3_xml`, `--reasoning-parser qwen3`
- **Memory**: model loading 70.32 GiB, KV cache 28.03 GiB = 1,491,188 tokens (5.69x concurrency at 262,144 tokens); `local-image-gen-mcp` must stay stopped; startup needs `MemFree` ≥ ~105 GiB
- **Performance**: ~38 tok/s median in the 2026-10-22 tests; first boot ≤ 18 m 39 s
- **Routing**: LiteLLM aliases `qwen3.8-flash-next`, `qwen3.8-flash-next-nothink`, `claude-qwen3.8-flash-next` (Claude Code `/model` discovery); `default_fallbacks: ["qwen3.8-flash-next"]`; agentgateway provider `vllm-qwen38-flash`
- **Details**: `docker-compose.qwen3.8-flash-next.yml` header and `docs/specs/qwen38-flash-next-stack/research.md`

### Qwen3.8-27B-NVFP4 (ROLLBACK since 2026-10-22 — see throughput/accuracy note in Model Comparison below)

- **Size**: 27B total parameters, dense (not MoE — all params active)
- **Architecture**: Hybrid Gated-DeltaNet + Gated-Attention, with vision encoder
- **Quantization**: compressed-tensors-shaped NVFP4 (MLP + `lm_head`) / FP8 (attention) mixed scheme, auto-detected
  (no `--quantization` flag needed — despite the model card's "quantized with Model Optimizer" framing, the
  on-disk schema is compressed-tensors' `config_groups`/`targets`, not ModelOpt's own schema)
- **Context**: 262K tokens native
- **GPU Memory**: KV cache 1,309,255 tokens / 4.99x concurrency at `--gpu-memory-utilization 0.6` (post
  simplification-pass, 2026-09-10)
- **Vision Support**: Yes (`--mm-encoder-tp-mode data`)
- **Reasoning**: Native thinking tokens with `--reasoning-parser qwen3`; `enable_thinking` is on by default
  (never explicitly set) — a small `max_tokens` can return an empty response, all tokens spent on reasoning
- **Special**: `--tool-call-parser qwen3_coder` (matches the official model card recipe — **not** `qwen3_xml`,
  which was only ever a carried-over guess during an earlier, now-retired checkpoint), `--trust-remote-code`,
  `--mamba-ssm-cache-dtype float32`, `--speculative-config` (MTP). No `--load-format fastsafetensors`,
  `--attention-backend`, `--async-scheduling`, `--enable-prefix-caching`, or `--override-generation-config` /
  `--default-chat-template-kwargs` — dropped 2026-09-09/10 as unneeded cruft (the sampling-related pair was
  confirmed to be a no-op: the checkpoint's own `generation_config.json` already ships the same values). See
  `docker-compose.qwen3.8.yml`'s CHECKPOINT SWAP/RESULT/SIMPLIFICATION PASS notes for full detail.

### Qwen3.6-35B-A3B-NVFP4 (ROLLBACK)

- **Size**: 35B total parameters, 3B active (MoE)
- **Architecture**: Hybrid Attention + MoE, with vision encoder
- **Quantization**: NVFP4 (NVIDIA ModelOpt)
- **Context**: 262K tokens (131K default in LiteLLM)
- **GPU Memory**: ~26GB weights (plus KV cache)
- **Vision Support**: Yes (`--mm-encoder-tp-mode data`)
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
| `vllm-qwen38-compile-cache` | torch.compile + FlashInfer autotune configs (qwen3.8 27B rollback engine) |
| `vllm-qwen38-flashinfer-cache` | FlashInfer JIT kernel workspace (qwen3.8 27B rollback engine) |
| `vllm-qwen38-triton-cache` | Triton kernel cache (qwen3.8 27B rollback engine) |
| `vllm-qwen38-flash-compile-cache` / `-flashinfer-cache` / `-triton-cache` / `-b12x-cache` | torch.compile AOT artifacts, FlashInfer, Triton and b12x caches (Flash-Next default engine) |
| `vllm-embed-compile-cache` | Embedding engine compile cache (shared by both qwen3.8 and qwen3.6 stacks) |