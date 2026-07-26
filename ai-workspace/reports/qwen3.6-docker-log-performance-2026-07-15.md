# Qwen 3.6 (35B-A3B-NVFP4) Engine Performance Report — 15 July 2026

## Container Overview
| Property | Value |
|---|---|
| **Container** | `qwen3-6-35b-nvfp4-engine` |
| **Model** | `unsloth/Qwen3.6-35B-A3B-NVFP4-Fast` (Qwen3_5MoeForConditionalGeneration) |
| **vLLM Version** | 0.23.1rc1.dev1042+g8e981630c |
| **GPU** | NVIDIA GB10 (sm121 / Blackwell architecture) |
| **Quantization** | NVFP4 MoE + FP8 KV Cache |
| **Speculative Decoding** | MTP (Multi-Token Prediction), 2 spec tokens |
| **Uptime** | ~9 hours (started 03:20 UTC) |

---

## Throughput Metrics (172 logging intervals)

### Prompt Throughput (tokens/s)
| Metric | Value |
|---|---|
| **Average** | 314 tokens/s |
| **Max (non-zero)** | ~2,297 tokens/s |
| **Typical range** | 300–900 tokens/s during active requests |

### Generation Throughput (tokens/s)
| Metric | Value |
|---|---|
| **Average** | 22.7 tokens/s |
| **Max** | 62.1 tokens/s |
| **Typical range** | 15–45 tokens/s during active requests |

### Generation Throughput (Clarification)
The `Avg generation throughput` reported by vLLM is the **post-verification delivered-token rate** — the actual number of tokens that made it into the output per second, after speculative decoding has already done its work. The 22.7 tok/s average already accounts for speculation speedup; multiplying by the mean acceptance length (2.71) again would be a double-count.

When actively processing requests (filtering out idle ticks), generation throughput typically ranges **40–50 tokens/s**. The lower average of 22.7 tok/s reflects the idle periods included in the 10-second sampling interval.

- **Draft model acceptance rate**: ~85% average

---

## Speculative Decoding Performance
| Metric | Value |
|---|---|
| **Mean Acceptance Length** | 2.71 |
| **Avg Draft Acceptance Rate** | ~85% |
| **Accepted Throughput** | ~15–30 tokens/s |
| **Drafted Throughput** | ~17–35 tokens/s |

The draft model accepts ~2.71 of every 3 proposed tokens, which is good but there's room for improvement. Some intervals showed acceptance rates as low as 50–64% (likely on longer/harder outputs).

---

## Prefix Cache Performance
| Metric | Value |
|---|---|
| **Average Hit Rate** | ~82–85% |
| **Trend** | Gradually increasing from 77% → 88% as cache builds |

Prefix caching is working well and improving over time. At 85%+ hit rate, repeated prompts are nearly free.

---

## GPU Memory & KV Cache
| Metric | Value |
|---|---|
| **Model Load Memory** | 22.19 GiB |
| **KV Cache Size** | 1,443,719 tokens |
| **Available KV Cache** | 16.74 GiB |
| **Max Concurrency** | 5.51x (for 262K token sequences) |
| **CUDA Graph Memory** | ~12.42 GiB estimated |

---

## Startup Timeline
| Phase | Duration |
|---|---|
| Model weight loading (main) | 41.1 seconds |
| Draft model loading | 10.3 seconds |
| Torch.compile (backbone) | 99.2 seconds |
| Initial profiling/warmup | 163.6 seconds |
| FlashInfer autotuning | ~8 seconds (21 ops × 2 passes) |
| CUDA graph capture | ~388 seconds (6.5 min) |
| **vLLM total init** (profile + kv cache + warmup) | **716.97 seconds (~12 min)** |

Container started at 03:20:36 UTC. Engine init completed at 03:34:33 UTC. API server began accepting traffic at ~03:35:06 UTC — total **~14.5 minutes** from container start to first usable request.

---

## Key Observations

### Strengths
1. **Strong prompt processing** — 300–1300+ tokens/s prompt throughput handles long context inputs efficiently
2. **Good speculative decoding** — 2.71 mean acceptance length means ~2.7x effective speedup over raw decode
3. **Excellent prefix cache** — 85%+ hit rate means repeated system prompts are essentially free
4. **FP8 KV cache** — Smart choice for memory efficiency on this model
5. **NVFP4 quantization** — Enables running a 35B MoE model on single GPU

### Areas to Watch
1. **Generation throughput variance** — Drops to 1–7 tokens/s on some requests (likely very long outputs or complex reasoning)
2. **Draft acceptance rate fluctuation** — Ranges from 50% to 100%, suggesting the draft model struggles with certain output patterns
3. **No MoE config file found** — Warning: `E=256,N=512,device_name=NVIDIA_GB10.json` missing; performance may be sub-optimal
4. **CUDAGraph limitation** — PIECEWISE mode only (not FULL) due to spec-decode + FlashInfer incompatibility on this hardware

### Recommendations
1. **Create MoE tuning config** for GB10 GPU to optimize the 256-expert configuration
2. **Monitor for OOM** — KV cache is growing; with 1.4M token capacity, watch for concurrent request spikes
3. **Test `max_num_seqs` with a concurrency-sweep benchmark** — vLLM's DGX Spark guidance recommends keeping it around 4, as increasing beyond that tends to cost more in per-token bandwidth tax on Spark's unified memory than the batching gains buy back. This is a hypothesis to test, not something to simply crank up.
4. **Review `enable_chunked_prefill`** settings if long-prompt workloads increase

---

## Activity Timeline
- **03:20–03:27 UTC**: Startup and warmup (no requests)
- **04:22–04:46 UTC**: First batch of requests (~20 requests in 24 min)
- **04:46–11:40 UTC**: Idle period — **complete log silence** (no heartbeat lines for ~7 hours). Only 2 log entries exist at the tail end (04:46:07, 04:46:17). The vLLM 10-second logging interval stopped entirely during this stretch, consistent with the logger not emitting when `Running: 0` is held for extended periods.
- **11:40–12:06 UTC**: Second burst of activity (~25+ requests in 26 min)

The workload appears to be intermittent with mostly single-request concurrency (0–1 running requests at any time). Note: the ~7-hour gap (04:46–11:40) shows **no log output at all**, not just idle heartbeat lines — the engine was running but vLLM's logger stopped emitting during extended idle periods.
