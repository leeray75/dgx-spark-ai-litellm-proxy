# Model Comparison Guide

This guide compares the three supported LLMs for the **NVIDIA DGX Spark (Blackwell GB10)** workstation.

## Model Overview

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
| **Context Window** | 128K tokens |
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

### llama-nemotron-embed-vl-1b-v2 (Embedding Model)

| Attribute | Value |
|-----------|-------|
| **Model Name** | llama-nemotron-embed-vl-1b-v2 |
| **Provider** | NVIDIA |
| **Total Parameters** | ~1.7B |
| **Architecture** | Llama 3.2 1B LM + SigLip2 400M vision encoder |
| **Output Dimension** | 2048 |
| **Context Window** | 10240 tokens (image+text combined) |
| **VRAM Required** | ~4-6 GB |
| **Model ID** | `nvidia/llama-nemotron-embed-vl-1b-v2` |
| **vLLM Image** | `vllm/vllm-openai:nightly` |
| **Port** | 8302 (Qwen3.6 stack only) |

#### Key Features

- **Multimodal**: Embeds text, images, and image+text pairs in shared space
- **Concurrent**: Small enough to run alongside chat engine on same GPU
- **RAG-Ready**: 2048-dim vectors for document retrieval workflows
- **Built with Llama**: Uses Llama 3.2 1B language model + SigLip2 400M vision encoder

#### Use Cases

- Vector database embeddings
- Document retrieval and RAG
- Image-text similarity search
- Multimodal semantic search

---

## Model Comparison

| Feature | Qwen3.6-35B-A3B-NVFP4 | Qwen3-Coder-Next-FP8 | Nemotron-3-Super-120B | Embedding |
|---------|----------------------|---------------------|----------------------|-----------|
| **Context** | 262K (131K default) | 262K | 128K | 10240 |
| **VRAM (weights)** | ~26 GB | ~118 GB | ~80 GB | ~4-6 GB |
| **Model Type** | 35B MoE (3B active) | 80B MoE (3B active) | 120B MoE (12B active) | 1.7B VLM |
| **Quantization** | NVFP4 | FP8 | NVFP4 | N/A |
| **Output Format** | Standard JSON | Standard JSON | Reasoning blocks | 2048-dim vector |
| **Vision** | ❌ No | ❌ No | ❌ No | ✅ Yes (embedder) |
| **Tool Calling** | Native (qwen3_xml) | Native (qwen3_coder) | Requires parser | N/A |
| **Best For** | Coding (Cline) | Coding tasks | General reasoning | Embeddings/RAG |
| **Runs Concurrently** | ❌ | ❌ | ❌ | ✅ Yes |

---

## Configuration Comparison

### Qwen3.6-35B-A3B-NVFP4 (docker-compose.qwen3.6.yml)

```yaml
qwen3-6-35b-nvfp4-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
    FLASHINFER_DISABLE_VERSION_CHECK: "1"
    CUTE_DSL_ARCH: sm_121a
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: "1"
    VLLM_USE_FLASHINFER_MOE_FP4: "0"
    VLLM_FP8_MOE_BACKEND: flashinfer_cutlass
    VLLM_NVFP4_GEMM_BACKEND: marlin
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
    --tool-call-parser qwen3_xml
    --reasoning-parser qwen3
    --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
```

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

### Embedding Model (docker-compose.qwen3.6.yml)

```yaml
nemotron-embed-vl-engine:
  image: vllm/vllm-openai:nightly
  environment:
    HF_TOKEN: ${HF_TOKEN}
  command:
    --model nvidia/llama-nemotron-embed-vl-1b-v2
    --served-model-name llama-nemotron-embed-vl-1b-v2
    --trust-remote-code
    --max-model-len 10240
    --gpu-memory-utilization 0.1
```

---

## Selecting the Right Model

### Choose Qwen3.6-35B-A3B-NVFP4 (default) if:

- You need **large context** (up to 262K tokens) for long documents
- You're doing **coding tasks** with Cline/AI agents
- You need **native tool calling** with qwen3_xml parser
- You want **fast restarts** with FlashInfer cache persistence
- You need **efficient memory usage** (only ~26GB weights)

### Choose Qwen3-Coder-Next-FP8 if:

- You need the **80B MoE** model for specific workloads
- You need **262K context** for long documents
- You're doing **coding tasks**
- You need **GDN/SSM layer** stability

### Choose Nemotron-3-Super-120B if:

- You need **strong reasoning** capabilities
- You're doing **general problem solving**
- You're working with **128K context** (sufficient for most tasks)
- You want **NVIDIA's best model** for Blackwell GPUs

### Choose Embedding Model if:

- You need **vector embeddings** for RAG/document retrieval
- You need **multimodal** (text + image) embeddings
- You need embeddings that run **concurrently** with a chat model

---

## Testing Models

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
  -d '{"model": "llama-nemotron-embed-vl-1b-v2", "input": "Hello world"}'