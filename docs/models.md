# Model Comparison Guide

This guide compares the supported LLMs for the **NVIDIA DGX Spark (Blackwell GB10)** workstation.

## Model Overview

### Qwen3.8-27B-NVFP4 (DEFAULT — see throughput/accuracy note below)

| Attribute | Value |
|-----------|-------|
| **Model Name** | Qwen3.8-27B-NVFP4 |
| **Provider** | NVIDIA (checkpoint swapped from Inferact 2026-09-09 — see CHANGELOG.md) |
| **Total Parameters** | 27B (dense — not MoE) |
| **Active Parameters** | 27B (all) |
| **Architecture** | Hybrid Gated-DeltaNet + Gated-Attention, with vision encoder |
| **Quantization** | NVIDIA ModelOpt (nvidia-modelopt v0.48.0), compressed-tensors schema — NVFP4 on MLP + `lm_head`, FP8 on attention/linear-attention layers |
| **Context Window** | 262K tokens native |
| **VRAM Required** | ~22-25 GiB weights (varies by checkpoint tested; see `docker-compose.qwen3.8.yml` for exact boot-log figures) |
| **Model ID** | `nvidia/Qwen3.8-27B-NVFP4` |
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

#### Throughput — real live test confirms the trade (see Accuracy Benchmarks below)

**Real live-usage result (the head-to-head test that was pending): 20.4 tok/s median, 20.26 tok/s mean**, sampled
over a 6-hour window with 221 active generation samples on `nvidia/Qwen3.8-27B-NVFP4`
(`qwen3-8-27b-nvfp4-engine`). Mean and median are nearly identical, so this is steady sustained throughput under
real usage, not a number skewed by bursts.

For reference, the earlier synthetic single-request benchmark (direct engine, two independent 700-token runs)
measured **~24.3-24.9 tok/s** (28.07-28.85s per run, 96% GPU utilization, ~37-38W power draw) — a real ~35-40%
improvement over the retired Inferact checkpoint's ~17.5-18.5 tok/s at the time, but that number is not what
callers actually see under real usage; the 20.4 tok/s live median above is. Still memory-bandwidth-bound (dense
27B streaming all weights every token) rather than compute-bound, the same root cause every Qwen3.8 checkpoint
tried so far has shown.

qwen3.6's oft-cited **~83-84 tok/s** is a clean synthetic single-request benchmark number, not representative of
live usage — the user reports qwen3.6 typically runs **~40-45 tok/s** under real/live conditions (informal
estimate, not yet measured with the same 6-hour/sampled rigor as qwen3.8's number above). Taking that at face
value, qwen3.8 is roughly **~2x slower** under real live conditions — not the ~1.6-1.8x or ~3.3x estimates floating
around in earlier notes (those compared mismatched synthetic-vs-live or synthetic-vs-synthetic numbers). This
real head-to-head live test is now DONE, not pending. Full investigation (including both retired checkpoints'
crash/throughput history) is in `docker-compose.qwen3.8.yml`'s header.

#### Use Cases

- **Primary/default stack as of 2026-09-09** — NVIDIA's own published accuracy benchmarks favor this checkpoint
  over qwen3.6 on every overlapping metric (see Accuracy Benchmarks below); the throughput cost is an explicit,
  deliberate trade the user chose to accept. The real 6-hour live test now confirms that cost is a genuine ~2x,
  not the narrower ~1.6-1.8x earlier synthetic-vs-live comparisons suggested — the user is sticking with the
  accuracy-over-speed call regardless
- Vision-assisted coding tasks (screenshots, diagrams) — the only stack of the two with a vision encoder
- Coding tasks with Cline/Claude Code where the accuracy gain matters more than raw tok/s

---

### Qwen3.6-35B-A3B-NVFP4 (ROLLBACK)

**Rollback stack as of 2026-09-09** — kept fully buildable and unmodified as the known-good fallback if the
now-confirmed ~2x throughput cost (see Qwen3.8's Throughput section above) stops being worth the accuracy gain in
practice (see `docker-compose.qwen3.6.yml`'s header and CHANGELOG.md).

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
- **Native Tool Calling**: `--tool-call-parser qwen3_xml` (matches the official vLLM recipe, confirmed 2026-09-02
  against a freshly-pasted copy of the recipe's exact command — this flag flip-flopped repeatedly before that;
  see `docker-compose.qwen3.6.yml` corrections item 21)
- **Thinking disabled by default**: `--default-chat-template-kwargs '{"enable_thinking":false}'` (2026-09-02) —
  the reasoning pass was found to consume 72-91% of a constrained `max_tokens` budget on long, multi-requirement
  tickets, truncating later requirements before the model acted on them; verified fixed both directly against
  the engine and end-to-end via a real Cline CLI run against a cloned repo
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
| **Tool Calling** | Native (qwen3_coder, unverified) | Native (qwen3_xml) | Native (qwen3_coder) | Requires parser | N/A |
| **Best For** | Coding (Cline/Claude Code), default | Coding (rollback) | Coding tasks | General reasoning | Embeddings/RAG |
| **Runs Concurrently** | ❌ | ❌ | ❌ | ❌ | ✅ Yes |

---

## Accuracy Benchmarks (NVIDIA-published, NVFP4-quantized)

NVIDIA's own published benchmarks for each model's NVFP4-quantized checkpoint (from each model's HF model card)
show qwen3.8 ahead of qwen3.6 on every overlapping metric:

| Benchmark | Qwen3.6-35B-A3B-NVFP4 | Qwen3.8-27B-NVFP4 | Δ (qwen3.8 − qwen3.6) |
|-----------|----------------------|-------------------|------------------------|
| GPQA Diamond | 84.8 | 88.01 | +3.2 |
| AA-LCR | 62.0 | 73.38 | +11.4 |
| SciCode | 40.6 | 48.41 | +7.8 |
| IFBench | 62.8 | 78.93 | +16.1 |

This is the basis for the 2026-09-09 decision to make qwen3.8 the default/primary stack — trading throughput for
meaningfully better accuracy. A real 6-hour/221-sample live test has since confirmed that trade: qwen3.8 sustains
20.4 tok/s median (20.26 mean) under real usage, vs. qwen3.6's informal ~40-45 tok/s live estimate — roughly ~2x
slower, a real cost the user has chosen to accept (quality over raw speed). See `docker-compose.qwen3.8.yml`'s
RESULT section and CHANGELOG.md for the full reasoning.

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
    --model nvidia/Qwen3.8-27B-NVFP4
    --served-model-name qwen3.8-27b
    --dtype auto
    --kv-cache-dtype fp8_e4m3
    --gpu-memory-utilization 0.6
    --max-model-len 262144
    --max-num-seqs 4
    --max-num-batched-tokens 8192
    --mamba-ssm-cache-dtype float32
    --trust-remote-code
    --enable-auto-tool-choice
    --tool-call-parser qwen3_coder
    --reasoning-parser qwen3
    --mm-encoder-tp-mode data
    --seed 0
    --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN38_NUM_SPECULATIVE_TOKENS:-3}}'
```

No `--quantization` flag — auto-detected from the checkpoint's compressed-tensors-shaped `config.json` (despite
the model card's own "quantized with Model Optimizer" framing). No `--moe-backend` or MoE-specific env vars —
this is a dense model, unlike every other engine in this table.

**SIMPLIFICATION PASS (2026-09-09/10):** following a report of excessive agentic self-verification (26 tool-call
steps on one subtask vs. 7-13 on others in the same OpenCode run), `--override-generation-config` and
`--default-chat-template-kwargs` were dropped to let the model's own `generation_config.json`/chat-template
defaults apply, matching NVIDIA's official sample command exactly on this axis. **This did NOT change the actual
sampling behavior** — the checkpoint's own shipped `generation_config.json` specifies `temperature: 1.0, top_k:
20, top_p: 0.95`, identical to what the removed override was setting, so this was confirming the vendor default
rather than fixing a misconfiguration. `enable_thinking` remains on by default either way (never explicitly set),
so the known "small `max_tokens` can return an empty response, all tokens spent on reasoning" behavior is
unchanged — confirmed via direct retest. Also dropped as unneeded cruft, not tied to any known incident:
`--load-format fastsafetensors`, `--attention-backend flashinfer`, `--async-scheduling`, `--enable-prefix-caching`,
`--uvicorn-log-level warning`. Kept despite being absent from the official command — each tied to a real incident
or correctness need: `--trust-remote-code`, `--mamba-ssm-cache-dtype float32`, `--speculative-config` (MTP), and
the GB10-safe `0.6/4/8192` memory values (not the official recipe's GB300-scaled `0.85/32/32768` — this box's own
history shows 0.85 causes real swap). See `docker-compose.qwen3.8.yml`'s SIMPLIFICATION PASS note for the full
reasoning.

**Real live-usage throughput, measured across two windows:**
- 6-hour/221-sample window (before the simplification pass): 20.4 tok/s median (20.26 mean, steady/sustained)
- Post-simplification/421-sample window: 22.8 tok/s median (26.41 mean — mean now above median, reflecting some
  heavily-batched/concurrent intervals) — a real ~12% median improvement, most likely from the freed-up KV cache
  headroom (see below) letting more requests batch together during busy periods, not from any sampling/thinking
  change (which, per above, didn't actually change)

KV cache headroom also improved after the simplification pass: 1,309,255 tokens / 4.99x concurrency (up from
746,890 tokens / 2.85x) at the same `--gpu-memory-utilization 0.6` — freed by dropping the removed flags. The
earlier synthetic single-request benchmark measured ~24.3-24.9 tok/s (two independent 700-token runs, pre-dating
the simplification pass), a real ~35-40% improvement over the retired Inferact checkpoint's ~17.5-18.5 tok/s, but
still memory-bandwidth-bound like every Qwen3.8 checkpoint tried so far — live numbers above are what actually
matters for real usage. See `docker-compose.qwen3.8.yml`'s CHECKPOINT SWAP/RESULT sections (and the ARCHIVED
section) for the full investigation across all three checkpoints tried.

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
    --gpu-memory-utilization 0.5
    --max-model-len 262144
    --max-num-seqs 8
    --max-num-batched-tokens 8192
    --load-format fastsafetensors
    --moe-backend marlin
    --max-cudagraph-capture-size 256
    --compilation-config '{"cudagraph_capture_sizes":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,48,64,96,128,192,256]}'
    --tool-call-parser qwen3_xml
    --reasoning-parser qwen3
    --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN36_NUM_SPECULATIVE_TOKENS:-3},"moe_backend":"triton"}'
    --default-chat-template-kwargs '{"preserve_thinking":true,"enable_thinking":false}'
```

`--gpu-memory-utilization 0.5` and `--max-num-seqs 8` were aligned to the official vLLM recipe on 2026-08-27 —
see `docker-compose.qwen3.6.yml` corrections items 19-20 for the full diff and verification (including a real
5-tool tool-calling test). `--tool-call-parser` flip-flopped repeatedly after that (items 16/17/19/20) before
settling back on `qwen3_xml` on 2026-09-02 by diffing a freshly-pasted copy of the official recipe's exact
command — an exact match on every flag (item 21). `enable_thinking:false` was added the same day: the reasoning
pass was found to consume 72-91% of a constrained `max_tokens` budget on long, multi-requirement tickets,
truncating later requirements before the model ever acted on them — disabling it by default fixed this, verified
both directly against the engine and end-to-end via a real Cline CLI run against a cloned open-source repo.

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

### Choose Qwen3.8-27B-NVFP4 (default) if:

- You're doing **coding tasks** with Cline/Claude Code and want the **better accuracy** — NVIDIA's own published
  benchmarks show qwen3.8 ahead of qwen3.6 on every overlapping metric (GPQA Diamond, AA-LCR, SciCode, IFBench —
  see Accuracy Benchmarks above)
- You specifically need **vision support** (screenshots, diagrams) — the only stack of the two with a vision
  encoder
- You can accept the confirmed throughput trade: a real 6-hour/221-sample live test measured **20.4 tok/s
  median (20.26 mean)**, roughly **~2x slower** than qwen3.6's informal ~40-45 tok/s live estimate (qwen3.6's
  often-cited ~83-84 tok/s is a synthetic single-request number, not representative of live use)
- Understand this is an explicit, deliberate trade (accuracy over raw speed) — the live test above is now DONE,
  not pending, and confirms the cost is real; the user is sticking with the accuracy-over-speed call anyway

### Choose Qwen3.6-35B-A3B-NVFP4 (rollback) if:

- You need **maximum throughput** under real/live usage — ~40-45 tok/s live (informal estimate; up to ~83-84
  tok/s in a clean synthetic single-request benchmark)
- You need **large context** (up to 262K tokens) for long documents
- You need **native tool calling** — `qwen3_xml` parser, confirmed against the official recipe 2026-09-02
  (see `docker-compose.qwen3.6.yml` corrections item 21)
- You want **fast restarts** with FlashInfer cache persistence (already warmed from prior use)
- You need **efficient memory usage** (only ~26GB weights)
- You'd rather not accept qwen3.8's now-confirmed ~2x throughput cost, even with its accuracy advantage

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