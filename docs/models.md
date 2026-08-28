# Model Comparison Guide

This guide compares the supported LLMs for the **NVIDIA DGX Spark (Blackwell GB10)** workstation.

## Model Overview

### Qwen3.8-27B-NVFP4 (EXPERIMENTAL — NOT recommended, see throughput note below)

| Attribute | Value |
|-----------|-------|
| **Model Name** | Qwen3.8-27B-NVFP4 |
| **Provider** | Inferact (swapped from Unsloth 2026-08-26 — see CHANGELOG.md) |
| **Total Parameters** | 27B (dense — not MoE) |
| **Active Parameters** | 27B (all) |
| **Architecture** | Hybrid Gated-DeltaNet + Gated-Attention, with vision encoder |
| **Quantization** | NVIDIA ModelOpt NVFP4 (W4A4, group size 16); `lm_head` NOT quantized |
| **Context Window** | 262K tokens native |
| **VRAM Required** | ~24.97 GiB weights (confirmed via boot log) |
| **Model ID** | `Inferact/Qwen3.8-27B-NVFP4` |
| **vLLM Image** | `vllm/vllm-openai:nightly` |
| **Port** | 8301 |

#### Key Features

- **Vision-capable**: has a vision encoder, unlike qwen3.6's text-only checkpoint
- **Dense architecture**: no MoE routing — simpler kernel selection, no `moe_backend` config needed
- **Same ModelOpt quantization scheme as qwen3.6**, but vLLM auto-selects the NATIVE
  `FlashInferCutlassNvFp4LinearKernel` for this checkpoint rather than Marlin (unlike qwen3.6, which uses
  Marlin for the same quant_method on the same hardware — the discrepancy is unconfirmed)
- **Native Reasoning**: `--reasoning-parser qwen3`
- **Tool Calling**: `--tool-call-parser qwen3_coder` — the vLLM recipe's recommendation for this checkpoint,
  **not independently verified** against a real Cline/Claude Code tool-calling session
- **Speculative Decoding**: MTP support, `num_speculative_tokens=3` (matches the vLLM recipe's recommendation)

#### Throughput — NOT RECOMMENDED

Real measured throughput: **~17.5 tok/s** (700 tokens in 39.95s), with 96% GPU utilization but only ~34W power
draw — the same low-power-despite-busy signature the previously-tried Unsloth checkpoint showed at ~20 tok/s.
Both Qwen3.8 checkpoints tried so far land in the same slow class; **qwen3.6 (~83.7 tok/s) is the only proven-fast
option and remains the default.** Full investigation (including the retired Unsloth checkpoint's own crash
history) is in `docker-compose.qwen3.8.yml`'s header.

#### Use Cases

- Not currently recommended for real work — kept as an experimental option pending a vLLM build with better
  SM121 kernel support for NVFP4 on this architecture family
- Vision-assisted coding tasks, if/when the throughput issue is resolved

---

### Qwen3.6-35B-A3B-NVFP4 (DEFAULT)

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
- **Native Tool Calling**: `--tool-call-parser qwen3_coder` (per the official vLLM recipe; verified against a
  real 5-tool tool-calling test 2026-08-27)
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
| **Tool Calling** | Native (qwen3_coder, unverified) | Native (qwen3_coder, verified) | Native (qwen3_coder) | Requires parser | N/A |
| **Best For** | Coding (rollback) | Coding (Cline/Claude Code), default | Coding tasks | General reasoning | Embeddings/RAG |
| **Runs Concurrently** | ❌ | ❌ | ❌ | ❌ | ✅ Yes |

---

## Configuration Comparison

### Qwen3.8-27B-NVFP4 (docker-compose.qwen3.8.yml, experimental)

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
    --model Inferact/Qwen3.8-27B-NVFP4
    --served-model-name qwen3.8-27b
    --dtype auto
    --quantization modelopt
    --kv-cache-dtype fp8
    --gpu-memory-utilization 0.6
    --max-model-len 262144
    --max-num-seqs 4
    --max-num-batched-tokens 8192
    --load-format fastsafetensors
    --mamba-ssm-cache-dtype float32
    --attention-backend flashinfer
    --tool-call-parser qwen3_coder
    --reasoning-parser qwen3
    --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN38_NUM_SPECULATIVE_TOKENS:-3}}'
```

Explicit `--quantization modelopt` — same scheme qwen3.6 uses. No `--moe-backend` or MoE-specific env vars —
this is a dense model, unlike every other engine in this table. **Real measured throughput ~17.5 tok/s**, same
slow class as the previously-tried Unsloth checkpoint — see `docker-compose.qwen3.8.yml`'s PROVENANCE, RESULT,
and ARCHIVED sections for the full investigation of both checkpoints tried so far. Not recommended for real use.

### Qwen3.6-35B-A3B-NVFP4 (docker-compose.qwen3.6.yml, default)

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
    --gpu-memory-utilization 0.5
    --max-model-len 262144
    --max-num-seqs 8
    --max-num-batched-tokens 8192
    --load-format fastsafetensors
    --moe-backend marlin
    --max-cudagraph-capture-size 256
    --compilation-config '{"cudagraph_capture_sizes":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,48,64,96,128,192,256]}'
    --tool-call-parser qwen3_coder
    --reasoning-parser qwen3
    --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN36_NUM_SPECULATIVE_TOKENS:-3},"moe_backend":"triton"}'
```

`--gpu-memory-utilization 0.5`, `--max-num-seqs 8`, and `--tool-call-parser qwen3_coder` were aligned to the
official vLLM recipe on 2026-08-27 (previously `0.6`/`4`/`qwen3_xml`) — see `docker-compose.qwen3.6.yml`
corrections items 19-20 for the full diff and verification (including a real 5-tool tool-calling test).

`--compilation-config`'s `cudagraph_capture_sizes` is densified across 1-32 because that's the effective decode-batch
range for this engine: `--max-num-seqs 8` combined with MTP's per-sequence verification query length of
`1 + num_speculative_tokens` (up to 4 at the default of 3) tops out at `8 × 4 = 32`. `QWEN36_NUM_SPECULATIVE_TOKENS`
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

### Choose Qwen3.8-27B-NVFP4 (experimental — not currently recommended) if:

- You specifically need **vision support** (screenshots, diagrams) and can accept ~17-20 tok/s
- You want to help further investigate the throughput gap (see CHANGELOG.md — dense-vs-MoE architecture is the
  current leading theory, not fixable by kernel/config changes; two checkpoints and two kernel backends tried)

### Choose Qwen3.6-35B-A3B-NVFP4 (default) if:

- You're doing **coding tasks** with Cline/Claude Code — this is the primary/default stack, ~83 tok/s
- You need **large context** (up to 262K tokens) for long documents
- You need **native tool calling** — `qwen3_coder` parser, verified against a real 5-tool tool-calling test
  (2026-08-27, see `docker-compose.qwen3.6.yml` corrections item 19)
- You want **fast restarts** with FlashInfer cache persistence (already warmed from prior use)
- You need **efficient memory usage** (only ~22GB weights)

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

### Test Qwen3.8-27B-NVFP4 (experimental)

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

### Test Qwen3.6-35B-A3B-NVFP4 (default)

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