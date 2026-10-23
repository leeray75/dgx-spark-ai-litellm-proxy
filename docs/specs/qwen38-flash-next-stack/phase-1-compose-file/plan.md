# Qwen3.8-Flash-Next stack · Phase 1 — Plan

Facts cited as `research.md R-n` are in the shared [../research.md](../research.md).

## Approach

Build `docker-compose.qwen3.8-flash-next.yml` by assembling it from the two source files rather than rewriting services by hand:

1. Copy lines 576–1104 of `docker-compose.qwen3.8.yml` (from `services:` to the end) as the skeleton. This keeps every unchanged service byte-for-byte, including the YAML anchors and the per-service comments.
2. Replace the `qwen3-8-27b-nvfp4-engine` service, including its section comment and its long flag-rationale comment block, with the engine service below.
3. Change `litellm.depends_on` to point at the new engine.
4. Append the `agentgateway` service before `networks:`, with the changes below.
5. Edit `volumes:`: drop the three `vllm-qwen38-*` volumes and add the four `vllm-qwen38-flash-*` volumes.
6. Write a new, concise header (FR-P1-21) in place of the 27B file's lines 1–575.

## File layout

```
ai-litellm-proxy/
├── docker-compose.qwen3.8-flash-next.yml   ← NEW (the only non-doc file touched)
└── docs/specs/qwen38-flash-next-stack/phase-1-compose-file/ ← this spec set
```

## Engine service (reference definition)

The implementation MUST match this definition in content. Comment wording may differ. Every flag and env value comes from research.md R-4/R-5, apart from the three FR-P1-12 deviations.

```yaml
  # ---------------------------------------------------------------------------
  # vLLM Engine — nvidia/Qwen3.8-Flash-Next-FP4-Local (ModelOpt mixed NVFP4/MXFP8, QAD)
  # NVIDIA DGX Spark — GB10 (128GB unified memory)
  # Flags and env: NVIDIA's DGX Spark recipe from the model card, verbatim,
  # except --served-model-name and the two env-parameterized values (see the
  # PROVENANCE section in the header).
  # ---------------------------------------------------------------------------
  qwen3-8-flash-next-fp4-engine:
    # Community image required: upstream vLLM can't read the checkpoint's
    # compressed NVFP4 scale format ("csf") yet. Pinned by digest (= :latest on 2026-10-22,
    # arm64, CUDA 13.0.2, built 2026-10-15) — never use the mutable tag.
    image: eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595
    platform: linux/arm64
    container_name: qwen3-8-flash-next-fp4-engine
    networks:
      - ai-bridge
    ports:
      - "8301:8000"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
      - vllm-qwen38-flash-compile-cache:/root/.cache/vllm
      - vllm-qwen38-flash-flashinfer-cache:/root/.cache/flashinfer
      - vllm-qwen38-flash-triton-cache:/root/.triton
      - vllm-qwen38-flash-b12x-cache:/root/.cache/b12x
    environment:
      HF_TOKEN: ${HF_TOKEN}
      VLLM_PLE_TABLE_MEMORY: "disk"
      B12X_DISK_BACKEND: "io_uring"
      CUTE_DSL_ARCH: "sm_121a"
      SAFETENSORS_FAST_GPU: "1"
      VLLM_WORKER_MULTIPROC_METHOD: "spawn"
      VLLM_SSM_CONV_STATE_LAYOUT: "DS"
      VLLM_USE_AOT_COMPILE: "1"
      VLLM_USE_MEGA_AOT_ARTIFACT: "1"
      VLLM_USE_V2_MODEL_RUNNER: "1"
      B12X_POLICY_MODE: "auto"
      VLLM_MXFP8_LM_HEAD: "1"
      VLLM_B12X_MOE_FP4_LAYER_MAX_INPUT_SCALE: "w13"
      VLLM_B12X_MOE_FP4_FORCE_A16: "1"
      B12X_W4A16_A4_PREFILL: "1"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    ipc: host
    shm_size: '16gb'
    ulimits:
      memlock:
        soft: -1
        hard: -1
      stack:
        soft: 67108864
        hard: 67108864
    security_opt:
      - seccomp=unconfined
      - apparmor=unconfined
    depends_on:
      nemotron-embed-engine:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"]
      interval: 15s
      timeout: 10s
      retries: 120
      start_period: 3600s
    command: >
      vllm serve nvidia/Qwen3.8-Flash-Next-FP4-Local
      --served-model-name qwen3.8-flash-next
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
      --speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN38_FLASH_NUM_SPECULATIVE_TOKENS:-4}}'
      --gdn-decode-kernel b12x
      --linear-backend b12x
      --moe-backend b12x
      --no-enable-flashinfer-autotune
      --mm-encoder-tp-mode data
      --reasoning-parser qwen3
      --tool-call-parser qwen3_xml
      --enable-auto-tool-choice
      --compilation-config '{"pass_config":{"fuse_act_quant":true}}'
      --gpu-memory-utilization ${QWEN38_FLASH_GPU_MEMORY_UTILIZATION:-0.80}
    restart: "no"
```

Notes:

- `urllib.request.urlopen` raises on connection errors and on HTTP status ≥ 400, so the healthcheck exits non-zero. vLLM's `/health` returns 200 with an empty body once the engine is ready.
- Values in `environment:` are quoted strings. Compose would otherwise turn bare `1` into an integer, which is harmless but inconsistent with the repo.
- The JSON in `--speculative-config` and `--compilation-config` uses single quotes, the same pattern as the 27B file. Compose shell-splits `command:` strings.

## litellm change

```yaml
    depends_on:
      postgres:
        condition: service_healthy
      qwen3-8-flash-next-fp4-engine:        # was qwen3-8-27b-nvfp4-engine
        condition: service_healthy
      nemotron-embed-engine:
        condition: service_healthy
      langfuse-web:
        condition: service_started
      redis:
        condition: service_healthy
```

## agentgateway service

Copy the service from `docker-compose.agentgateway.yml` unchanged, including its volumes, `user`, ports, memory limit and `restart: unless-stopped`. Change these:

- `networks: [ai-bridge]` now refers to the file's internal network. No change is needed in the service itself; only the top-level external network declaration and `name:` are not copied.
- `AGW_LANGFUSE_BASIC_AUTH: ${AGW_LANGFUSE_BASIC_AUTH:?export AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0) after 'set -a; source .env; set +a' - see header}`
  - The message must tell the operator to load `.env` first: with the keys unset the one-liner yields `Og==`, which passes the guard. Compose's `:?` message is literal text and isn't shell-expanded. Check that `config` accepts the message string. If `$(`, `'` or `"` in it cause an interpolation error, escape `$` as `$$` or shorten the message to `see header of docker-compose.qwen3.8-flash-next.yml`.
- Carry over its section comment. Add a note that `./agentgateway/data` must exist (`mkdir -p agentgateway/data`), as `agentgateway-up.sh` creates it today.

## Header outline (FR-P1-21)

```
# =============================================================================
# docker-compose.qwen3.8-flash-next.yml — Qwen3.8-Flash-Next-FP4-Local (nvidia) on NVIDIA DGX Spark (GB10)
#
# STATUS: Phase 1 (spec docs/specs/qwen38-flash-next-stack/phase-1-compose-file/) — written, statically
#         validated, NEVER BOOTED. Not the default stack.
#
# Usage, preconditions (stop local-image-gen-mcp; this stack and
#   docker-compose.qwen3.8.yml / .qwen3.6.yml share project "ai-litellm-proxy",
#   ports and container names — mutually exclusive; bring the standalone
#   agentgateway project down first: both use container_name agentgateway),
#   AGW_LANGFUSE_BASIC_AUTH export one-liner.
# Memory budget (R-6) and why 0.80 / why not 0.70 (R-7).
# Ports table (8301 engine, 8302 embed, 4000 LiteLLM, 4100/127.0.0.1:4101 agentgateway, …).
# PROVENANCE — recipe-verbatim / deviation + reason / unverified (curl/python3 apt-installed per
#   image history but not confirmed at runtime; python3 healthcheck, io_uring needs seccomp unconfined, qwen3_xml tool parsing).
# KNOWN GAPS until Phase 2 — litellm-config.yaml + agentgateway/config.yaml still route
#   qwen3.8-27b to qwen3-8-27b-nvfp4-engine; no Langfuse price; restart.sh/model-switch.sh
#   don't know this stack; Claude Code /model needs a claude-prefixed alias.
# Env overrides: QWEN38_FLASH_GPU_MEMORY_UTILIZATION (default 0.80),
#   QWEN38_FLASH_NUM_SPECULATIVE_TOKENS (default 4). Changing either invalidates the compile cache.
# =============================================================================
```

Keep it under about 120 lines.

## Validation (static only)

The validator script lives in the session scratchpad, not in the repo. It:

1. Runs `AGW_LANGFUSE_BASIC_AUTH=dummy docker compose -f <file> config --format json` for the new file, the qwen3.8 file and the agentgateway file. Output goes to the scratchpad and is never printed.
2. Parses each with `python3 -I`.
3. Compares the normalized service dicts per AS-4 and prints only differing key paths.
4. Checks AS-2, AS-3 and AS-5.
5. Runs the negative test AS-6 without the variable.

Record `docker ps -a --format '{{.Names}} {{.Status}}'` before and after (AS-7). Status strings like "Up 39 hours" change over time, so compare names and states, not exact uptime.

## Risks

| Risk | Mitigation |
|---|---|
| A community `:latest` image changes under us | Pinned by digest (FR-P1-09) |
| `curl` missing in the image (apt-installed per image history, unconfirmed at runtime) → healthcheck never passes | python3 healthcheck (FR-P1-16) |
| Out-of-memory on first boot → restart loop on unified memory | `restart: "no"` (FR-P1-17), image-gen stopped (D-1) |
| Startup memory-check race between the two engines | Engine depends on the embedding engine being healthy (FR-P1-18) |
| The `:?` guard blocks `logs` / `down` without the variable | Header one-liner; launcher script in Phase 2 (D-3) |
| Container-name clash with the running standalone agentgateway | Documented precondition (D-4); nothing is started in Phase 1 |
| Running `docker compose config` leaks secrets to logs | Output only to the scratchpad; key paths only (NFR-P1-02) |
