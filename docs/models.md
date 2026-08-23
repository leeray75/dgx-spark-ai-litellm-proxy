# Model Comparison Guide

This guide compares the supported LLMs for the **NVIDIA DGX Spark (Blackwell GB10)** workstation.

## Model Overview

### Qwen3.8-27B-NVFP4 (DEFAULT)

| Attribute | Value |
|-----------|-------|
| **Model Name** | Qwen3.8-27B-NVFP4 |
| **Provider** | Unsloth |
| **Total Parameters** | 27B (dense — not MoE) |
| **Active Parameters** | 27B (all) |
| **Architecture** | Hybrid Gated-DeltaNet + Gated-Attention, with vision encoder |
| **Quantization** | compressed-tensors NVFP4 + FP8 (mixed) |
| **Context Window** | 262K tokens native (extensible to 1M via YaRN, untested here) |
| **VRAM Required** | ~22.13 GiB weights (confirmed via boot log) |
| **Model ID** | `unsloth/Qwen3.8-27B-NVFP4` |
| **vLLM Image** | `vllm/vllm-openai:nightly` |
| **Port** | 8301 |

#### Key Features

- **Vision-capable**: has a vision encoder, unlike qwen3.6's text-only checkpoint
- **Dense architecture**: no MoE routing — simpler kernel selection, no `moe_backend` config needed
- **Native kernels confirmed**: `FlashInferCutlassNvFp4LinearKernel` (NVFP4 GEMM) and
  `CutlassFP8ScaledMMLinearKernel` (FP8 layers), no Marlin fallback needed on GB10/SM121 for this
  quantization scheme (unlike qwen3.6's ModelOpt scheme, which does need Marlin)
- **Native Reasoning**: `--reasoning-parser qwen3`
- **Tool Calling**: `--tool-call-parser qwen3_xml` — **carried over by analogy from qwen3.6, not
  independently verified for this model**; see `docker-compose.qwen3.8.yml`'s PROVENANCE header
- **Speculative Decoding**: MTP support, `num_speculative_tokens=2` (matches Unsloth's own documented example)

#### Use Cases

- AI coding agent (Cline, Claude Code) — primary/default model for this stack
- Vision-assisted coding tasks (screenshots, diagrams)
- Technical documentation
- General-purpose assistant with coding focus

#### Known-unverified items

See `docker-compose.qwen3.8.yml`'s PROVENANCE and CORRECTIONS HISTORY headers for the full list of what's
confirmed vs. assumed. `--gpu-memory-utilization` was corrected from an initial `0.4` (which OOM'd on first
boot) to `0.6` — verified working but not yet a measured optimum.

---

### Qwen3.6-35B-A3B-NVFP4 (ROLLBACK)

| Attribute | Value |
|-----------|-------|
| **Model Name** | Qwen3.6-35B-A3B-NVFP4 |
| **Provider** | NVIDIA |
| **Total Parameters** | 35B |
| **Active Parameters** | 3B (MoE) |
| **Architecture** | Hybrid Attention + MoE |
| **Quantization** | NVFP4 (NVIDIA 4-bit) |
| **Context Window** | 262K tokens (configurable, 131K default in LiteLLM) |
| **VRAM Required** | ~26 GB (weights) |
| **Model ID** | `nvidia/Qwen3.6-35B-A3B-NVFP4` |
| **vLLM Image** | `vllm/vllm-openai:nightly` |
| **Port** | 8301 |

#### Key Features

- **NVFP4 Quantization**: 4-bit weights with NVIDIA-optimized kernel
- **MoE Architecture**: 35B total, 3B activated per token — efficient inference
- **Text-Only**: No vision encoder; all memory available for KV cache
- **Native Reasoning**: `--reasoning-parser qwen3` prevents thinking tokens in output
- **Native Tool Calling**: `--tool-call-parser qwen3_xml` (official NVIDIA spec)
- **Speculative Decoding**: MTP (Multi-step Predictive Training) support

#### Use Cases

- AI coding agent (Cline) with 250k+ token context
- Technical documentation
- Code generation and completion
- Natural language to SQL/JSON
- General-purpose assistant with coding focus

---

### Qwen3-Coder-Next-FP8

| Attribute | Value |
|-----------|-------|
| **Model Name** | Qwen3-Coder-Next-FP8 |
| **Provider** | Alibaba Cloud |
| **Total Parameters** | 80B |
| **Active Parameters** | 3B (MoE) |
| **Architecture** | Gated DeltaNet (GDN) + Gated Attention + MoE |
| **Quantization** | FP8 |
| **Context Window** | 262K tokens |
| **VRAM Required** | ~118 GB |
| **Model ID** | `Qwen/Qwen3-Coder-Next-FP8` |
| **vLLM Image** | `vllm/vllm-openai:nightly` |
| **Port** | 8300 |

#### Key Features

- **Gated DeltaNet (GDN)**: Linear attention mechanism for faster inference
- **Hybrid Architecture**: Combines GDN, Gated Attention, and MoE
- **512 Experts**: 10 active per forward pass
- **No Reasoning Blocks**: Standard output format, no `...` tags
- **Native Tool Calling**: `tool-call-parser: qwen3_coder`

#### Use Cases

- Code generation and completion
- Technical documentation
- Programming interview questions
- Natural language to SQL/JSON
- General-purpose assistant with coding focus

---

### Nemotron-3-Super-120B-A12B-NVFP4

| Attribute | Value |
|-----------|-------|
| **Model Name** | Nemotron-3-Super-120B-A12B-NVFP4 |
| **Provider** | NVIDIA |
| **Total Parameters** | 120B |
| **Active Parameters** | 12B (MoE) |
| **Architecture** | MoE with 512 experts |
| **Quantization** | NVFP4 (NVIDIA 4-bit) |
| **Context Window** | 262K tokens |
| **VRAM Required** | ~80 GB |
| **Model ID** | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` |
| **vLLM Image** | `vllm/vllm-openai:nightly` |
| **Port** | 8200 |

#### Key Features

- **NVFP4 Quantization**: 4-bit weights with NVIDIA-optimized kernel
- **MoE Architecture**: 512 experts, 12 active per forward pass
- **Reasoning Parser**: Requires custom plugin for response extraction
- **FlashAttention-3**: Optimized attention kernel for Blackwell GPUs
- **Tensor Parallelism**: Supports multi-GPU configurations

#### Use Cases

- General reasoning and problem solving
- Complex multi-step tasks
- Scientific computing
- Technical analysis
- Creative writing with technical depth

---

### nemotron-3-embed-1b-nvfp4 (Embedding Model)

| Attribute | Value |
|-----------|-------|
| **Model Name** | nemotron-3-embed-1b-nvfp4 |
| **Provider** | NVIDIA |
| **Total Parameters** | 1.14B |
| **Architecture** | Pruned Ministral-3-3B-Instruct-2512-based encoder |
| **Output Dimension** | 2048 |
| **Context Window** | 4096 tokens (configured; model supports up to 32768) |
| **VRAM Required** | ~1-2 GB (NVFP4 quantized) |
| **Model ID** | `nvidia/Nemotron-3-Embed-1B-NVFP4` |
| **vLLM Image** | `vllm/vllm-openai:nightly` (requires vLLM 0.25.0+; 0.23.x/0.24.x broken) |
| **Port** | 8302 (Qwen3.8/3.6 stacks) |

#### Key Features

- **Text-only**: No vision encoder — replaces the multimodal llama-nemotron-embed-vl-1b-v2
- **NVFP4 Quantized**: Weights and activations of linear layers quantized via post-training QAD
- **Asymmetric Embedding**: Requires manual `query:`/`passage:` input prefixing
- **Concurrent**: Small enough to run alongside chat engine on same GPU
- **RAG-Ready**: 2048-dim vectors for document retrieval workflows

#### Use Cases

- Vector database embeddings
- Document retrieval and RAG
- Text semantic search

---

## Model Comparison

| Feature | Qwen3.8-27B-NVFP4 | Qwen3.6-35B-A3B-NVFP4 | Qwen3-Coder-Next-FP8 | Nemotron-3-Super-120B | Embedding |
|---------|-------------------|----------------------|---------------------|----------------------|-----------|
| **Context** | 262K | 262K (131K default) | 262K | 262K | 4096 |
| **VRAM (weights)** | ~22 GB | ~26 GB | ~118 GB | ~80 GB | ~1-2 GB |
| **Model Type** | 27B dense | 35B MoE (3B active) | 80B MoE (3B active) | 120B MoE (12B active) | 1.14B text encoder |
| **Quantization** | NVFP4+FP8 (compressed-tensors) | NVFP4 (ModelOpt) | FP8 | NVFP4 | NVFP4 |
| **Output Format** | Standard JSON | Standard JSON | Standard JSON | Reasoning blocks | 2048-dim vector |
| **Vision** | ✅ Yes | ❌ No | ❌ No | ❌ No | ❌ No |
| **Tool Calling** | Native (qwen3_xml, unverified) | Native (qwen3_xml) | Native (qwen3_coder) | Requires parser | N/A |
| **Best For** | Coding (Cline/Claude Code), default | Coding (rollback) | Coding tasks | General reasoning | Embeddings/RAG |
| **Runs Concurrently** | ❌ | ❌ | ❌ | ❌ | ✅ Yes |

---

## Configuration Comparison

### Qwen3.8-27B-NVFP4 (docker-compose.qwen3.8.yml, default)

```yaml
qwen3-8-27b-nvfp4-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
    TRITON_CACHE_DIR: /root/.triton/cache
    FLASHINFER_DISABLE_VERSION_CHECK: "1"
    CUTE_DSL_ARCH: sm_121a
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: "1"
  volumes:
    - vllm-qwen38-triton-cache:/root/.triton/cache
  command:
    --model unsloth/Qwen3.8-27B-NVFP4
    --served-model-name qwen3.8-27b
    --dtype auto
    --kv-cache-dtype fp8
    --gpu-memory-utilization 0.6
    --max-model-len 262144
    --max-num-seqs 4
    --max-num-batched-tokens 8192
    --load-format fastsafetensors
    --mamba-ssm-cache-dtype float32
    --attention-backend flashinfer
    --tool-call-parser qwen3_xml
    --reasoning-parser qwen3
    --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN38_NUM_SPECULATIVE_TOKENS:-2}}'
```

No `--quantization` flag — compressed-tensors NVFP4/FP8 is auto-detected from the checkpoint. No `--moe-backend` or
MoE-specific env vars either — this is a dense model, unlike every other engine in this table. See
`docker-compose.qwen3.8.yml`'s PROVENANCE and CORRECTIONS HISTORY headers for what's verified vs. carried over by
analogy from qwen3.6 (`--tool-call-parser qwen3_xml` in particular is unverified for this model), and for the
`--gpu-memory-utilization 0.4 → 0.6` real-boot OOM correction.

### Qwen3.6-35B-A3B-NVFP4 (docker-compose.qwen3.6.yml, rollback)

```yaml
qwen3-6-35b-nvfp4-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
    TRITON_CACHE_DIR: /root/.triton/cache
    FLASHINFER_DISABLE_VERSION_CHECK: "1"
    CUTE_DSL_ARCH: sm_121a
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: "1"
    VLLM_USE_FLASHINFER_MOE_FP4: "0"
    VLLM_FP8_MOE_BACKEND: flashinfer_cutlass
    VLLM_NVFP4_GEMM_BACKEND: marlin
  volumes:
    - vllm-triton-cache:/root/.triton/cache   # persists Triton's JIT kernel cache across restarts
  command:
    --model nvidia/Qwen3.6-35B-A3B-NVFP4
    --served-model-name qwen3.6-35b-a3b
    --dtype auto
    --quantization modelopt
    --kv-cache-dtype fp8
    --gpu-memory-utilization 0.4
    --max-model-len 262144
    --max-num-seqs 4
    --max-num-batched-tokens 8192
    --load-format fastsafetensors
    --moe-backend marlin
    --max-cudagraph-capture-size 256
    --compilation-config '{"cudagraph_capture_sizes":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,24,32,48,64,96,128,192,256]}'
    --tool-call-parser qwen3_xml
    --reasoning-parser qwen3
    --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN36_NUM_SPECULATIVE_TOKENS:-3},"moe_backend":"triton"}'
```

`--compilation-config`'s `cudagraph_capture_sizes` is densified across 1-16 because that's the effective decode-batch
range for this engine: `--max-num-seqs 4` combined with MTP's per-sequence verification query length of
`1 + num_speculative_tokens` (up to 4 at the default of 3) tops out at `4 × 4 = 16`. `QWEN36_NUM_SPECULATIVE_TOKENS`
(from `.env`, default `3`) is the A/B toggle for the speculative lookahead depth — see `CHANGELOG.md` for the
acceptance-rate reasoning and benchmarking steps.

### Qwen3-Coder-Next-FP8 (docker-compose.yml)

```yaml
qwen3-coder-next-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: "1"
    VLLM_NVFP4_GEMM_BACKEND: marlin
  command:
    --model Qwen/Qwen3-Coder-Next-FP8
    --dtype auto
    --quantization fp8
    --kv-cache-dtype fp8
    --max-model-len 262144
    --mamba-ssm-cache-dtype float32
    --tool-call-parser qwen3_coder
```

### Nemotron-3-Super-120B (docker-compose.nemotron.yml)

```yaml
nemotron-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
    VLLM_NVFP4_GEMM_BACKEND: marlin
    VLLM_USE_FLASHINFER_MOE_FP4: "0"
  volumes:
    - ./scripts/super_v3_reasoning_parser.py:/app/super_v3_reasoning_parser.py:ro
  command:
    --model nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
    --quantization fp4
    --reasoning-parser-plugin /app/super_v3_reasoning_parser.py
    --reasoning-parser super_v3
    --enable-auto-tool-choice
    --tool-call-parser qwen3_coder
```

### Embedding Model (docker-compose.qwen3.8.yml / docker-compose.qwen3.6.yml — identical config in both)

```yaml
nemotron-embed-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
  command:
    --model nvidia/Nemotron-3-Embed-1B-NVFP4
    --served-model-name nemotron-3-embed-1b-nvfp4
    --max-model-len 4096
    --max-num-batched-tokens 4096
    --max-cudagraph-capture-size 4096
    --gpu-memory-utilization 0.1
```

---

## Selecting the Right Model

### Choose Qwen3.8-27B-NVFP4 (default) if:

- You're doing **coding tasks** with Cline/Claude Code — this is the primary/default stack
- You need **vision support** (screenshots, diagrams) alongside coding
- You need **large context** (262K tokens) for long documents
- You're comfortable with a model whose flags are still being empirically verified (see the compose
  file's PROVENANCE header) — first production use is the real test of `--tool-call-parser qwen3_xml`

### Choose Qwen3.6-35B-A3B-NVFP4 (rollback) if:

- Qwen3.8 regresses on something Qwen3.6 was known-good at (tool calling, latency, stability)
- You need **large context** (up to 262K tokens) for long documents
- You need **native tool calling** with a confirmed-working qwen3_xml parser
- You want **fast restarts** with FlashInfer cache persistence (already warmed from prior use)
- You need **efficient memory usage** (only ~26GB weights)

### Choose Qwen3-Coder-Next-FP8 if:

- You need the **80B MoE** model for specific workloads
- You need **262K context** for long documents
- You're doing **coding tasks**
- You need **GDN/SSM layer** stability

### Choose Nemotron-3-Super-120B if:

- You need **strong reasoning** capabilities
- You're doing **general problem solving**
- You're working with **262K context** (matches the full vLLM `--max-model-len`)
- You want **NVIDIA's best model** for Blackwell GPUs

### Choose Embedding Model if:

- You need **vector embeddings** for RAG/document retrieval
- Your embeddings are **text-only** (no image/multimodal support)
- You need embeddings that run **concurrently** with a chat model

---

## Testing Models

### Test Qwen3.8-27B-NVFP4 (default)

```bash
# Switch to Qwen3.8
./scripts/model-switch.sh qwen3.8

# Test API
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.8-27b",
    "messages": [{"role": "user", "content": "Write a Python function to sort a list."}]
  }'
```

### Test Qwen3.6-35B-A3B-NVFP4 (rollback)

```bash
# Switch to Qwen3.6
./scripts/model-switch.sh qwen3.6

# Test API
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.6-35b-a3b",
    "messages": [{"role": "user", "content": "Write a Python function to sort a list."}]
  }'
```

### Test Qwen3-Coder-Next-FP8

```bash
# Switch to Qwen3-Coder-Next
./scripts/model-switch.sh qwen

# Test API
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3-coder-next",
    "messages": [{"role": "user", "content": "Write a Python function to sort a list."}]
  }'
```

### Test Nemotron-3-Super-120B

```bash
# Switch to Nemotron
./scripts/model-switch.sh nemotron

# Test API
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "nemotron-super",
    "messages": [{"role": "user", "content": "Explain the concept of quantum entanglement."}]
  }'
```

### Test Embedding Model

```bash
# Text embedding (via LiteLLM proxy)
curl http://localhost:4000/v1/embeddings \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "nemotron-3-embed-1b-nvfp4", "input": "query: Hello world"}'