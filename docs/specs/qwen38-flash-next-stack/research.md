# Qwen3.8-Flash-Next stack — Shared research

Shared by every phase (see [SPECS.md](SPECS.md)). R-1 to R-10 were verified on 2026-10-22, before Phase 1 design. Each fact names its source. "Unverified" means nobody has confirmed it on this box yet.

Later phases append new entries with the next free number and a phase tag, e.g. `## R-11 (P2) …`. Existing entries are never renumbered. Correct an existing fact with a dated note under it, not by rewriting it.

## R-1 Host

- NVIDIA DGX Spark (GB10), aarch64, 121.7 GiB unified CPU/GPU memory (`docker stats`), driver 595.99.02 / CUDA 13.2.
- Disk: about 2.8 TB free on `/` (NVMe).
- GPU-resident memory at the time of writing:

  | Process | Memory |
  |---|---|
  | `qwen3-8-27b-nvfp4-engine` (util 0.54) | 62.9 GB |
  | `local-image-gen-mcp` | 18.0 GB (cap `IMAGE_GPU_MEMORY_LIMIT=40`) |
  | `nemotron-embed-engine` | 2.5 GB |

  `free -g`: 28 GB available, 9 GB of swap in use.
- `local-image-gen-mcp` never frees its pipeline. `unload()` exists in `models/qwen_image_2_1.py:452`, but `server.py` never calls it.

## R-2 Model — `nvidia/Qwen3.8-Flash-Next-FP4-Local`

Source: [model card](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) and `config.json`.

- `Qwen4ExpForConditionalGeneration` (`model_type: qwen4_exp`). 125B total parameters, 6B active, plus a 51B n-gram (PLE) embedding table and a 4B MTP head. Vision encoder included.
- 48 layers: 36 Gated DeltaNet and 12 Qwen Sparse Attention (2 KV heads, head_dim 256). 512 experts, 10 routed + 1 shared. 262,144 native context, extensible to 1M.
- Checkpoint: about 96 GiB, 21 safetensors shards (about 103 GB) under `tensors/`.
- Validated on DGX Spark "with or without PLE offload"; 1M tokens of FP8 KV with PLE offload.
- License: NVIDIA Open Model Agreement plus Qwen Community License 1.0.

## R-3 Upstream vLLM can't load it

The card says: "the NVFP4 scale factors in this checkpoint are in a new lossless compression format, but upstream vLLM support for this format has not yet landed. **You must use one of the containers provided below.**" `config.json` sets `weight_scale_encoding: "csf"` on every routed-expert layer. This repo's `vllm/vllm-openai:nightly`, `v0.19.1-cu130` and `v0.18.1-cu130` images are therefore unusable for it.

## R-3a Container — `eugr/spark-vllm-b12x`

Inspected with `docker buildx imagetools inspect`; nothing was pulled.

| Property | Value |
|---|---|
| Digest (`:latest` on 2026-10-22) | `sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595` (single-arch manifest) |
| Architecture | `arm64` |
| Created | 2026-10-15 |
| Base | CUDA 13.0.2 (`NVIDIA_REQUIRE_CUDA=cuda>=13.0`). The host driver supports it, so **no driver change is needed**. |
| Entrypoint | `/opt/nvidia/nvidia_entrypoint.sh` (runs its arguments); `Cmd`: none |
| WorkingDir | `/workspace/vllm` |
| User | root |
| Image healthcheck | none |
| Exposed ports | none |
| Relevant baked-in env | `TORCH_CUDA_ARCH_LIST=12.1a`, `FLASHINFER_CUDA_ARCH_LIST=12.1a`, `INSTANTTENSOR_IO_DEPTH=16`, `VLLM_BASE_DIR=/workspace/vllm` |
| `curl` / `python3` present | `curl` and `python3` are apt-installed in the final stage per the image history (layer ~79/104, after an earlier curl purge); not confirmed at runtime (the image isn't pulled). The healthcheck uses `python3` only. |

## R-4 NVIDIA DGX Spark recipe — environment (verbatim from the card)

```
VLLM_PLE_TABLE_MEMORY=disk
B12X_DISK_BACKEND=io_uring
CUTE_DSL_ARCH=sm_121a
SAFETENSORS_FAST_GPU=1
VLLM_WORKER_MULTIPROC_METHOD=spawn
VLLM_SSM_CONV_STATE_LAYOUT=DS
VLLM_USE_AOT_COMPILE=1
VLLM_USE_MEGA_AOT_ARTIFACT=1
VLLM_USE_V2_MODEL_RUNNER=1
B12X_POLICY_MODE=auto
VLLM_MXFP8_LM_HEAD=1
VLLM_B12X_MOE_FP4_LAYER_MAX_INPUT_SCALE=w13
VLLM_B12X_MOE_FP4_FORCE_A16=1
B12X_W4A16_A4_PREFILL=1
```

Docker run options: `--gpus all --ipc host --network host --shm-size=16g --ulimit memlock=-1 --ulimit stack=67108864 --security-opt seccomp=unconfined --security-opt apparmor=unconfined`.

The recipe bind-mounts host directories at: `/root/.cache/huggingface`, `/root/.cache/vllm`, `/root/.cache/flashinfer`, `/root/.triton`, `/root/.cache/b12x`.

`seccomp=unconfined` is most likely needed because Docker's default seccomp profile blocks the `io_uring_*` syscalls that `B12X_DISK_BACKEND=io_uring` uses to read the PLE table from NVMe. This is an inference, not stated on the card.

## R-5 NVIDIA DGX Spark recipe — vLLM flags (verbatim from the card)

```
vllm serve nvidia/Qwen3.8-Flash-Next-FP4-Local
  --host 0.0.0.0
  --port 8000
  --tensor-parallel-size 1
  --pipeline-parallel-size 1
  --mamba-cache-mode align
  --enable-prefix-caching
  --enable-chunked-prefill
  --dtype bfloat16
  --kv-cache-dtype fp8
  --quantization modelopt_mixed
  --block-size 16
  --load-format b12x
  --max-model-len 262144
  --max-num-seqs 8
  --max-num-batched-tokens 4096
  --speculative-config '{"method":"mtp","num_speculative_tokens":4}'
  --gdn-decode-kernel b12x
  --linear-backend b12x
  --moe-backend b12x
  --no-enable-flashinfer-autotune
  --mm-encoder-tp-mode data
  --reasoning-parser qwen3
  --tool-call-parser qwen3_xml
  --enable-auto-tool-choice
  --compilation-config '{"pass_config":{"fuse_act_quant":true}}'
  --gpu-memory-utilization 0.8
```

The tool parser is `qwen3_xml`. The 27B engine uses `qwen3_coder`, so tool calling must be re-validated in Phase 3.

## R-6 Memory budget

- **At 0.80:** vLLM's share is about 97 GiB of 121.7.
- **PLE on disk:** the n-gram table (about 27–48 GiB depending on how it's counted) stays on NVMe. About 68 GiB of weights stay resident ([diffbot recipe](https://huggingface.co/diffbot/Qwen3.8-Flash-Next-FP4-Local-DGX-Spark)).
- **Measured at 0.80** ([ai-muninn](https://ai-muninn.com/en/blog/qwen38-flash-next-nvfp4-dgx-spark-vllm-recipe)): KV 17.04 GiB = 1,069,759 tokens (about 16 KiB/token). `MemAvailable` 14.3–14.9 GB steady, 12.9 GiB during a 32K prefill.
- **Budget beside the engine:** embedding engine about 2.5 GB, observability containers about 5 GB (sum of their limits), OS about 6 GB. That leaves about 10 GB of headroom with the image-gen server **stopped**. With the image-gen server running (18 GB), headroom goes negative, so it MUST be stopped (D-1).
- **Startup memory check:** vLLM refuses to start when free memory is below util × total. This file's history records that failure on this box (the qwen3.8 file's corrections item 1, at 0.4). The embedding engine at 0.1 asks for about 12.2 GiB free, so starting it first avoids a race (FR-P1-18).

## R-7 Why not 0.70

- [diffbot](https://huggingface.co/diffbot/Qwen3.8-Flash-Next-FP4-Local-DGX-Spark) runs the same image at 0.70 and gets a KV pool of only 175–240K tokens, below one full 262,144-token sequence. Four 46K contexts already trigger preemption.
- A [forum user](https://forums.developer.nvidia.com/t/six-weeks-optimizing-qwen3-8-flash-next-on-one-dgx-spark-67-5-tok-s-median-decode-80-on-structured-work-reproducible-recipe-with-raw-data/385463) hit `ValueError: 3.02 GiB available vs 4.32 GiB needed at 262144`.
- So 0.70 is about the floor for a single full-length context, and it doesn't fit next to the image-gen server either.

## R-8 Expected behavior (for Phase 3, not verified here)

- Cold start takes 10–13 minutes; the first boot also downloads about 103 GB.
- Decode, one stream: about 45 tok/s with the stock recipe, 63–64 tok/s tuned on agentic coding. Prose is slower (27–38 tok/s).
- Prefill: about 1.7–2.1K tok/s.
- Greedy output can differ between runs, because b12x MoE reductions use atomics.

## R-9 agentgateway integration facts

- `docker-compose.agentgateway.yml` sets `name: ai-litellm-agentgateway` and joins the **external** `ai-litellm-proxy_ai-bridge`. Its `restart: unless-stopped` and `user: "1000:1000"` are deliberate (see its header).
- `AGW_LANGFUSE_BASIC_AUTH` isn't in `.env`. `scripts/agentgateway-up.sh` derives it as `base64(LANGFUSE_PUBLIC_KEY:LANGFUSE_SECRET_KEY)` (`base64 -w0`) at launch and runs `mkdir -p agentgateway/data`.
- `agentgateway/config.yaml` routes `qwen3.8-27b` to `http://qwen3-8-27b-nvfp4-engine:8000/v1`, routes the embedding engine and `local-image-gen-mcp:8500`, and exports traces to `langfuse:3000`. Under this stack the qwen3.8 route fails until Phase 2.
- `litellm-config.yaml` points `qwen3.8-27b` (also the `default_fallbacks` target) at `qwen3-8-27b-nvfp4-engine`. Under this stack those routes fail until Phase 2.

## R-10 Repository conventions (from `docker-compose.qwen3.8.yml` and `CLAUDE.md`)

- Engine host port `8301`, embedding `8302`, LiteLLM `4000`, Langfuse `3000`, MinIO `9090/9091`. Internal ports bind to `127.0.0.1`.
- Engine caches live in named volumes (`vllm-qwen38-compile-cache` and so on). The embedding engine's `vllm-embed-compile-cache` is shared between stacks in the same project.
- Each engine pins its image. `:nightly` drift caused the 2026-08-24 incident.
- `litellm` uses `restart: always`; other services use `unless-stopped`; `minio-init` uses `on-failure`.

## R-11 (P2) Facts for the first boot and tests (2026-10-22)

- **No Hugging Face CLI on the host.** No `hf` or `huggingface-cli`, and `huggingface_hub` isn't installed in `/home/leeray75/vscode-workspace/.venv` (which is the `python3` on PATH). The HF cache `~/.cache/huggingface/hub` already holds 255 GB; there's about 2.8 TB free on disk.
- **Memory with the 27B stack and image-gen up:** MemTotal 121.7 GiB, MemFree ≈ 13.3 GiB, MemAvailable ≈ 27.7 GiB, Cached ≈ 6.3 GiB, SwapFree ≈ 6.7 GiB.
- **Page cache and vLLM's startup check:** `scripts/restart.sh` runs `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` before starting an engine, and the repo `CLAUDE.md` says this frees unified memory before a new engine starts. CUDA's free-memory figure on GB10, which vLLM's startup check uses, tracks MemFree rather than MemAvailable. That's why a cache drop can be required even when MemAvailable is high. This is inferred from the repo's practice and the qwen3.8 file's `gpu_memory_utilization` OOM history, not measured in Phase 1.
- **Scripts bring stacks down with `--remove-orphans`:** `restart.sh` and `model-switch.sh` run `docker compose -f <stack> down --remove-orphans` and then `up -d`.
- **Existing tests:**
  - `scripts/test-agentic-capabilities.py` is stdlib only. It has 8 tests and the options `--base-url` (default `http://localhost:4000/v1`), `--api-key` (default `LITELLM_MASTER_KEY` or `.env`), `--model` (default `qwen3.8-27b`) and `--output`. It has no vision or throughput test.
  - `scripts/test-agentic-capabilities-langgraph.py` needs `langchain_openai` and `langgraph`, which are present in `/home/leeray75/vscode-workspace/.venv`. Its usage line shows only `--model` and `--output`.
  - 27B baselines are in `ai-workspace/reports/agentic-test-{stdlib,langgraph}-20260916.json`. The stdlib run had tool-selection breadth 3/4 (FAIL) and small-budget WARN.
- **The network is recreated when the 27B stack goes down:** `docker compose -f docker-compose.qwen3.8.yml down` removes `ai-litellm-proxy_ai-bridge`, and the next `up` creates a new network with the same name but a new ID. A stopped `local-image-gen-mcp` attached to the old network should be brought back with its compose `up -d`, not `docker start`. That behavior is inferred from how Docker handles networks; nobody has seen it happen on this box yet.
  *Note 2026-10-22 (P2): now observed, see R-12.*
- **LiteLLM entry for the 27B:** `qwen3.8-27b` → `openai/qwen3.8-27b` at `http://qwen3-8-27b-nvfp4-engine:8000/v1`, `api_key: "none"`, 262144 tokens, tool choice, function calling and vision all `true`, plus measured electricity costs. `default_fallbacks: ["qwen3.8-27b"]`.

## R-12 (P2) First boot and test results on this box (2026-10-22)

Measured on the DGX Spark, defaults only (util 0.80, MTP 4), with the image-gen server stopped. Raw logs and meminfo snapshots were kept in the session scratchpad.

**Preparation**
- Checkpoint download needed no extra license step. `HF_TOKEN` comes from the shell environment (`.bashrc`), not from `.env` (`.env` has only a comment about it). The snapshot is `b9ce18a6…`: 21 shards plus `model.safetensors.index.json`, 102.26 GB (96 GiB), no `.incomplete` files. The image is 28.1 GB.
- Downloading 96 GB left about 24 GiB of page cache and MemFree at 1.9 GiB. After shutting the 27B stack down, MemFree was only 9.7 GiB (MemAvailable 117.6), so the user had to drop caches (MemFree 118.2 GiB afterwards). This confirms the R-11 inference that the check must follow MemFree.

**Boot** (`up -d` at 21:27:56; engine healthy by 21:46:35 at the latest, **≤ 18 m 39 s**: `litellm-proxy`, which depends on `service_healthy`, started then, and vLLM was serving at 21:46:24. The 30 s poller first observed `healthy` at 21:46:50, 18 m 54 s. That is longer than the 10–13 min in R-8 because of the one-time b12x compile)
- Weights loaded in 104.5 s and 9.8 s (two stages); "Model loading took **70.32 GiB** memory and 238.9 s".
- b12x weights/state/bind preparation and JIT warmup compiled with 0 cached entries (first boot): about 6 min for weights preparation, 5 min for state preparation, plus warmup. The `init engine (profile, create kv cache, warmup model)` step took 749 s. Later boots should be faster if `vllm-*`/`b12x` caches persist (not measured).
- **Available KV cache 28.03 GiB = 1,491,188 tokens; "Maximum concurrency for 262,144 tokens per request: 5.69x"**. This is more than the 17.04 GiB / 1.07 M tokens in R-6.
- The healthcheck (python3 /health) worked inside the image, so python3 is present at runtime. No Traceback in the boot log. No container had OOMKilled. `litellm-proxy` started only after the engine was healthy.
- Host memory once healthy and idle: MemFree 7.0 GiB, **MemAvailable 8.16 GiB**, Cached 1.82 GiB. After the tests, idle (21:54): MemAvailable 6.81 GiB, MemFree 5.13 GiB. Memory was not sampled during the tests, so it is unknown how low MemAvailable went under load; the only readings are idle ones, and the lowest was 6.8 GiB, about 3.8 GiB above the 3 GiB rollback trigger. The R-6 estimate of about 10 GB headroom was optimistic. Keep image-gen stopped and watch MemAvailable under real traffic.
- Swap: SwapFree 15.27 GiB before boot, 6.17 GiB when healthy, 7.08 GiB later (about 8.9 of 16 GiB used, mostly cold vLLM pages; vmstat showed 0 swap-out while idle).
- All 11 services running (healthy where a healthcheck exists); `langfuse-minio-init` exited 0 as designed.
- `/v1/models` on the engine (`:8301`) and on LiteLLM (`:4000`) both list `qwen3.8-flash-next`.

**Tests** (reports in `ai-workspace/reports/agentic-test-*-qwen38-flash-next-*-20261022.json`)
- Stdlib, direct engine: 9 PASS, 1 WARN (small-budget, empty content at max_tokens=20), 0 FAIL. Tool selection 4/4. Vision PASS ("Red"). `qwen3_xml` tool calls arrive as proper OpenAI `tool_calls`, including streaming.
- Stdlib, through LiteLLM: 8 PASS, 1 WARN, 1 FAIL. Tool selection 3/4: "create a new file" picked `execute_command` instead of `write_file`. This is the same miss as the 27B 2026-09-16 run. The direct engine run got 4/4, so this is likely sampling variance (n=1 per path, temperature 1.0). Supporting that, two later direct-engine re-runs (after script edits, reports kept in the scratchpad) scored breadth 2/4 each, so the result moves between runs. The script labels breadth 3/4 as FAIL and exits 1; AS-7 itself is met by both runs (all seven required tests PASS, breadth ≥ 3/4).
- LangGraph, through LiteLLM: 4 PASS, 1 WARN (reasoning field not surfaced by langchain_openai, as for the 27B), 1 FAIL (tool selection 2/4). The write_file and npm test cases hit `GraphRecursionError` at limit 15. The 27B also scored 2/4 with a recursion error on a different case. The multi-step chain passed, but used 7 calls where the 27B used 2.
- Compared with the 27B stdlib report: same results on every test except the engine-direct breadth (4/4 vs 3/4); new Vision and Throughput tests pass.

**Throughput** (27B baseline: 21.1 tok/s live median)
- Test script, 1024 completion tokens (includes reasoning tokens; `finish_reason=length`, i.e. it hits the cap), wall time includes prefill: 45.5 tok/s direct, 47.7 tok/s via LiteLLM.
- vLLM log `Avg generation throughput` while the three runs executed: 23 non-zero 10 s samples (21:47:14–21:50:54), median **38.2 tok/s**, max 48.7 (mixed short requests and prefill; MTP speculation on).
- That is about 1.8–2.3x the 27B and in line with R-8 (about 45 tok/s stock).
- **Stale network observed:** `local-image-gen-mcp` still references network `0f655f48…`, but the live `ai-litellm-proxy_ai-bridge` is `c84d4eac…` (recreated when the 27B stack went down). Restoring image-gen therefore needs its compose `up -d` (`docker/docker-compose.yml` + `docker-compose.override.yml`), not `docker start`.
- **Operational gap while this stack is up:** `qwen3.8-27b`, `qwen3.8-27b-nothink` and LiteLLM's `default_fallbacks` target the absent 27B engine and fail; agentgateway's qwen3.8 route fails too. Phase 3 fixes the routing.

## R-13 (P3) Facts for routing, operations and pricing (2026-10-22)

- **Chat template:** the checkpoint's `chat_template.jinja` checks `enable_thinking is defined and enable_thinking is false`, so `chat_template_kwargs.enable_thinking: false` (LiteLLM `extra_body`, agentgateway `overrides`) turns reasoning off. It also honors `preserve_thinking`.
- **Claude Code discovery:** Claude Code's gateway model discovery keeps only IDs that match `/^(claude|anthropic)/i` (saved memory, verified 2026-07-17). A non-Claude model appears in `/model` only under a `claude`-prefixed alias; otherwise it has to be typed by hand.
- **agentgateway today:** provider `vllm-qwen38` points at `http://qwen3-8-27b-nvfp4-engine:8000/v1`, completions only. Its models are `claude-*` (anthropic), `qwen3.8-27b`, `qwen3.8-27b-nothink` (`params.model: qwen3.8-27b`, `overrides.chat_template_kwargs.enable_thinking: false`), `qwen3.6-35b-a3b` and `nemotron-3-embed-1b-nvfp4`.
- **Switch scripts:**
  - `scripts/restart.sh` (279 lines) and `scripts/model-switch.sh` (307 lines) both have a `stop_all` that runs `down --remove-orphans` on the qwen3.8, qwen3.6, coder and nemotron files.
  - `wait_for_container` uses `max_wait=600` (10 min), less than Flash-Next's ≤ 18 m 39 s first boot.
  - `restart.sh` drops caches with `sudo … || log_warning`; `model-switch.sh` doesn't.
  - Neither script has a dry-run mode.
- **shellcheck** isn't installed.
- **Pricing tool:** `~/.claude/skills/llm-power-cost/scripts/power_cost.py` reads `~/power-logs/power-YYYY-MM.csv`, which the user unit `power-logger.service` writes. Its `qwen_*` counters scrape vLLM `/metrics` on `:8301`, now the Flash-Next engine. The rate is $0.298/kWh. Changing a Langfuse model definition means DELETE + POST through the public API (there's no update). The 27B definition is `cmv2s7old000apj07jlh6hol6`.
- **Clients outside the repo:** `~/.cline/data/settings/models.json` references `qwen3.8-27b`, as do some Cline session logs, which are history. No hits under `~/.config` or `~/.claude/settings.json`.
  *Note 2026-10-22 (P3): `~/.claude/settings.json` does have one hit, but it is a `permissions.allow` rule for `docker compose -f …/docker-compose.qwen3.8.yml up -d --no-deps qwen3-8-27b-nvfp4-engine`, not a model setting. Its `model` is `opus`. See R-14.*

## R-14 (P3) Measured prices, Langfuse, verification and findings (2026-10-22)

**Prices** (`power_cost.py --since 2026-10-22T21:46:35Z --rate 0.298`, run 22:07:59Z). The script applies to `:8301` unchanged: `power-logger.sh` scrapes `localhost:8301/metrics` for the `qwen_*` counters (they first appear in the CSV at 21:47:14Z, after the Flash-Next engine started; no counter reset in the window), and its optional `--langfuse` query matches `%qwen3.8%`, so it also covers Flash-Next. Nothing 27B-specific needed adapting.

| Quantity | Value |
|---|---|
| Window | 21:46:38Z – 22:07:59Z, 0.35 h, 254 samples, 0 resets, 0 gaps |
| Tokens | input 56,918, output 12,482 |
| Sample size | **21 decode intervals, 12,482 output tokens → below 30 / 20,000, so PROVISIONAL** (FR-P3-12) |
| Decode | 40.9 tok/s at 36.7 W → **0.90 J/output token** |
| Prefill | 39 intervals at 42.1 W → 0.01522 J per counted input token (mostly fresh test prompts; the 27B's 0.001 came from prefix-cache-heavy agent traffic) |
| Idle baseline | 12.4 W (about $0.089/day) |
| Energy | total 6.75 Wh = $0.00201; above idle 2.37 Wh = $0.00071 |
| Per 1M tokens | output $0.0742, input $0.001260 |
| LiteLLM values used | `output_cost_per_token: 7.42e-08`, `input_cost_per_token: 1.26e-09` on all three Flash-Next aliases |

Re-derive after about a day of real use; expect the input price to fall.

**Langfuse.** No `qwen3.8-flash-next` definition existed, so it was a plain `POST /api/public/models` (no delete): `modelName qwen3.8-flash-next`, `matchPattern (?i)^(openai/)?(qwen3.8-flash-next)$`, `unit TOKENS`, input 1.26e-9, output 7.42e-8, **id `cmvk3jw270001mo07qns04r4t`**. The 27B definition `cmv2s7old000apj07jlh6hol6` was listed before and after and is unchanged. `LANGFUSE_HOST` (the Tailscale hostname) resolves from the host, so no `localhost:3000` fallback was needed. `./scripts/agentgateway-sync-costs.py` then wrote `vllm-qwen38-flash/qwen3.8-flash-next` and `…-nothink` into `agentgateway/costs/langfuse-overlay.json` (0.00126 / 0.0742 per 1M); the 27B definition has no agentgateway route now and was skipped, so after a rollback the sync script must be re-run.

**Apply.** The engine was busy at first (`vllm:num_requests_running` 1, from another client), so the restart waited until it was 0 with no `Running: [1-9]` in the last 2 minutes (22:14:52Z), then `./scripts/flash-next-compose.sh restart litellm agentgateway`. LiteLLM answered `/health/liveliness` 200 about 30 s later. `StartedAt` of the Flash-Next engine (21:29:09Z) and the embedding engine (21:27:57Z) did not change; `litellm-proxy` and `agentgateway` restarted at 22:15Z.

**Verification** (all via the restarted gateways):
- LiteLLM `/v1/models` lists `qwen3.8-flash-next`, `qwen3.8-flash-next-nothink`, `claude-qwen3.8-flash-next`, `qwen3.6-35b-a3b`, the embedding model and the `anthropic/*` entries; it lists neither `qwen3.8-27b` nor `qwen3.8-27b-nothink`. agentgateway `:4100/v1/models` lists `qwen3.8-flash-next`, `qwen3.8-flash-next-nothink`, `qwen3.6-35b-a3b`, the embedding model and the `claude-*` entries.
- One chat request per alias succeeded through LiteLLM (all three) and through agentgateway (both). `qwen3.8-flash-next` and `claude-qwen3.8-flash-next` return `reasoning_content` and 16–22 reasoning tokens; **both `-nothink` aliases return no `reasoning_content` and `reasoning_tokens` 0**, with content `OK`.
- `POST /v1/messages` with `model: claude-qwen3.8-flash-next` returned `type: message`, `role: assistant`, `stop_reason: end_turn`, a `thinking` block and a `text` block ("OK"): the Claude Code path works and the explicit alias wins over `anthropic/*`.
- Langfuse: the newest LiteLLM generation (`openai/qwen3.8-flash-next`, environment `production`, 9 input / 1 output tokens) has total cost 8.554e-08 = 9 × 1.26e-9 + 1 × 7.42e-8, so the new definition matched. The `/v1/messages` request, logged as `qwen3.8-flash-next`, cost 1.7759e-06 (55 in, 23 out), also matched. agentgateway generations (environment `agentgateway-trial`) show output cost 7.598e-05 for 1,024 tokens.
- `scripts/test-agentic-capabilities.py --base-url http://localhost:4100/v1 --model qwen3.8-flash-next`: 8 PASS, 1 FAIL, 1 WARN. The FAIL is **Streaming reconstruction: `IndexError`**. agentgateway ends a stream with a usage-only chunk whose `choices` is `[]` (valid OpenAI behaviour; LiteLLM sends no such chunk), and the script does `chunk.get("choices", [{}])[0]` (line 204), which raises on `[]`. A copy of the script with `(chunk.get("choices") or [{}])[0]` passes that test through agentgateway. The script was not changed in Phase 3 (outside the file list). Tool-selection breadth was 4/4 in the real run and 3/4 in the patched-copy run, in line with the run-to-run variance noted in R-12. Vision PASS; decode ~46 tok/s.

**Findings**
- `scripts/model-switch.sh` could never run any target on this box: `check_env_vars` greps `.env` for `HF_TOKEN=`, but `.env` only has a comment (the token comes from `~/.bashrc`). Phase 3 now lets an exported variable count.
- Memory gate design (revised after review): `MemFree` measured before stopping a running stack includes what that stack holds, so a pre-stop `MemFree` check would fail whenever any engine runs. `model-switch.sh flash` therefore has (1) a **pre-stop page-cache gate**: `Cached+Buffers` ≥ 10 GiB (MemTotal 121.7 − 105 GiB needed free − ~5 GiB baseline ≈ 11.7, rounded down) aborts with exit 2 before anything is stopped (measured now: 2.9 GiB), (2) a `MemFree` check before stopping only when no engine or image-gen container runs, and (3) a **post-stop `MemFree` gate** that aborts with exit 3 before `up`; at that point the previous stack is already stopped and nothing is serving, so the message says so and prints the sudo drop command and the re-run command. At verification time `MemFree` was 3–4 GiB with the stack up, `MemAvailable` ~5.8–6.8 GiB.
- agentgateway logged `/mcp/image-gen` 500s ("backends required DNS resolution which failed") for a Tailscale client at 22:14Z: expected while `local-image-gen-mcp` is off.
- Existing `restart.sh`/`model-switch.sh` `status` lines printed literal `\033[…]` text (`echo` without `-e`); fixed while adding the Flash-Next lines.
- Client inventory (nothing edited): `~/.cline/data/settings/models.json` model key `…/models/qwen3.8-27b` (rename to `qwen3.8-flash-next`, with `qwen3.6-35b-a3b`'s name/price copied there today, so also fix `name` and prices); Cline session logs under `~/.cline/data/sessions/` (history); `~/.claude/settings.json` has only a `permissions.allow` rule mentioning the 27B compose command (harmless; model `opus`); nothing under `~/.config`. In the repo: the default `DEFAULT_MODEL = "qwen3.8-27b"` and usage lines in `scripts/test-agentic-capabilities.py` and `-langgraph.py`, a comment in `.env.sample`, and history in `CHANGELOG.md`.

**Removed aliases (decision U-5).** Checked after the restart: LiteLLM answers `qwen3.8-27b`, `qwen3.8-27b-nothink` and an unknown name (`no-such-model`) with HTTP 200, served by Flash-Next through `default_fallbacks`, with reasoning present and the requested name echoed in `model`. `qwen3.8-27b-nothink` callers therefore lose no-think silently. agentgateway returns 404 `model_not_found` for all three. The user decided to keep this behaviour (no compat aliases, `default_fallbacks` unchanged); it is documented in troubleshooting 4e, `agents.md`, `CLAUDE.md` and the CHANGELOG.

**Review fixes (R002, 2026-10-22).**
- `model-switch.sh`: pre-stop page-cache gate (exit 2) plus the post-stop MemFree gate (exit 3, "previous stack STOPPED", re-run command, mentions `restart.sh`); both gates documented in the script header and help.
- Both scripts: `DRY_RUN` is a dry run for any non-empty value except `0`; dry-run output uses `%q` and shows the real `docker compose` command with "(with AGW_LANGFUSE_BASIC_AUTH derived from .env)" instead of the internal helper name; `verify_stopped` after `stop_all` aborts if an engine container or `agentgateway` still runs; `warn_27b_rollback` lists each 27B item still commented out (LiteLLM aliases, `default_fallbacks`, agentgateway model) and the `agentgateway-sync-costs.py` re-run.
- `scripts/test-agentic-capabilities.py`: tolerates the usage-only stream chunk (`choices: []`); both test scripts default to `qwen3.8-flash-next`. Re-run through agentgateway: Streaming reconstruction PASS (8 PASS, 1 FAIL, 1 WARN; the FAIL was tool-selection breadth 2/4, the sampling variance noted in R-12).
- Docs: troubleshooting 4e, `agents.md`, `CLAUDE.md`, CHANGELOG now describe the real behaviour for removed aliases; supersession note added next to P1 D-3.

