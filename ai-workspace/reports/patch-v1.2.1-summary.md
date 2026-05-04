# Patch v1.2.1 — Summary Report

**Date:** 2026-05-04
**Branch:** `bugfix/qwen3.6-resource-tuning`
**Base commit:** `2667fc6` (v1.2.0 - Add Qwen3.6-27B-FP8 support as default model)

---

## Overview

This patch addresses resource tuning for the Qwen3.6-27B-FP8 vLLM engine. The changes reduce GPU memory utilization and sequence limits to improve stability under load, and remove a deprecated vLLM flag.

---

## Changes

### `docker-compose.qwen3.6.yml`

| Parameter | Old Value | New Value | Reason |
|-----------|-----------|-----------|--------|
| `--gpu-memory-utilization` | `0.85` | `0.60` | Reduce VRAM pressure to prevent OOM errors during peak load |
| `--max-num-seqs` | `32` | `20` | Lower concurrency to match reduced memory budget |
| `--language-model-only` | present | removed | Flag no longer needed/compatible with current vLLM version |

---

## Impact

- **Stability:** Lower GPU memory utilization (60% vs 85%) provides headroom for large context windows and speculative decoding, reducing OOM risk.
- **Throughput:** Reduced max sequences (20 vs 32) may slightly decrease concurrent request capacity, but improves per-request latency consistency.
- **Compatibility:** Removing `--language-model-only` ensures compatibility with latest vLLM versions where this flag may be deprecated.

---

## Testing Recommendations

1. Verify Qwen3.6 container starts without OOM errors
2. Monitor GPU memory usage under load with `nvidia-smi`
3. Test concurrent requests (up to 20 sequences) for stability
4. Verify response latency is acceptable with lower memory budget