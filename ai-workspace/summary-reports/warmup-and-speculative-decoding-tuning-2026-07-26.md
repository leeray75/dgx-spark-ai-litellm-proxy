# Qwen3.6 Warmup Coverage + Speculative Decoding Tuning — Summary Report

**Date:** 2026-07-26
**Branch:** `feature/nemotron-embed-nvfp4` (working tree; not yet committed)
**Base:** current working tree of `docker-compose.qwen3.6.yml` / `litellm-config.yaml`
(these two files already carried an unrelated, uncommitted embedding-model
`max-model-len` 4096→32768 change before this patch — this report covers only
the warmup/compilation and speculative-decoding changes described below, not
that pre-existing change)

---

## Overview

Investigated two performance issues reported against the Qwen3.6-35B-A3B-NVFP4
engine on the DGX Spark (GB10):

1. Triton kernels (`fused_moe_kernel`, `batch_memcpy_kernel`, `eagle_*`,
   `causal_conv1d*`, etc.) JIT-compiling **during live inference** instead of
   during startup warmup, each causing a latency spike (`jit_monitor.py`
   warnings).
2. Speculative decoding (MTP, `num_speculative_tokens=3`) showing a steep
   per-position acceptance drop-off by the 3rd draft position, with average
   draft acceptance in the mid-50s%.

Both are addressed with additive, reversible changes to
`docker-compose.qwen3.6.yml` — no changes to the LiteLLM proxy, Langfuse,
auth, or the other two model stacks (Qwen3-Coder-Next, Nemotron-Super).

---

## Root cause: Issue 1

`docs/architecture.md` and the **v1.3.0 CHANGELOG entry** both already
documented a `vllm-triton-cache` volume as existing, alongside
`vllm-compile-cache` (torch.compile + FlashInfer autotune configs) and
`vllm-flashinfer-cache` (FlashInfer JIT workspace). It was never actually
declared in the `volumes:` block or mounted on `qwen3-6-35b-nvfp4-engine` —
the documentation was aspirational and drifted from reality.

Consequence: Triton's own on-disk JIT cache (`@triton.jit` /
`@triton.autotune`-compiled kernels, default path `/root/.triton/cache`)
lived only inside the container's ephemeral filesystem. `scripts/restart.sh`
recreates the container on every run (`down` + `up`; it never runs
`docker volume rm`), so **the Triton JIT compilation tax was being re-paid on
every restart** — unlike the other two caches, which were already correctly
persisted and load from cache on subsequent boots. This is the most direct
explanation for kernels showing up in `jit_monitor.py` warnings mid-inference
rather than only once, cold, during the very first boot.

Separately, `--max-cudagraph-capture-size 256` only sets a ceiling — it
doesn't guarantee the specific batch-size shapes hit by real traffic are in
the captured/warmed set. With `--max-num-seqs 4` and MTP speculative
verification steps using a per-sequence query length of
`1 + num_speculative_tokens`, the effective decode-batch dimension actually
seen in production ranges up to `4 × (1+3) = 16` — a range vLLM's default
inferred capture-size list apparently doesn't densely cover.

## Root cause: Issue 2

`num_speculative_tokens=3` was set in v1.3.0 (restored in v1.4.1 after a
brief drop to `2` in v1.4.0). That v1.4.0→v1.4.1 change is **not** a clean
prior A/B result for this parameter — it was bundled with a full checkpoint
and quantization-backend revert (unsloth/compressed-tensors →
nvidia/ModelOpt), so no isolated signal exists yet on whether 2 or 3 is
better for this checkpoint. Given the reported acceptance-rate drop-off by
the 3rd position, testing `num_speculative_tokens=2` is reasonable, but
lowers the ceiling in good windows — hence an opt-in toggle rather than a
default change.

---

## Changes

### `docker-compose.qwen3.6.yml` (`qwen3-6-35b-nvfp4-engine` service)

- **Added** `vllm-triton-cache:/root/.triton/cache` volume mount and
  `TRITON_CACHE_DIR: /root/.triton/cache` env var — closes the persistence
  gap described above, matching the existing pattern for the other two
  caches.
- **Added** `--compilation-config '{"cudagraph_capture_sizes":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,24,32,48,64,96,128,192,256]}'`
  — densifies capture/warmup coverage across the 1-16 effective batch range,
  falling back to the existing spacing up to the unchanged 256 ceiling.
  `--max-cudagraph-capture-size 256` is left in place as-is.
- **Added** `QWEN36_NUM_SPECULATIVE_TOKENS` env var indirection:
  `--speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN36_NUM_SPECULATIVE_TOKENS:-3},"moe_backend":"triton"}'`
  — default `3` (**no behavior change**); set to `2` in `.env` to A/B test.
- Synced the same env-var substitution into the commented-out `DEBUG VARIANT`
  command block below, so it doesn't silently reset to a hardcoded `3` if
  ever un-commented.
- Added `vllm-triton-cache:` to the top-level `volumes:` block.

### `.env` / `.env.sample`

- Added `QWEN36_NUM_SPECULATIVE_TOKENS=3` with an explanatory comment.

### `docs/models.md`

- Updated the Qwen3.6 config example to include `TRITON_CACHE_DIR`, the
  `vllm-triton-cache` volume mount, `--compilation-config`, and the
  env-var-driven `--speculative-config`, plus a short prose explanation of
  the capture-size math.

### `docs/architecture.md`

- No change needed — it already (aspirationally) listed `vllm-triton-cache`
  in the volumes table; that claim is now actually true.

### `CHANGELOG.md`

- Added an `[Unreleased]` entry under **Fixed** (the triton-cache
  persistence gap) and **Added** (the widened capture-size list and the
  speculative-tokens A/B toggle), including the benchmarking procedure below.

---

## Impact

- **Startup/restart time:** subsequent restarts should now also skip
  re-compiling Triton kernels from scratch, similar to how the FlashInfer
  autotune cache already shortens second-boot time today. **Not yet measured
  on hardware** — first boot after this change will still populate a fresh
  `vllm-triton-cache` volume; the benefit shows up starting on the *second*
  restart after that.
- **Mid-inference latency spikes:** the widened `cudagraph_capture_sizes`
  list is expected to reduce/eliminate `jit_monitor.py` warnings for shapes
  within the 1-16 effective batch range. Not yet confirmed against live
  traffic.
- **No default behavior change:** `QWEN36_NUM_SPECULATIVE_TOKENS` defaults to
  `3`, identical to the current running config.
- **Risk:** `--compilation-config` is a new flag on an already
  frequently-adjusted, occasionally-fragile command line (per this repo's own
  CHANGELOG history of moe-backend/quantization crash-loops). If it causes a
  startup failure or a much longer compile phase, the fix is simply to delete
  the `--compilation-config` line — everything else (volumes, env vars,
  speculative-config toggle) is independent of it.

---

## Testing Recommendations

1. `docker compose -f docker-compose.qwen3.6.yml config --quiet` — already
   run; confirms the file parses and env-var interpolation resolves as
   expected (`QWEN36_NUM_SPECULATIVE_TOKENS` unset → `3`; overridden → `2`).
2. `./scripts/restart.sh qwen3.6` and confirm the engine reaches `healthy`.
   Watch first-boot logs for the new volume mounting cleanly.
3. After that first boot, restart again and grep logs for FlashInfer/Triton
   cache-hit messages to confirm the Triton cache is now actually being
   reused (mirrors the existing `docs/troubleshooting.md` guidance for the
   FlashInfer cache).
4. Drive representative traffic (single-stream chat + a Cline/Cursor-style
   coding session) and grep for `jit_monitor.py` warnings — they should stop
   appearing for shapes in the 1-16 batch range.
5. **Speculative decoding A/B**: capture baseline
   `docker compose -f docker-compose.qwen3.6.yml logs qwen3-6-35b-nvfp4-engine | grep -E "Avg generation throughput|SpecDecoding metrics"`,
   then set `QWEN36_NUM_SPECULATIVE_TOKENS=2` in `.env`, run
   `docker compose -f docker-compose.qwen3.6.yml up -d --force-recreate qwen3-6-35b-nvfp4-engine`,
   and repeat against comparable traffic before deciding whether to change
   the default.
