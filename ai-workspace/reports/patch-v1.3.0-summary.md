# Patch v1.3.0 — Summary Report

**Date:** 2026-07-13
**Branch:** `bugfix/qwen3.6-resource-tuning` (working tree; not yet committed)
**Base:** current working tree of `docker-compose.qwen3.6.yml` / `litellm-config.yaml`
(these two files already carried unrelated, uncommitted resource-tuning edits
before this patch — this report covers only the embedding-model addition
described below, not those pre-existing changes)

---

## Overview

Adds multimodal embedding support to the Qwen3.6 stack via
[`nvidia/llama-nemotron-embed-vl-1b-v2`](https://huggingface.co/nvidia/llama-nemotron-embed-vl-1b-v2)
— a ~1.7B-param VLM embedder (Llama 3.2 1B LM + SigLip2 400M vision encoder)
that embeds text, page images, and image+text pairs into a shared 2048-dim
space, for RAG / document retrieval use cases.

Unlike the three main chat models (which are mutually exclusive on this
box due to GPU memory), this model is small enough to run **concurrently**
alongside whichever chat engine is active. It is currently wired into
`docker-compose.qwen3.6.yml` only.

---

## Changes

### `docker-compose.qwen3.6.yml`

- Added service `nemotron-embed-vl-engine` — a second `vllm/vllm-openai:nightly`
  container serving `nvidia/llama-nemotron-embed-vl-1b-v2` on port `8302`
  (external) / `8000` (internal).
  - `--trust-remote-code` and `--max-model-len 10240` per the model card
    (10240 covers the largest supported modality, image+text combined).
  - `--gpu-memory-utilization 0.1` — conservative reservation; the chat
    engine already runs at `0.4`, leaving ample headroom on the 128GB
    unified pool for a model this size (~4-6GB weights).
  - Requires vLLM ≥0.17.0 to register the `LlamaNemotronVLModel`
    architecture — already satisfied by the `:nightly` image in use.
  - New named volume `vllm-embed-compile-cache` (own `/root/.cache/vllm`,
    separate from the chat engine's, since the two containers have
    different model/config hashes).
  - `litellm` now also depends on `nemotron-embed-vl-engine` with
    `condition: service_healthy`.
- Documented port `8302` in the file's external-ports header comment.

### `litellm-config.yaml`

- Added `model_name: llama-nemotron-embed-vl-1b-v2` to `model_list`,
  routing to `hosted_vllm/llama-nemotron-embed-vl-1b-v2` at
  `http://nemotron-embed-vl-engine:8000/v1`, with `model_info.mode: embedding`
  and `output_vector_size: 2048`.

### `CLAUDE.md`

- Added the embedding model to the model-alias table, access-points table,
  and a `/v1/embeddings` curl example. Clarified that the "only one engine
  at a time" GPU constraint applies to the three chat models, not this one.

---

## Impact

- **New capability:** `POST /v1/embeddings` on the LiteLLM proxy (port 4000)
  now accepts text, image, or image+text input and returns 2048-dim vectors,
  enabling RAG/document-retrieval workflows on top of the existing stack.
- **GPU/memory:** adds a second vLLM process on the same GPU. Estimated
  additional footprint is small relative to the 128GB unified pool, but has
  **not been measured on hardware** — verify actual KV cache and swap impact
  on the next real restart (same caveat this file already applies to every
  other memory-tuning change).
- **Startup time:** `litellm` now also waits on the embedding engine's
  healthcheck (900s start_period, much shorter than the chat engine's
  3600s) before serving — should not meaningfully change total stack
  startup, since the chat engine's healthcheck is already the long pole.
- **License:** distinct from the chat models' licenses — governed by the
  NVIDIA Open Model License plus the Llama 3.2 Community Model License
  (model is "Built with Llama"). No action needed beyond the existing
  `HF_TOKEN` requirement, but worth noting if this stack is ever
  redistributed.

---

## Testing Recommendations

1. `docker compose -f docker-compose.qwen3.6.yml up -d` and confirm both
   `qwen3-6-35b-nvfp4-engine` and `nemotron-embed-vl-engine` reach healthy.
2. Text embedding:
   `curl http://localhost:4000/v1/embeddings -H "Authorization: Bearer $LITELLM_MASTER_KEY" -d '{"model":"llama-nemotron-embed-vl-1b-v2","input":"hello"}'`
   — confirm a 2048-length vector.
3. Image and image+text embedding via the direct engine
   (`http://localhost:8302/v1/embeddings`, OpenAI `image_url` content parts)
   to confirm multimodal input works before relying on it through LiteLLM.
4. `nvidia-smi` / `free -h` during a chat + embedding request in flight,
   to confirm no OOM or unexpected swap from running both engines together.
5. Confirm the chat engine's boot time and KV cache capacity are unchanged
   with the second engine present (rules out unexpected memory contention).
