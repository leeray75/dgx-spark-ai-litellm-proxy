# Qwen3.8-27B-NVFP4 (Unsloth) Stack — Summary Report

**Date:** 2026-08-23
**Branch:** `feat/qwen3.8-27b-nvfp4-stack` (commit `c9f0053`, this report's doc-cleanup pass follows in a second commit)
**Base:** branched from `perf/qwen3.6-warmup-and-spec-decode-tuning` at the point it was pushed to origin

---

## Overview

Added `unsloth/Qwen3.8-27B-NVFP4` as a new, fully-wired stack (`docker-compose.qwen3.8.yml`) and made it the
default model for Cline/Claude Code, replacing `docker-compose.qwen3.6.yml` in that role. Qwen3.6's stack is kept,
completely unmodified, as an explicit rollback path — the goal throughout was "new default, zero regression risk
to the existing known-good config."

Verified end-to-end on real hardware (this DGX Spark), including a real crash and fix during first boot — not
just a config that parses, but one that has actually served a request through the full LiteLLM → vLLM → response
path with correct reasoning-token separation.

---

## Why Qwen3.8 instead of Qwen3.6

User-driven model upgrade decision, not a bug fix. Qwen3.8-27B-NVFP4 (Unsloth) offers:
- Vision support (qwen3.6's checkpoint is text-only)
- A newer, differently-quantized checkpoint (compressed-tensors NVFP4+FP8 vs. NVIDIA ModelOpt NVFP4)
- Same 262K native context, same hybrid Gated-DeltaNet + Gated-Attention architecture family as qwen3.6, so most
  of the hard-won GB10-specific tuning knowledge from qwen3.6's file transfers by analogy

---

## Research method and a source-reliability note

Before writing any flags, three primary sources were checked directly (not paraphrased from memory or from
secondary web results):
1. `unsloth/Qwen3.8-27B-NVFP4`'s `config.json` on Hugging Face — confirmed `architectures:
   ["Qwen3_5ForConditionalGeneration"]`, `model_type: "qwen3_5"`, dense (not MoE), vision encoder present,
   compressed-tensors quantization_config.
2. `unsloth.ai/docs/models/qwen3.8` — official docs page, source for verified sampling defaults and the exact
   MTP speculative-decoding example (`num_speculative_tokens: 2`).
3. A freshly-pulled `vllm/vllm-openai:nightly` image, introspected live (not assumed from release notes) to
   confirm it registers `Qwen3_5ForConditionalGeneration` before any flags were written.

Web search also surfaced several NVIDIA-forum-style threads and small GitHub repos with suspiciously specific
DGX Spark launch commands and benchmark numbers for this exact model (an invented-sounding container image name,
a nonexistent-sounding "DFlash" speculative decoding technique). These were deliberately **not** used as sources —
noted explicitly in `docker-compose.qwen3.8.yml`'s header so future readers don't accidentally treat them as
verified if they go looking.

Where a flag couldn't be verified against a primary source, it was carried over from qwen3.6's proven config **by
architectural analogy** (same "qwen3_5" hybrid model family, same GB10 hardware) and explicitly labeled as such,
following the same rigor the qwen3.6 file already established for itself.

---

## What's new

### `docker-compose.qwen3.8.yml`

Full standalone stack (own Postgres/ClickHouse/Redis/MinIO/Langfuse, mirroring qwen3.6's structure exactly),
serving `unsloth/Qwen3.8-27B-NVFP4` on port 8301 (same port as qwen3.6 — intentional, since only one runs at a
time and reusing the port means nothing external needs to change on model swap).

Key differences from qwen3.6's config, all driven by verified architecture facts:
- **Dense, not MoE** — dropped all MoE-specific flags/env vars (`VLLM_USE_FLASHINFER_MOE_FP4`,
  `VLLM_FP8_MOE_BACKEND`, `--moe-backend marlin`, the `"moe_backend":"triton"` speculative-config key).
- **compressed-tensors quantization** — no `--quantization` flag needed (auto-detected), unlike qwen3.6's
  explicit `--quantization modelopt`.
- **MTP speculative decoding** defaults to `num_speculative_tokens: 2` (Unsloth's own documented value), vs.
  qwen3.6's `3`.
- **`--mamba-ssm-cache-dtype float32`** carried over — same hybrid GDN layer family as qwen3.6.

The file carries an unusually detailed header (longer than usual for a first-cut config) with two sections:
- **PROVENANCE** — three buckets: VERIFIED (checked against primary sources this session), CARRIED BY ANALOGY
  (reused from qwen3.6, not independently confirmed), and NOT CARRIED FORWARD (qwen3.6-specific, doesn't apply).
- **CORRECTIONS HISTORY** — real first-boot findings, written in the same style qwen3.6's file already uses for
  its own 17-item corrections log.

### Wiring (so it's actually usable, not just a compose file)

- `litellm-config.yaml`: new `qwen3.8-27b` route; `qwen3.6-35b-a3b` **kept** (not replaced) for rollback;
  `default_fallbacks` updated to `qwen3.8-27b`.
- `scripts/restart.sh` / `scripts/model-switch.sh`: `qwen3.8` is now the no-arg default; `qwen3.6` remains a
  first-class target. Also fixed a real pre-existing bug in `model-switch.sh`'s `show_status` — it checked for
  container name `qwen3-6-27b-engine`, stale since the 27B→35B-A3B rename, so `status` always reported qwen3.6
  as stopped even when running.
- `.env.sample`: added `QWEN38_NUM_SPECULATIVE_TOKENS` (default `2`), mirroring the existing
  `QWEN36_NUM_SPECULATIVE_TOKENS` pattern.
- **Langfuse**: added a `qwen3.8-27b` pricing entry in the `dgx-spark` project via the Langfuse Models API —
  same per-token rates as qwen3.6 (`$0.000000015` input / `$0.000000035` output), matched exactly to the existing
  `qwen3.6-35b-a3b` entry found via the API. This is runtime state, not a file in this repo.

---

## Real first-boot incident (found, not hypothesized)

`--gpu-memory-utilization 0.4` — the value carried over from qwen3.6 by analogy — crashed on first real boot:

```
ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization`...
```

vLLM's own preceding log line explained the mechanism: CUDA-graph memory profiling made the effective
utilization lower than the nominal value, and left zero room for KV cache after weights (22.13 GiB, confirmed)
and this model's memory-profiling pass — which, unlike qwen3.6's text-only checkpoint, includes profiling the
vision encoder/multimodal path.

**Fix applied**: raised to `0.6`. Recreated the container, confirmed 13.96 GiB KV cache available on the next
boot, then brought up the rest of the stack (LiteLLM had been silently stuck in `Created` state the whole time,
blocked by its `service_healthy` dependency on the crash-looping engine) and verified a real chat completion
through the full path — `reasoning_content` correctly separated from `content` by `--reasoning-parser qwen3`.

Documented in three places, matching how this repo already treats real incidents: the compose file's
CORRECTIONS HISTORY, `CHANGELOG.md`, and a new `docs/troubleshooting.md` entry (§4a) with the exact error text
so a future search for this message finds the explanation.

---

## What's still unverified

Flagged explicitly rather than silently assumed correct:
- **`--tool-call-parser qwen3_xml`** — carried over from qwen3.6 by the same reasoning qwen3.6's own file used
  (general-purpose Qwen3 models use `qwen3_xml`; `qwen3_coder` targets Coder-trained-specific output). Not
  independently confirmed for this checkpoint. **First thing to check** if Cline/Claude Code tool calls fail to
  parse in real use — a plain chat completion (already tested) doesn't exercise this path.
- **`--gpu-memory-utilization 0.6`** — verified working, not a measured optimum. Real KV cache capacity/headroom
  under the full observability stack hasn't been measured the way qwen3.6's file measured its own value across
  several iterations.
- One real positive finding worth calling out: vLLM auto-selected native `FlashInferCutlassNvFp4LinearKernel`
  and `CutlassFP8ScaledMMLinearKernel` kernels for this checkpoint's compressed-tensors scheme, with no Marlin
  fallback needed — different from qwen3.6's ModelOpt-scheme experience, where SM121 forced a Marlin fallback.
  The `VLLM_NVFP4_GEMM_BACKEND=marlin` escape hatch is left commented out in the file rather than deleted, in
  case a different failure mode surfaces later under real load.

---

## Documentation pass

A separate, explicit ask mid-task: audit the rest of the repo's docs for staleness and update the changelog.
Found that six living docs (`README.md`, `CLAUDE.md`, and all five files under `docs/`) still described qwen3.6
as the only/default model, with zero mention of qwen3.8. Updated all of them — tables, config examples, curl
tests, SDK snippets, port/volume listings — to reflect qwen3.8 as default and qwen3.6 as an explicit,
still-fully-documented rollback option, not simply deleted from the docs.

Also fixed two real, pre-existing bugs in `docs/troubleshooting.md`, unrelated to this task but found while
editing that file: a duplicated `### 7b. Langfuse Events Not Showing` header, and a duplicated "If loading
fails" block with near-identical content repeated back to back.

`CHANGELOG.md` got a new `[Unreleased]` entry (Added/Fixed/Known-issue) covering the new stack, the
`gpu-memory-utilization` correction, the `model-switch.sh` bug fix, and a **known-issue** note (not fixed) about
`LITELLM_MASTER_KEY` in `.env` still being the sample placeholder `sk-change-me-in-production` — discovered while
verifying the stack end-to-end via curl, and worth flagging since LiteLLM binds `0.0.0.0:4000` and
`LANGFUSE_HOST` uses a Tailscale hostname, implying the port is meant to be tailnet-reachable. Deliberately not
auto-fixed since `.env` is a secrets file this project's own conventions avoid editing automatically.

---

## Testing performed

1. `docker compose -f docker-compose.qwen3.8.yml config --quiet` — validated syntax before and after every edit.
2. Pulled and live-introspected `vllm/vllm-openai:nightly` to confirm architecture-class support before writing
   any flags (not after — this was a pre-check, not a post-hoc validation).
3. Real boot: crashed on `0.4` utilization (documented above), fixed to `0.6`, confirmed healthy.
4. Real end-to-end request through `http://localhost:4000/v1/chat/completions` with `model: "qwen3.8-27b"` —
   confirmed correct routing, correct `reasoning_content`/`content` separation.
5. Confirmed qwen3.6's pre-existing cache volumes (`vllm-compile-cache`, `vllm-flashinfer-cache`,
   `vllm-triton-cache`) are untouched, so rollback via `./scripts/restart.sh qwen3.6` should hit the FlashInfer
   autotune cache rather than re-tuning from scratch.

## Not yet tested

- A real tool-calling turn through Cline or Claude Code (the actual test of `--tool-call-parser qwen3_xml`).
- Vision input handling (screenshots/diagrams) — the compose file enables it by default, but no multimodal
  request has been sent yet.
- Sustained real coding-session traffic (the kind qwen3.6's file iterated on for its own
  `--max-num-batched-tokens` / `--compilation-config` tuning) — qwen3.8's file deliberately does not carry over
  qwen3.6's custom `--compilation-config` cudagraph capture-size list, since that was tuned for a Triton
  fused-MoE kernel warmup gap that doesn't exist in this dense model; default vLLM capture-size inference is
  used instead pending real traffic showing a need to override it.
