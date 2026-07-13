# Patch v1.3.1 — Documentation Update Summary

**Date:** 2026-07-13
**Branch:** `bugfix/qwen3.6-resource-tuning` (working tree; not yet committed)
**Base:** current working tree of `ai-litellm-proxy`

---

## Overview

This patch updates all project documentation to reflect the changes introduced in v1.3.0 (model switch from Qwen3.6-27B-FP8 to Qwen3.6-35B-A3B-NVFP4, embedding model addition, Claude Code alias removal). The existing `patch-v1.3.0-summary.md` is preserved unchanged; this new report documents the documentation updates only.

---

## Files Updated

### 1. `CHANGELOG.md`

- **Added**: New v1.3.0 section with comprehensive change log
  - **Added**: Qwen3.6-35B-A3B-NVFP4 as default model, embedding model, persistent cache volumes, debug command variant
  - **Changed**: vLLM image, gpu-memory-utilization, max-num-seqs, max-num-batched-tokens, tool-call-parser, load-format, speculative-config, LiteLLM dependency, memory limits, restart script
  - **Removed**: Claude Code proxy aliases, vision support, --language-model-only flag
  - **Fixed**: FlashInfer autotune persistent cache, LiteLLM startup timing, FlashInfer version check

### 2. `CLAUDE.md`

- **Updated**: Model name from Qwen3.6-27B-FP8 to Qwen3.6-35B-A3B-NVFP4
- **Updated**: vLLM flags (no --language-model-only, uses qwen3_xml parser, --load-format fastsafetensors)
- **Added**: Embedding model access point (port 8302)
- **Removed**: Claude Code alias references (claude-sonnet-4-6, claude-haiku-4-6)
- **Added**: Note about Claude Code alias removal in model names table
- **Updated**: Model info table with current aliases and vLLM flags

### 3. `README.md`

- **Updated**: Title to reflect Qwen3.6-35B-A3B-NVFP4
- **Updated**: Features section to include multimodal embedding
- **Updated**: Architecture diagram to show embedding engine (port 8302)
- **Updated**: Model references throughout (qwen3.6-35b-a3b instead of qwen3.6-27b)
- **Removed**: Claude Code configuration section (aliases removed)
- **Added**: Embedding API example
- **Updated**: AI Agents table (removed Claude Code entries)
- **Updated**: Access Points table (added Embedding Engine port 8302)

### 4. `docs/models.md`

- **Updated**: Qwen3.6 section — 35B-A3B-NVFP4 specs (not 27B-FP8)
  - Provider changed to NVIDIA
  - Architecture: Hybrid Attention + MoE
  - NVFP4 quantization
  - Text-only (no vision)
  - Updated vLLM flags
- **Added**: New llama-nemotron-embed-vl-1b-v2 section with full specs
- **Updated**: Model comparison table with new columns
- **Updated**: Configuration comparison with current vLLM flags
- **Updated**: Testing examples with new model names

### 5. `docs/agents.md`

- **Updated**: Agent table — removed Claude Code entries
- **Updated**: All model references to qwen3.6-35b-a3b
- **Added**: Note about Claude Code alias removal
- **Updated**: Cursor, Continue, OpenAI SDK examples
- **Updated**: Model reference table with current aliases
- **Updated**: Testing examples with new model names and embedding test

### 6. `docs/architecture.md`

- **Updated**: Architecture diagram to show embedding engine (port 8302)
- **Updated**: Inference Engines table with current images and models
- **Updated**: Port Assignment table (added 8302)
- **Updated**: Model Details section — 35B-A3B-NVFP4 specs
- **Added**: Embedding model details
- **Updated**: Docker Volumes with new cache volumes

### 7. `docs/setup.md`

- **Updated**: Default model name to Qwen3.6-35B-A3B-NVFP4
- **Updated**: Container log commands (qwen3-6-35b-nvfp4-engine)
- **Updated**: Health check commands (added port 8302)
- **Updated**: API test examples with new model names
- **Added**: Embedding model test example
- **Updated**: Boot time estimates (10-60 min first boot, 5-15 min subsequent)
- **Removed**: Claude Code model test section

### 8. `docs/troubleshooting.md`

- **Updated**: Model loading timeout section — 10-60 min first boot, 5-15 min subsequent
- **Updated**: Container names (qwen3-6-35b-nvfp4-engine, nemotron-embed-vl-engine)
- **Updated**: Health check URLs (added port 8302)
- **Added**: Section 7a — FlashInfer Autotune Hangs on First Boot
- **Updated**: Log file commands with new container names
- **Updated**: Diagnostic commands with new container names

---

## Summary of Documentation Changes

| Document | Lines Changed | Primary Updates |
|----------|--------------|-----------------|
| CHANGELOG.md | +48 added | New v1.3.0 entry |
| CLAUDE.md | ~80 modified | Model info, flags, aliases |
| README.md | ~60 modified | Model names, embedding, Claude Code removal |
| docs/models.md | ~200 modified | Full model spec update, new embedder section |
| docs/agents.md | ~40 modified | Model refs, Claude Code removal |
| docs/architecture.md | ~30 modified | Diagram, engine table, volumes |
| docs/setup.md | ~30 modified | Model names, boot times |
| docs/troubleshooting.md | ~50 modified | New FlashInfer section, container names |

---

## Notes

- Existing report `ai-workspace/reports/patch-v1.3.0-summary.md` is preserved unchanged
- All documentation now consistently references Qwen3.6-35B-A3B-NVFP4 as the default model
- Claude Code proxy aliases (claude-sonnet-4-6, claude-haiku-4-6) are documented as removed in v1.3.0
- Embedding model (llama-nemotron-embed-vl-1b-v2) is documented across all relevant files