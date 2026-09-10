# Qwen3.6 Engine Optimizations — Summary Report

**Date:** 2026-08-28
**Branch:** `fix/anthropic-messages-thinking-passthrough` (branched off `feat/qwen3.8-27b-nvfp4-stack`)
**Base:** commit `90c6b13` (cache-elimination verification documentation)

---

## Overview

Three vLLM engine configuration changes were applied to `docker-compose.qwen3.6.yml` to optimize the Qwen3.6-35B-A3B-NVFP4 engine for better multi-modal encoder throughput and more robust tool-call parsing.

---

## Changes

### 1. `--mm-encoder-tp-mode data` (NEW)

**What it does:** Controls how multi-modal (vision/audio) encoder inference is parallelized across tensor parallelism (TP) ranks.

**Values:**
- `"weights"` (default): Split the weights of each layer across TP ranks (standard TP behavior)
- `"data"`: Host the **full weights on each TP rank**, but split the **batched input data** across ranks to process in parallel

**Why this matters:** For multi-modal models, the vision/audio encoder can become a bottleneck. Setting `data` mode allows all GPUs to work in parallel on different parts of the batch, improving throughput when the encoder is compute-bound rather than memory-bound.

**Source:** [vLLM config/multimodal.py](https://github.com/vllm-project/vllm/blob/main/vllm/config/multimodal.py) — `MMEncoderTPMode` literal type.

---

### 2. `--tool-call-parser qwen3_xml` (CHANGED from `qwen3_coder`)

**What it does:** Specifies the parser used to extract tool calls from the model's output.

**Change:** Switched from `qwen3_coder` to `qwen3_xml` to match the official vLLM recipe for this checkpoint.

**Verification:** Previously verified that `qwen3_coder` correctly selected tools and produced well-formed JSON arguments in a 5-tool coding-agent palette test. This change is based on the official vLLM recipe, not empirical testing — future verification recommended.

**Source:** [recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B](https://recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B?hardware=dgx_spark_gb10&variant=nvfp4)

---

### 3. `--reasoning-parser qwen3` (NEW)

**What it does:** Specifies the parser used to extract reasoning/thinking content from the model's output.

**Why added:** Ensures proper extraction of chain-of-thought reasoning traces, which are critical for models that use explicit reasoning before answering.

**Source:** vLLM's reasoning parser registry — `qwen3` is the designated parser for Qwen3-family models.

---

## Impact Assessment

| Change | Risk | Expected Benefit |
|--------|------|------------------|
| `--mm-encoder-tp-mode data` | Low — falls back to `weights` if unsupported | Better multi-modal encoder throughput |
| `--tool-call-parser qwen3_xml` | Medium — unverified against real traffic | Alignment with official recipe; potentially more robust parsing |
| `--reasoning-parser qwen3` | Low — explicit parser for Qwen3 models | Correct reasoning trace extraction |

---

## Notes

- The `--mm-encoder-tp-mode data` change is particularly relevant if multi-modal inputs (images, audio) are expected in the workload.
- Tool-call parser change should be verified with real traffic before committing.