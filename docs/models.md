# Model Comparison Guide

This guide compares the three supported LLMs for the **NVIDIA DGX Spark (Blackwell GB10)** workstation.

## Model Overview

### Qwen3.6-27B-FP8 (DEFAULT)

| Attribute | Value |
|-----------|-------|
| **Model Name** | Qwen3.6-27B-FP8 |
| **Provider** | Alibaba Cloud |
| **Total Parameters** | 27B |
| **Active Parameters** | 27B (dense) |
| **Architecture** | Gated DeltaNet (GDN) + Gated Attention |
| **Quantization** | FP8 |
| **Context Window** | 262K tokens |
| **VRAM Required** | ~111 GB |
| **Model ID** | `Qwen/Qwen3.6-27B-FP8` |
| **vLLM Image** | `vllm/vllm-openai:v0.19.1-cu130` |
| **Port** | 8301 |

#### Key Features

- **Gated DeltaNet (GDN)**: Linear attention mechanism for faster inference
- **Hybrid Architecture**: Combines GDN and Gated Attention
- **27B Dense Model**: No MoE, all parameters active
- **Vision-Enabled**: Native multimodal (vision + text) support
- **Native Reasoning**: `--reasoning-parser qwen3` prevents thinking tokens in output
- **Native Tool Calling**: `tool-call-parser: qwen3_coder`
- **Speculative Decoding**: MTP (Multi-step Predictive Training) support

#### Use Cases

- Code generation and completion
- Technical documentation
- Programming interview questions
- Natural language to SQL/JSON
- General-purpose assistant with coding focus
- Vision tasks (image analysis)

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
| **vLLM Image** | `vllm/vllm-openai:v0.19.1-cu130` |
| **Port** | 8300 |

#### Key Features

- **Gated DeltaNet (GDN)**: Linear attention mechanism for faster inference
- **Hybrid Architecture**: Combines GDN, Gated Attention, and MoE
- **512 Experts**: 10 active per forward pass
- **No Reasoning Blocks**: Standard output format, no `...<tool_call>` tags
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
| **vLLM Image** | `vllm/vllm-openai:v0.18.1-cu130` |
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

## Model Comparison

| Feature | Qwen3.6-27B-FP8 | Qwen3-Coder-Next-FP8 | Nemotron-3-Super-120B |
|---------|-----------------|---------------------|----------------------|
| **Context** | 262K tokens | 262K tokens | 128K tokens |
| **VRAM** | ~111 GB | ~118 GB | ~80 GB |
| **Model Type** | 27B dense | 80B MoE (3B active) | 120B MoE (12B active) |
| **Output Format** | Standard JSON | Standard JSON | Reasoning blocks |
| **Vision** | ✅ Yes | ❌ No | ❌ No |
| **Tool Calling** | Native support | Native support | Requires parser |
| **Best For** | Coding tasks (default) | Coding tasks | General reasoning |
| **Speed** | Faster | Fast | Slightly slower |
| **Reasoning** | Strong (native) | Limited | Strong |

---

## Configuration Comparison

### Qwen3.6-27B-FP8 (docker-compose.qwen3.6.yml)

```yaml
qwen3-6-27b-engine:
  image: vllm/vllm-openai:v0.19.1-cu130
  environment:
    HF_TOKEN: ${HF_TOKEN}
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: "1"
    VLLM_NVFP4_GEMM_BACKEND: marlin
  command:
    --model Qwen/Qwen3.6-27B-FP8
    --served-model-name qwen3.6-27b
    --dtype auto
    --kv-cache-dtype fp8
    --max-model-len 262144
    --mamba-ssm-cache-dtype float32
    --tool-call-parser qwen3_coder
    --reasoning-parser qwen3
    --enable-auto-tool-choice
    --speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

### Qwen3-Coder-Next-FP8 (docker-compose.yml)

```yaml
qwen3-coder-next-engine:
  image: vllm/vllm-openai:v0.19.1-cu130
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
  image: vllm/vllm-openai:v0.18.1-cu130
  environment:
    HF_TOKEN: ${HF_TOKEN}
    VLLM_NVFP4_GEMM_BACKEND: marlin
    VLLM_FLASHINFER_ALLREDUCE_BACKEND: trtllm
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

---

## Selecting the Right Model

### Choose Qwen3.6-27B-FP8 (default) if:

- You need **262K context** for long documents
- You're doing **coding tasks** (Python, JavaScript, etc.)
- You want **vision support** (image analysis)
- You need **faster inference** with native tool calling
- You prefer **native reasoning** without thinking token leakage

### Choose Qwen3-Coder-Next-FP8 if:

- You need the **80B MoE** model for specific workloads
- You need **262K context** for long documents
- You're doing **coding tasks**
- You need **faster inference** with native tool calling

### Choose Nemotron-3-Super-120B if:

- You need **strong reasoning** capabilities
- You're doing **general problem solving**
- You're working with **128K context** (sufficient for most tasks)
- You want **NVIDIA's best model** for Blackwell GPUs

---

## Claude Code Models

The LiteLLM proxy supports Claude Code API compatibility through virtual model names.

### claude-sonnet-4-6 (DEFAULT)

| Attribute | Value |
|-----------|-------|
| **Model Name** | claude-sonnet-4-6 |
| **Purpose** | Main tasks, complex reasoning |
| **Backend** | Qwen3.6-27B-FP8 (vLLM port 8301) |
| **Max Tokens** | 262,144 input / 16,384 output |
| **Tool Calling** | Supported |
| **Function Calling** | Supported |
| **Vision** | Supported |

**Use Cases:**
- Complex multi-step reasoning tasks
- Code generation and analysis
- Technical documentation
- Vision tasks (image analysis)
- General assistant with coding focus

---

### claude-haiku-4-6

| Attribute | Value |
|-----------|-------|
| **Model Name** | claude-haiku-4-6 |
| **Purpose** | Fast/background tasks |
| **Backend** | Qwen3.6-27B-FP8 (vLLM port 8301) |
| **Max Tokens** | 32,768 input / 4,096 output |
| **Tool Calling** | Supported |
| **Function Calling** | Supported |
| **Vision** | Supported |

**Use Cases:**
- Fast background processing
- Simple tasks and queries
- Automated workflows
- Quick responses

---

## Testing Models

### Test Qwen3.6-27B-FP8 (default)

```bash
# Switch to Qwen3.6
./scripts/model-switch.sh qwen3.6

# Test API
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.6-27b",
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