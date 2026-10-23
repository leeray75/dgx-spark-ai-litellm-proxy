# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

An OpenAI-compatible LLM proxy stack running on an **NVIDIA DGX Spark (Blackwell GB10)** workstation with 128GB unified memory. It wraps local vLLM inference engines behind a LiteLLM proxy with full Langfuse v3 observability (tracing, cost tracking, analytics).

The selectable chat models cannot run simultaneously — only one chat inference engine is active at a time due to GPU memory constraints. The `nemotron-3-embed-1b-nvfp4` embedding engine is small enough (~1.14B params) to run alongside whichever chat engine is active; it's wired into `docker-compose.qwen3.8-flash-next.yml`, `docker-compose.qwen3.8.yml` and `docker-compose.qwen3.6.yml`.

**`docker-compose.qwen3.8-flash-next.yml` is the default/primary stack as of 2026-10-22** (explicit user decision U-4, `docs/specs/qwen38-flash-next-stack/`). Checkpoint is `nvidia/Qwen3.8-Flash-Next-FP4-Local` (125B-parameter MoE, ~6B active, vision-capable, 262K context), served by the community `eugr/spark-vllm-b12x` image because upstream vLLM cannot load its NVFP4 scale-factor format. Measured on this box: ~38 tok/s median in vLLM's own log during the tests (about 1.8-2.3x the 27B's ~21 tok/s live median), 45-48 tok/s in single-request tests. The stack bundles Langfuse, LiteLLM, the embedding engine **and its own agentgateway** in one file. `docker-compose.qwen3.8.yml` (27B) is now the **rollback** stack and `docker-compose.qwen3.6.yml` the retired rollback: the `qwen3.8-27b` / `qwen3.8-27b-nothink` aliases were removed from `litellm-config.yaml` and `agentgateway/config.yaml` (kept as commented ROLLBACK blocks), and `default_fallbacks` is `["qwen3.8-flash-next"]` only. `local-image-gen-mcp` stays **off** while Flash-Next runs (it runs at `--gpu-memory-utilization 0.75`; image generation is only available on the 27B stack).

*History:* `docker-compose.qwen3.8.yml` was the default/primary stack again from 2026-09-09 (explicit user decision, reverting
the 2026-08-24 fallback to qwen3.6). Checkpoint is `nvidia/Qwen3.8-27B-NVFP4`, swapped in from the previously-tried
`Inferact/Qwen3.8-27B-NVFP4`. Reason: NVIDIA's own published accuracy benchmarks show qwen3.8 ahead of qwen3.6 on
every overlapping metric — GPQA Diamond +3.2, AA-LCR +11.4, SciCode +7.8, IFBench +16.1 (see `docs/models.md` for
the full comparison). A real live test (6-hour window, 221 active samples) confirmed sustained throughput of
20.4 tok/s median (20.26 mean — steady, not bursty) — roughly 2x slower than qwen3.6's own live throughput
(informally ~40-45 tok/s, not yet measured with the same rigor; qwen3.6's oft-cited ~83-84 tok/s is a clean
synthetic single-request number, not representative of live usage). The user judged qwen3.8's accuracy gains worth
this confirmed ~2x throughput cost — see `docker-compose.qwen3.8.yml`'s RESULT section for the full investigation.
`docker-compose.qwen3.6.yml` is kept, fully wired, unmodified, and buildable as the rollback path if that changes —
not deleted, just not the default.

## Stack Management

### Starting the stack

```bash
# Default model (Qwen3.8-Flash-Next-FP4-Local) — recommended. ALWAYS through the wrapper:
# every compose command on this file needs AGW_LANGFUSE_BASIC_AUTH, which the
# wrapper derives from .env (and refuses to run if the Langfuse keys are empty).
./scripts/flash-next-compose.sh up -d
./scripts/flash-next-compose.sh ps          # also: logs -f qwen3-8-flash-next-fp4-engine | down | config --quiet

# Qwen3.8-27B-NVFP4 (rollback — restore the ROLLBACK blocks in litellm-config.yaml
# and agentgateway/config.yaml first; see "Switching back to the 27B" below)
docker compose -f docker-compose.qwen3.8.yml up -d

# Qwen3.6-35B-A3B-NVFP4 (retired rollback — see note above)
docker compose -f docker-compose.qwen3.6.yml up -d

# Qwen3-Coder-Next-FP8 (80B MoE, coding-focused)
docker compose up -d

# Nemotron-3-Super-120B (general reasoning)
docker compose -f docker-compose.nemotron.yml up -d
```

### Full restart with cache clearing (the "Ritual")

```bash
./scripts/restart.sh              # restarts Qwen3.8-Flash-Next (default)
./scripts/restart.sh flash        # same (aliases: qwen3.8-flash, flash-next)
./scripts/restart.sh qwen3.8      # Qwen3.8-27B-NVFP4 (rollback — prints a warning about the ROLLBACK blocks)
./scripts/restart.sh qwen3.6      # Qwen3.6-35B-A3B-NVFP4 (retired rollback)
./scripts/restart.sh qwen         # Qwen3-Coder-Next-FP8
./scripts/restart.sh nemotron     # Nemotron-3-Super-120B
./scripts/restart.sh status       # show container health
./scripts/restart.sh clean        # stop all containers
```

The restart script drops system caches (`sync; echo 3 > /proc/sys/vm/drop_caches`) to free unified memory before starting a new engine. This requires `sudo`.

**Flash-Next needs the cache drop:** vLLM refuses to start when free memory is below `gpu-memory-utilization × total` (0.75 × 121.7 GiB ≈ 91.3 GiB), and on GB10 CUDA's free figure tracks `MemFree`, not `MemAvailable`. After a large download or heavy file I/O the page cache can leave `MemFree` at a few GiB even with `MemAvailable` high (2026-10-22: 9.7 GiB after shutting the 27B down). `restart.sh flash` stops `local-image-gen-mcp`, drops caches and warns if `MemFree` is still under 105 GiB; `model-switch.sh flash` has no cache drop, so it aborts with the exact `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` command when `MemFree` is under 105 GiB (it can only judge this after the old stack is stopped when an engine is running; with nothing running it aborts before stopping anything). Its wait limit is 3600 s (first boot took up to 18 m 39 s); other targets keep 600 s.

`model-switch.sh flash` has **two memory gates**: (1) a **pre-stop** page-cache gate: if `Cached+Buffers` ≥ 10 GiB (121.7 GiB total − 105 GiB − ~5 GiB baseline ≈ 11.7, rounded down) it aborts with exit 2 *before stopping anything* and prints the sudo drop command (dropping caches while the old stack runs is harmless); (2) a **post-stop** `MemFree` gate: if `MemFree` is still under 105 GiB after the old stack is stopped it aborts with exit 3 *before starting* — at that point the previous stack is **already stopped and nothing is serving**; the message prints the sudo drop command and the exact re-run command (`./scripts/restart.sh flash` drops caches itself). After `stop_all` both scripts verify that no engine container or `agentgateway` is still running (a stale standalone agentgateway clashes on the container name) and abort before `up` if one is. `DRY_RUN` counts any non-empty value other than `0` (1, true, yes …).

**Dry run:** `DRY_RUN=1 ./scripts/restart.sh [target]` / `DRY_RUN=1 ./scripts/model-switch.sh <target>` print every mutating command (`docker compose … up/down`, `docker stop`, `sudo`, `agentgateway-up.sh`) instead of running it; read-only checks still run.

**What the switch scripts do around the new target:** `stop_all` also brings down the Flash-Next stack (through the wrapper) and the standalone agentgateway project (`docker-compose.agentgateway.yml`), so switching away no longer silently leaves or removes the wrong agentgateway. Switching to the 27B (`qwen3.8`) afterwards restores `local-image-gen-mcp` with its compose `up -d` (not `docker start`: the `ai-bridge` network is recreated when a stack goes down, and a stopped image-gen container keeps the stale one) and the standalone agentgateway via `./scripts/agentgateway-up.sh`.

**Switching back to the 27B:** the 27B aliases are inactive. Before `restart.sh qwen3.8` / `model-switch.sh qwen3.8`, uncomment the ROLLBACK blocks in `litellm-config.yaml` (and set `default_fallbacks` to `["qwen3.8-27b"]`) and `agentgateway/config.yaml`, then re-run `./scripts/agentgateway-sync-costs.py` so the cost overlay prices `vllm-qwen38/qwen3.8-27b`. The scripts print this warning and never edit configs.

### Switching models

```bash
./scripts/model-switch.sh flash     # switch without full restart (default; aliases: qwen3.8-flash, flash-next)
./scripts/model-switch.sh qwen3.8   # Qwen3.8-27B-NVFP4 rollback
./scripts/model-switch.sh qwen3.6   # retired rollback
./scripts/model-switch.sh qwen
./scripts/model-switch.sh nemotron
./scripts/model-switch.sh status
```

**Note:** `model-switch.sh` skips the system cache drop; use `restart.sh` when memory pressure is suspected.

### Checking status

```bash
docker compose ps
docker compose logs -f <service>   # e.g. litellm, qwen3-6-35b-nvfp4-engine
./scripts/flash-next-compose.sh ps # Flash-Next stack (plain `docker compose` needs AGW_LANGFUSE_BASIC_AUTH)
```

## Configuration Files

| File | Purpose |
|------|---------|
| `litellm-config.yaml` | LiteLLM model routing, Redis cache, Langfuse callbacks (native SDK) |
| `docker-compose.yml` | Qwen3-Coder-Next-FP8 stack |
| `docker-compose.qwen3.8-flash-next.yml` | Qwen3.8-Flash-Next-FP4-Local stack (**default** since 2026-10-22; includes its own agentgateway). Run it via `scripts/flash-next-compose.sh` |
| `scripts/flash-next-compose.sh` | Wrapper for the Flash-Next compose file: sources `.env`, derives `AGW_LANGFUSE_BASIC_AUTH` (refuses if the Langfuse keys are empty), `mkdir -p agentgateway/data`, then `exec docker compose -f docker-compose.qwen3.8-flash-next.yml "$@"` |
| `scripts/check-engine-image.sh` | Notify-only check for newer builds of every digest-pinned image in `docker-compose*.yml` (compares the pin with the image's `:latest`; `TRACK_TAG` overrides). Run by the systemd **user** timer `engine-image-check.timer` (~3 min after boot + daily; units in `~/.config/systemd/user/`). A newer build writes `~/.local/state/engine-image-check/notice`, which a marked block at the end of `~/.bashrc` prints in every interactive shell. `show` / `dismiss` subcommands; history in `check.log` beside the notice. Never pulls or edits anything — adopting a build is a manual digest edit + `flash-next-compose.sh up -d` |
| `docker-compose.qwen3.8.yml` | Qwen3.8-27B-NVFP4 stack (rollback since 2026-10-22 — see note above) |
| `scripts/eval-agentic-tasks.py` + `scripts/eval-tasks/` | Agentic coding evaluation through agentgateway: 5 repository tasks (each `TASK.md`, `workspace/`, `hidden_tests/`, `reference/`), deterministic tools with **no shell**, code executed only in the `eval-sandbox:py312` image (`scripts/eval-tasks/sandbox/Dockerfile`, `--network none`, read-only root). See "Evaluating models" below |
| `scripts/eval-hard-problems.py` | Single-prompt hard-problem set (no tools); saves after every answer, `--resume`, `--rerun-truncated`; default 32,768 output tokens |
| `docker-compose.qwen3.6.yml` | Qwen3.6-35B-A3B-NVFP4 stack (retired rollback) |
| `docker-compose.nemotron.yml` | Nemotron-3-Super-120B stack |
| `docker-compose.agentgateway.yml` + `agentgateway/config.yaml` | agentgateway **trial**, runs alongside LiteLLM. Under the Flash-Next stack it is part of that compose file (container `agentgateway`); the standalone `docker-compose.agentgateway.yml` (own compose project `ai-litellm-agentgateway`, joins `ai-litellm-proxy_ai-bridge`) is for the 27B/qwen3.6 stacks — both use container name `agentgateway`, so never run both. Start the standalone one with `./scripts/agentgateway-up.sh` (derives the Langfuse OTLP auth header from `.env`). Routes: provider `vllm-qwen38-flash` → `qwen3.8-flash-next` and `qwen3.8-flash-next-nothink`; the 27B provider/models are a commented ROLLBACK block. Traces go to Langfuse under environment `agentgateway-trial`. Cost-dashboard prices come from `agentgateway/costs/langfuse-overlay.json`, generated from the Langfuse `dgx-spark` project's model prices by `./scripts/agentgateway-sync-costs.py` — re-run it after changing prices in Langfuse (agentgateway reloads the file automatically) |
| `.env` | All secrets and credentials (copy from `.env.sample`) |
| `clickhouse-config.xml` | ClickHouse memory cap and server settings |
| `postgres-init/01_create_litellm_db.sql` | Creates the separate `litellm` database on first start |

## Architecture

```
Clients → LiteLLM Proxy (4000) → vLLM Engine (8301/8300/8200)
                ↓
          Langfuse SDK → Langfuse Worker → ClickHouse + MinIO
                                 ↑
                   Redis (event queue + exact-match prompt cache)
                   PostgreSQL (two isolated DBs: langfuse + litellm)
```

- **LiteLLM** (`litellm-config.yaml`): Routes by model name alias, manages virtual keys and spend tracking via PostgreSQL `litellm` DB, caches exact-match prompts in Redis (1hr TTL).
- **vLLM engines**: Each compose file configures one engine with GPU-memory-tuned parameters. vLLM prefix caching handles partial prompt reuse; LiteLLM Redis cache short-circuits 100%-identical requests before they reach vLLM.
- **`docker-compose.qwen3.8.yml`'s PROVENANCE header** (top of that file) documents exactly which vLLM flags for Qwen3.8-27B-NVFP4 are verified against primary sources vs. carried over by analogy from the qwen3.6 file vs. explicitly unverified — read it before changing that file's flags, and before trusting any web search result about this specific model (some surfaced during initial research looked fabricated/unverifiable and were deliberately not used).
- **Langfuse v3**: Two-container split — `langfuse-web` (UI + ingestion API) and `langfuse-worker` (async writer). Worker reads events from Redis queue and writes to ClickHouse (traces) and MinIO (event payloads).
- **PostgreSQL**: Single shared instance with two isolated databases. `TZ=UTC` is required — non-UTC causes incorrect Langfuse query results.

## Cross-File Dependencies

These are relationships that require reading multiple files to understand and are easy to break silently:

**`litellm-config.yaml` is shared across all the compose stacks.** Every compose file mounts it at `/app/config.yaml`. Changing model aliases or routing there affects whichever stack is currently running. Since 2026-10-22 the `qwen3.8-27b` / `qwen3.8-27b-nothink` entries exist only as a commented ROLLBACK block (same in `agentgateway/config.yaml`): running the 27B stack needs them uncommented, and `default_fallbacks` set back to `["qwen3.8-27b"]`.

**Three-way name binding for each model:** The vLLM `--served-model-name` flag sets the model name the engine advertises → `litellm-config.yaml` must reference it as `hosted_vllm/<served-model-name>` → the `api_base` must point to the correct Docker service name. If you add a new engine or rename a model, all three must stay in sync.

**Langfuse callback is the native SDK (`success_callback: ["langfuse"]`), not `langfuse_otel`** (since 2026-10-09). `langfuse_otel` logs any request carrying a `tools` list as a TOOL observation with no model name, so agent traffic got $0 cost — see CHANGELOG. The native callback sends to `LANGFUSE_HOST` (the Tailscale hostname, reachable from inside the container); `LANGFUSE_OTEL_HOST: http://langfuse:3000` (the container's `container_name: langfuse`, not the service name `langfuse-web`) is only used if `langfuse_otel` is re-enabled.

**`scripts/super_v3_reasoning_parser.py`** is mounted into the Nemotron container as `/app/super_v3_reasoning_parser.py` and activated via `--reasoning-parser-plugin`. **`scripts/qwen3_reasoning_parser.py`** is vestigial — it is not mounted in any compose file; the built-in `--reasoning-parser qwen3` flag is used instead.

**Nemotron stack (`docker-compose.nemotron.yml`) includes Qdrant** (ports 6333/6334) as an optional vector database — this service is absent from the other two compose files.

## Startup Timing and Cache Behavior

**Flash-Next (default):** the first boot (2026-10-22, b12x JIT compile with 0 cached entries, checkpoint already downloaded) took **≤ 18 m 39 s** from `up -d` to healthy (the `init engine (profile, create kv cache, warmup model)` step alone took 749 s); the compose healthcheck has `start_period` 3600 s and the switch scripts wait up to 3600 s. Later boots should be faster if the `vllm-*`/`b12x` named-volume caches persist (not yet measured). The first boot also needs `MemFree` ≥ ~105 GiB (see the cache-drop note under "Full restart"), and downloading the 96 GiB checkpoint fills the page cache, so drop caches after it.

### Qwen3.8 (27B) / Qwen3.6, rollback

First boot on a nightly image runs a FlashInfer fp8_gemm autotuning phase. On a cache-miss boot this takes ~10-35 minutes; the results persist in the `vllm-qwen38-compile-cache` (or `vllm-compile-cache` for the qwen3.6 rollback stack) volume at `/root/.cache/vllm`. Subsequent boots load the cache and complete in ~5-15 minutes total. This timing is carried over from qwen3.6's measured history — not yet independently confirmed for the qwen3.8 stack.

**Cache invalidation:** Changing `--gpu-memory-utilization`, `--max-num-batched-tokens`, `--max-model-len`, or the image version generates a new cache-key hash and forces a full re-tune on the next boot.

Verify cache behavior in logs:
```bash
docker compose -f docker-compose.qwen3.8.yml logs qwen3-8-27b-nvfp4-engine | grep -i "flashinfer.*cache"
```

If you see the cache load message on second boot, the persistent cache is working. If you see repeated "Tuning fp8_gemm" entries, the running nightly is too old (must be built after 2026-05-31, PR #44071).

## vLLM Image Versions

Each compose file pins a different vLLM image — do not swap these:

| Compose file | vLLM image | Notes |
|---|---|---|
| `docker-compose.qwen3.8-flash-next.yml` | `eugr/spark-vllm-b12x@sha256:03a95654…` (arm64, CUDA 13.0.2, created 2026-10-15) | Pinned by digest (= `:latest` on 2026-10-22). Required: upstream vLLM cannot load this checkpoint's `csf` NVFP4 scale encoding. The embedding engine in the same file still uses `vllm/vllm-openai:nightly` |
| `docker-compose.qwen3.6.yml` | `vllm/vllm-openai:nightly` (ARM64) | Currently digest `sha256:95bed119…` (vLLM `0.26.1rc1.dev1102+ge9d1398d9`) — see the pinning warning below |
| `docker-compose.qwen3.8.yml` | `vllm/vllm-openai:nightly` (ARM64) | Same digest as above — confirmed via live registry introspection to register `Qwen3_5ForConditionalGeneration`, the architecture class this checkpoint's config.json declares |
| `docker-compose.yml` | `vllm/vllm-openai:v0.19.1-cu130` | Pinned for GDN/Mamba stability |
| `docker-compose.nemotron.yml` | `vllm/vllm-openai:v0.18.1-cu130` | Nemotron requires v0.18.1, not v0.19.1 |

> **⚠️ Tag-pinning warning (2026-08-24 incident):** `docker-compose.qwen3.6.yml` and `docker-compose.qwen3.8.yml`
> both reference the **mutable** `:nightly` tag, not a pinned digest. A `docker pull vllm/vllm-openai:nightly` run
> to investigate qwen3.8's throughput silently upgraded qwen3.6's engine too on its next restart — to a build it
> had never been validated against — and reproduced the exact same `gpu_memory_utilization` OOM qwen3.8 hit
> (fixed the same way: `0.4` → `0.6` on both files). **Before running `docker pull vllm/vllm-openai:nightly`
> again, know that it affects both stacks simultaneously.** Neither file has a recorded pinned digest yet
> (`docker-compose.qwen3.6.yml`'s header still has an unfilled "Pinned working digest:" placeholder) — pinning
> both to the current known-working digest is the real fix, not yet done.

## Model Names and Aliases

### In LiteLLM (via API on port 4000)

| Alias | Backend | Purpose |
|-------|---------|---------|
| `qwen3.8-flash-next` | Qwen3.8-Flash-Next-FP4-Local (nvidia) | **Default.** Vision-capable, direct access (262K context). Electricity prices re-derived from agent traffic 2026-10-22 (input 3.19e-11, output 8.69e-8 per token) |
| `qwen3.8-flash-next-nothink` | Same engine | `enable_thinking: false` via `extra_body` — no reasoning pass (the chat template honors it); for subagents / template filling (`GOOSE_SUBAGENT_MODEL`). Replaces `qwen3.8-27b-nothink` |
| `claude-qwen3.8-flash-next` | Same engine | Claude Code discovery alias: `/model` only lists IDs matching `/^(claude\|anthropic)/i`, so the model shows up only under this name. Explicit `model_name`, so it wins over the `anthropic/*` wildcard. Verified via `POST /v1/messages` |
| `qwen3.8-27b`, `qwen3.8-27b-nothink` | Qwen3.8-27B-NVFP4 | **Removed 2026-10-22** (kept as a commented ROLLBACK block in `litellm-config.yaml` / `agentgateway/config.yaml`); clients must use the Flash-Next names. **LiteLLM does not 404 on them** (nor on any unknown name): `default_fallbacks` serves them with Flash-Next, thinking ON, echoing the requested name, so `qwen3.8-27b-nothink` callers silently lose no-think (use `qwen3.8-flash-next-nothink`); agentgateway returns 404 `model_not_found`. Intended, user decision U-5 |
| `qwen3.6-35b-a3b` | Qwen3.6-35B-A3B-NVFP4 | Retired rollback. Vision-capable — only reachable if `docker-compose.qwen3.6.yml` is running; see note above |
| `qwen3-coder-next` | Qwen3-Coder-Next-FP8 | 80B MoE coder (262K context) |
| `nemotron-super` | Nemotron-3-Super-120B | General reasoning (262K context) |
| `nemotron-3-embed-1b-nvfp4` | Nemotron-3-Embed-1B-NVFP4 | Text-only embedding, 2048-dim, NVFP4 (`/v1/embeddings`); requires manual `query:`/`passage:` input prefix |

> **Note:** The `anthropic/*` wildcard passthrough (added v1.4.0) routes all Claude model IDs — including future releases and any alias Claude Code/Desktop introduces — directly to Anthropic's real API via the proxy. A `default_fallbacks` entry sends failed requests to the local default engine (`qwen3.8-flash-next`, Flash-Next only since 2026-10-22). This replaces the older approach of using individual `claude-sonnet-4-6` / `claude-haiku-4-6` proxy aliases (removed in v1.3.0).

## Key vLLM Flags by Model

- **Qwen3.8-Flash-Next** (default since 2026-10-22; full provenance in `docker-compose.qwen3.8-flash-next.yml`, facts in `docs/specs/qwen38-flash-next-stack/research.md`): NVIDIA's DGX Spark recipe verbatim apart from the deviations listed in that file's header — `--quantization modelopt_mixed`, `--load-format b12x`, `--linear-backend b12x`, `--moe-backend b12x`, `--gdn-decode-kernel b12x`, `--mamba-cache-mode align`, `--kv-cache-dtype fp8`, `--block-size 16`, `--speculative-config '{"method":"mtp","num_speculative_tokens":4}'`, `--no-enable-flashinfer-autotune`, `--reasoning-parser qwen3`, `--tool-call-parser qwen3_xml` (works: arrives as proper OpenAI `tool_calls`, streaming included), `--max-num-seqs 8`, `--max-num-batched-tokens 4096`, `--mm-encoder-tp-mode data`, `--gpu-memory-utilization 0.75` (lowered from the recipe's 0.80 on 2026-10-22 to keep RAM under 120 GB; env-overridable via `QWEN38_FLASH_GPU_MEMORY_UTILIZATION`; changing it invalidates the compile cache), plus the recipe env vars (`VLLM_PLE_TABLE_MEMORY=disk`, `B12X_DISK_BACKEND=io_uring`, …) and `seccomp=unconfined`/`apparmor=unconfined` (whether `seccomp=unconfined` is really required is untested). Measured at boot (0.75, 2026-10-22 23:11 UTC): weights 70.32 GiB, KV cache 16.7 GiB = 888,648 tokens, 3.39x concurrency for 262,144-token requests; host RAM in use 108.4 GB, available 20.8 GiB, boot ~5 min with warm caches (at 0.80 it was KV 28–29 GiB ≈ 1.5M tokens, RAM ~122.8 GB). `tool_call_parser` is `qwen3_xml`, not the 27B's `qwen3_coder`. `restart: unless-stopped` (since 2026-10-22, user decision; was `"no"`) — it comes back by itself after a host reboot, where MemFree (~99 GiB) clears vLLM's ~97.4 GiB check without a cache drop. Before a driver/kernel update + reboot, the dgx-safe-update checklist flags it; `docker update --restart=no qwen3-8-flash-next-fp4-engine` if you want it to stay down that time.
- **Qwen3.8 27B** (rollback since 2026-10-22; was the default — checkpoint swapped `Inferact/Qwen3.8-27B-NVFP4` → `nvidia/Qwen3.8-27B-NVFP4` 2026-09-09; see note above): no `--quantization` flag (auto-detected — the checkpoint's config.json uses a compressed-tensors-shaped schema, not ModelOpt's own schema, despite the model card's "quantized with Model Optimizer" framing); `--reasoning-parser qwen3`; `--tool-call-parser qwen3_coder` (per the official model card recipe, **unverified** against a real tool-calling session on this specific checkpoint); `--kv-cache-dtype fp8_e4m3`; `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'` (no `moe_backend` key — dense, not MoE); `--gpu-memory-utilization 0.6`, `--max-num-seqs 4`, `--max-num-batched-tokens 8192` (GB10-appropriate values, not the official recipe's GB300-scaled 0.85/32/32768 — this box's own history shows 0.85 causes real swap); `--mm-encoder-tp-mode data` (vision encoder); no `--linear-backend marlin` — native kernel selection (`FlashInferFP8ScaledMMLinearKernel`, `FlashInferCutlassNvFp4LinearKernel`) confirmed clean on this checkpoint, not forced to Marlin given `lm_head` is itself NVFP4-quantized here.
  - **SIMPLIFICATION PASS (2026-09-09/10):** following a report of excessive agentic self-verification (26 tool-call steps on one OpenCode subtask vs. 7-13 on others in the same run), dropped `--override-generation-config` and `--default-chat-template-kwargs`, matching NVIDIA's official command exactly on this axis. **This did NOT change actual sampling behavior** — the checkpoint's own `generation_config.json` ships `temperature: 1.0, top_k: 20, top_p: 0.95`, identical to what was removed, so this confirmed the vendor default rather than fixing a misconfiguration. `enable_thinking` is still on by default (never explicitly set either way) — the small-`max_tokens`-returns-empty behavior (confirmed: a 20-token request returned zero content, all reasoning) is unchanged. Also dropped as unneeded cruft: `--load-format fastsafetensors`, `--attention-backend flashinfer`, `--async-scheduling`, `--enable-prefix-caching`, `--uvicorn-log-level warning`. Kept despite being absent from the official command (each tied to a real incident or correctness need): `--trust-remote-code`, `--mamba-ssm-cache-dtype float32`, `--speculative-config` (MTP), and the GB10-safe memory values above.
  - Measured throughput: ~24.3-24.9 tok/s synthetic single-request benchmark (pre-simplification). Real live-usage numbers, two windows: 6-hour/221-sample window (pre-simplification) — 20.4 tok/s median (20.26 mean, steady); post-simplification/421-sample window — **22.8 tok/s median (26.41 mean, mean now above median)**, a real ~12% median improvement most likely from freed KV cache headroom (1,309,255 tokens / 4.99x concurrency, up from 746,890 / 2.85x, at the same `--gpu-memory-utilization 0.6`) letting more requests batch during busy periods — not from any sampling change, since sampling didn't actually change. GPU signature during generation: 96% utilization but only ~37-38W power draw — memory-bandwidth-bound, consistent with the dense-vs-MoE architectural theory. NVIDIA's own published accuracy benchmarks favor this checkpoint over qwen3.6 on every overlapping metric (GPQA Diamond +3.2, AA-LCR +11.4, SciCode +7.8, IFBench +16.1). See `docker-compose.qwen3.8.yml`'s CHECKPOINT SWAP/RESULT/SIMPLIFICATION PASS notes for the full investigation.
- **Qwen3.6** (rollback): `--reasoning-parser qwen3` required (prevents thinking tokens leaking); `--speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'`; `--gpu-memory-utilization 0.5`, `--max-num-seqs 8` (aligned to the official vLLM recipe 2026-08-27 — see `docker-compose.qwen3.6.yml` corrections item 20; measured 12.45 GiB KV cache at boot); `--tool-call-parser qwen3_xml` (this flag flip-flopped repeatedly across items 11/16/17/19/20 — settled 2026-09-02 by directly diffing a freshly-pasted copy of the official recipes.vllm.ai DGX-Spark command against this file, exact match on every flag, see corrections item 21; the `qwen3_coder` value real-tool-call-verified on 2026-08-27, item 19, is no longer what's running); `--load-format fastsafetensors`; `--default-chat-template-kwargs '{"preserve_thinking":true,"enable_thinking":false}'` (2026-09-02, item 21 — the "thinking" reasoning pass is disabled by default because it was found to consume 72-91% of a constrained `max_tokens` budget on long, multi-requirement tickets, truncating later requirements before the model ever acted on them; verified directly against the engine and, end-to-end, via a real Cline CLI run against a cloned open-source repo — see the linked summary report). Measured throughput: informally ~40-45 tok/s under real/live usage (not yet measured with the same 6-hour/sampled rigor as qwen3.8's number above); ~83-84 tok/s only in a clean synthetic single-request benchmark.
  - `--max-num-batched-tokens 8192` matches the official DGX Spark spec but reduces Cline large-context ingestion throughput vs. the previous value of `262144`. If Cline latency regresses noticeably under real traffic, raising this back toward `262144` is the first lever to pull.
  - `VLLM_NVFP4_GEMM_BACKEND=marlin` env var (not `--linear-backend marlin` — that flag crashes startup on this model due to FP8-quantized GDN attention projection layers).
- **Qwen3-Coder-Next**: `--mamba-ssm-cache-dtype float32` required for GDN/SSM layer stability; `--max-cudagraph-capture-size 128` prevents GDN Mamba OOM
- **Nemotron**: Uses custom reasoning parser plugin at `scripts/super_v3_reasoning_parser.py`; requires vLLM `v0.18.1` (not `v0.19.1`)

## Memory Budget

All containers share the GB10's 128GB unified memory pool (no separate VRAM). **Flash-Next (default) runs at `--gpu-memory-utilization 0.75`** (~91 GiB of 121.7; 0.80 until 2026-10-22, which put host RAM at ~122.8 GB; model loading took 70.32 GiB, the n-gram PLE table stays on NVMe) with `local-image-gen-mcp` **stopped** (it holds ~18 GB and never frees it; user decision U-3). At 0.75 host RAM is ~108.4 GB in use with ~21 GiB available when healthy (at 0.80 it was 6.8–8.2 GiB available, which is why it was lowered); not sampled under heavy load, so still watch `MemAvailable` before starting anything else large. The 27B (rollback) runs at 0.54 (older notes below say 0.6, the previous value); qwen3.6 (retired rollback) at 0.5. Either leaves enough for the observability stack (Postgres 768M, ClickHouse 3G, Redis 512MB app + 640M container, MinIO 512M, Langfuse web 1.5G, Langfuse worker 1.5G, LiteLLM 1G). Measured KV cache headroom at boot: qwen3.8 ~26.48 GiB / 1,309,255 tokens / 4.99x concurrency (post-simplification-pass, 2026-09-10 — up from 746,890 tokens / 2.85x pre-pass, same utilization value), qwen3.6 ~12.45 GiB.

`langfuse-web` and `langfuse-worker` both use `NODE_OPTIONS: --max-old-space-size=1024` to cap V8's heap at 1024MB. Without this explicit cap, V8 ignores the Docker memory cgroup limit and OOMs under real trace-ingestion load — idle `docker stats` readings are not a reliable proxy for load-time memory usage.

## Evaluating models

```bash
python3 scripts/eval-agentic-tasks.py --self-test           # validate tasks: hidden tests fail on the start code, pass on reference/ (no model calls)
python3 scripts/eval-agentic-tasks.py --repeats 1           # quick pass, ~30-45 min (default --repeats 3, ~1.5-3 h)
python3 scripts/eval-agentic-tasks.py --resume <json>       # continue a stopped run (per attempt)
```

- Results: `ai-workspace/reports/agentic-eval-<model>-<UTC>.json` (rewritten after every attempt; `meta.per_task` has pass rate and score spread) plus each attempt's final workspace in the folder of the same name. The first run (2026-10-23, 1 attempt per task) scored 78/85 hidden tests and was graded by a subagent (`...-20261023-grading.md`).
- Tools the model gets: `list_files`, `read_file`, `outline`, `grep`, `write_file`, `edit_file` (echoes the edit + syntax check), `delete_file`, `show_diff`, `check_syntax`, `run_tests`, `run_python`, `finish` (refused once if files changed since the last passing full run). Every result carries "turn N/M"; context is compacted past 48k prompt tokens.
- Grading: hidden tests on the final workspace and on the last passing checkpoint, plus mechanical checks (scratch files, removed original tests, original tests on the final code, diff size vs. reference, first green turn, tool error rate). The harness sends no sampling parameters; `meta.sampling` records the engine's defaults.
- Adding a task: create `scripts/eval-tasks/<id>/` with the four parts, then run `--self-test --only <id>`.

## Access Points

| Service | URL |
|---------|-----|
| LiteLLM API | http://localhost:4000/v1 |
| LiteLLM UI | http://localhost:4000/ui |
| Langfuse UI | http://localhost:3000 |
| Qwen3.8-Flash-Next Engine (direct, default) | http://localhost:8301/v1 |
| Qwen3.8-27B Engine (direct, rollback — same port, mutually exclusive) | http://localhost:8301/v1 |
| Qwen3.6 Engine (direct, retired rollback — same port, mutually exclusive) | http://localhost:8301/v1 |
| Embedding Engine (direct, Qwen3.6/3.8 stacks only) | http://localhost:8302/v1 |
| Qwen3-Coder Engine (direct) | http://localhost:8300/v1 |
| Nemotron Engine (direct) | http://localhost:8200/v1 |
| MinIO Console | http://localhost:9091 |
| agentgateway API (trial, same key as LiteLLM) | http://localhost:4100/v1 |
| agentgateway UI (trial, local only, no auth) | http://localhost:4101/ui |
| agentgateway MCP (trial, same key; fronts `local-image-gen-mcp`) | http://localhost:4100/mcp/image-gen |

## Environment Setup

```bash
cp .env.sample .env
# Fill in all values — required keys:
# HF_TOKEN, LITELLM_MASTER_KEY, POSTGRES_PASSWORD, CLICKHOUSE_PASSWORD,
# MINIO_ROOT_PASSWORD, REDIS_AUTH, LANGFUSE_ENCRYPTION_KEY,
# LANGFUSE_SALT, NEXTAUTH_SECRET, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
```

`LITELLM_SALT_KEY` encrypts virtual key data at rest — never change it after virtual keys have been created.

## Testing the API

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "qwen3.8-flash-next", "messages": [{"role": "user", "content": "Hello"}]}'
```

```bash
curl http://localhost:4000/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "nemotron-3-embed-1b-nvfp4", "input": "query: Hello"}'
```

Engine health check (skip LiteLLM):
```bash
curl http://localhost:8301/health   # Flash-Next (default), Qwen3.8-27B or Qwen3.6 — whichever stack is up
curl http://localhost:8302/health   # Embedding engine
curl http://localhost:8300/health   # Qwen3-Coder
curl http://localhost:8200/health   # Nemotron
```
