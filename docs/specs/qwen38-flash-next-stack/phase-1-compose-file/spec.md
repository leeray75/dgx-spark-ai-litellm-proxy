# Qwen3.8-Flash-Next stack · Phase 1 — Compose file

| | |
|---|---|
| **Index** | [../SPECS.md](../SPECS.md) (all phases) |
| **Status** | Phase 1 implemented — compose file written and statically validated (AS-1 to AS-7 pass); independent review passed (R001/R002 fixes applied); never booted |
| **Date** | 2026-10-22 |
| **Depends on** | `docker-compose.qwen3.8.yml`, `docker-compose.agentgateway.yml` (sources, read-only) |
| **Next** | [../research.md](../research.md) (shared) → [plan.md](plan.md) → [tasks.md](tasks.md) |

## Problem

The default chat engine, `nvidia/Qwen3.8-27B-NVFP4`, generates at a live median of about 21 tok/s on this DGX Spark. `nvidia/Qwen3.8-Flash-Next-FP4-Local` is a mixture-of-experts model with about 6B active parameters out of 125B. NVIDIA validates it on DGX Spark, it scores higher than the 27B on every benchmark the Qwen card publishes, and community runs on a single Spark report 45–65 tok/s on agentic coding. There is no compose stack for it yet.

The agentgateway trial currently lives in its own compose project (`ai-litellm-agentgateway`). It joins the model stack's network as an external overlay, so starting it is a second, separate step.

## Goal

A single new compose file, `docker-compose.qwen3.8-flash-next.yml`. It should:

- run the same services as `docker-compose.qwen3.8.yml`;
- replace the Qwen3.8-27B engine with a Qwen3.8-Flash-Next-FP4-Local engine;
- include the agentgateway service from `docker-compose.agentgateway.yml`.

The whole stack then comes up with one `docker compose -f … up -d`.

## Phases

This spec covers **Phase 1 only**: write `docker-compose.qwen3.8-flash-next.yml` and validate it statically. Later phases are tracked in the index, [../SPECS.md](../SPECS.md).

> **2026-10-22 note:** this section first named Phase 2 "routing and integration" and Phase 3 "first boot". The order was swapped: Phase 2 is now first boot and tests, and Phase 3 is routing. Where this spec's text says "Phase 2" for routing work, read it as Phase 3.

## Non-goals (Phase 1)

- Starting, stopping, restarting, pulling, or recreating any container, image, network, or volume.
- Editing any existing file: other compose files, `litellm-config.yaml`, `agentgateway/config.yaml`, `.env`, scripts, `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `docs/*.md`.
- End-to-end or runtime testing.
- Git commits.

## User stories

**US-1 (P1)** As an operator, I can start the full stack with one compose file: Langfuse, LiteLLM, the embedding engine, the Flash-Next engine, and agentgateway. *(Executed in Phase 3.)*

**US-2 (P1)** As an operator, I can switch between the 27B stack and the Flash-Next stack the same way I switch between qwen3.8 and qwen3.6 today. The same compose project, network, ports, and data volumes are reused, so Langfuse and LiteLLM data carry over.

**US-3 (P1)** As an operator, I can read the file's header and see which engine flags come from NVIDIA's DGX Spark recipe and which are local deviations, with the reason for each.

**US-4 (P2)** As an operator, I can tune GPU memory utilization and MTP draft length through environment variables without editing the file.

## Functional requirements

### File and project

- **FR-P1-01** The new file MUST be `ai-litellm-proxy/docker-compose.qwen3.8-flash-next.yml`. No other file in the repository may be created or modified, apart from the docs in `docs/specs/`.
- **FR-P1-02** The compose project name MUST resolve to `ai-litellm-proxy`, the same as `docker-compose.qwen3.8.yml`. That keeps the network as `ai-litellm-proxy_ai-bridge`, which `local-image-gen-mcp` uses, and reuses the existing named data volumes. The file MUST NOT declare a top-level `name:`; this matches the qwen3.8 file.
- **FR-P1-03** The file MUST define exactly these services: `postgres`, `clickhouse`, `redis`, `minio`, `minio-init`, `langfuse-worker`, `langfuse-web`, `qwen3-8-flash-next-fp4-engine`, `nemotron-embed-engine`, `litellm`, `agentgateway`.

### Services carried over unchanged

- **FR-P1-04** `postgres`, `clickhouse`, `redis`, `minio`, `minio-init`, `langfuse-worker`, `langfuse-web` and `nemotron-embed-engine` MUST be semantically identical to their definitions in `docker-compose.qwen3.8.yml`. That covers image, container name, ports, environment, command, volumes, healthcheck, limits, `depends_on` and restart policy. The YAML anchors (`&langfuse-depends-on`, `&langfuse-env`) MUST be kept.
- **FR-P1-05** `litellm` MUST be identical to its qwen3.8 definition with one exception: `depends_on.qwen3-8-27b-nvfp4-engine` is replaced by `depends_on.qwen3-8-flash-next-fp4-engine` (`condition: service_healthy`).
- **FR-P1-06** The `networks:` block MUST be identical to the qwen3.8 file: an internal `ai-bridge` with the `bridge` driver.
- **FR-P1-07** The `volumes:` block MUST contain every data volume from the qwen3.8 file: `langfuse-postgres-data`, `langfuse-clickhouse-data`, `langfuse-clickhouse-logs`, `langfuse-minio-data`, `langfuse-redis-data`, `vllm-embed-compile-cache`. The three `vllm-qwen38-*` cache volumes MUST NOT be declared, because they belong to the 27B engine. It MUST add the four new engine cache volumes from FR-P1-13.

### Flash-Next engine

- **FR-P1-08** Service and `container_name` MUST be `qwen3-8-flash-next-fp4-engine`.
- **FR-P1-09** Image MUST be pinned by digest: `eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595`, with `platform: linux/arm64`. The mutable `:latest` tag MUST NOT be used (see CLAUDE.md's 2026-08-24 tag-pinning incident).
- **FR-P1-10** The image's entrypoint is `/opt/nvidia/nvidia_entrypoint.sh`, which runs its arguments. So `command:` MUST begin with `vllm serve nvidia/Qwen3.8-Flash-Next-FP4-Local`. `entrypoint:` MUST NOT be overridden.
- **FR-P1-11** The engine environment MUST include every variable in NVIDIA's DGX Spark recipe, with the recipe's values (list in research.md R-4), plus `HF_TOKEN: ${HF_TOKEN}`.
- **FR-P1-12** The vLLM flags MUST be NVIDIA's DGX Spark recipe flags (research.md R-5) with only these deviations:
  - **Add** `--served-model-name qwen3.8-flash-next`. This is the three-way name binding, completed in Phase 2.
  - **Parameterize** `--gpu-memory-utilization ${QWEN38_FLASH_GPU_MEMORY_UTILIZATION:-0.80}`. The default equals the recipe.
  - **Parameterize** the MTP draft length: `--speculative-config '{"method":"mtp","num_speculative_tokens":${QWEN38_FLASH_NUM_SPECULATIVE_TOKENS:-4}}'`. The default equals the recipe. This mirrors `QWEN38_NUM_SPECULATIVE_TOKENS` in the 27B file.

  Every other recipe flag MUST be present, with the recipe's value. No other flags may be added, including `--trust-remote-code`, `--seed` and `--mamba-ssm-cache-dtype`.
- **FR-P1-13** Caches MUST persist in named volumes. They replace the recipe's host bind mounts and follow this repo's convention:
  - `vllm-qwen38-flash-compile-cache:/root/.cache/vllm`
  - `vllm-qwen38-flash-flashinfer-cache:/root/.cache/flashinfer`
  - `vllm-qwen38-flash-triton-cache:/root/.triton`
  - `vllm-qwen38-flash-b12x-cache:/root/.cache/b12x`

  The Hugging Face cache MUST be bind-mounted `~/.cache/huggingface:/root/.cache/huggingface`, the same as the other engines.
- **FR-P1-14** Runtime options MUST match the recipe's `docker run` flags, translated to compose:
  - GPU reservation (`driver: nvidia`, `count: all`, `capabilities: [gpu]`);
  - `ipc: host`;
  - `shm_size: '16gb'`;
  - unlimited `memlock`;
  - `stack` 67108864 (soft and hard);
  - `security_opt` `seccomp=unconfined` and `apparmor=unconfined` (the `=` form, as in the recipe; the colon separator is deprecated).
- **FR-P1-15** Networking MUST use the `ai-bridge` network with port mapping `8301:8000`, not `--network host`. That is the same host port the 27B engine uses; the stacks are mutually exclusive.
- **FR-P1-16** The healthcheck MUST NOT rely on `curl`. The image history shows `curl` and `python3` are apt-installed, but neither is confirmed at runtime. It MUST use `python3` to GET `http://localhost:8000/health` and fail on any error or non-2xx response. Timing: `interval: 15s`, `timeout: 10s`, `retries: 120`, `start_period: 3600s`. That covers the first-boot download of about 103 GB plus ahead-of-time compilation.
- **FR-P1-17** The restart policy MUST be `"no"`. This deliberately differs from the 27B engine's `unless-stopped`. An out-of-memory or kernel failure on first boot must not turn into a restart loop on unified memory (`~/.claude/CLAUDE.md` rule 4).
  > *Note 2026-10-22 (after P3): superseded by user decision — the engine now uses `restart: unless-stopped` so it comes back after a reboot. The crash-loop guard moves to the `dgx-safe-update` pre-reboot check, which flags `unless-stopped` containers.*
- **FR-P1-18** The engine MUST have `depends_on: nemotron-embed-engine: condition: service_healthy`. vLLM refuses to start when free memory is below its requested share, and the embedding engine requests 0.1 × total. Starting the small engine first makes that check deterministic. It no longer depends on which of two engines profiles memory first.

### agentgateway

- **FR-P1-19** `agentgateway` MUST render identically to its definition in `docker-compose.agentgateway.yml`. The only intended differences are outside the rendered service: it joins the file's internal `ai-bridge` network (top-level definition: internal bridge instead of external; the network name still resolves to `ai-litellm-proxy_ai-bridge`), and the `:?` message text differs (see FR-P1-20; invisible in rendered output, verified by AS-6). The top-level `name: ai-litellm-agentgateway` and the external network declaration MUST NOT be carried over.
- **FR-P1-20** `AGW_LANGFUSE_BASIC_AUTH` MUST keep the `:?` guard from the source file, and the error message MUST name the derivation and say the Langfuse keys must be loaded first (see D-3). With the keys unset, the derivation yields `Og==` (base64 of `:`), which passes the guard but breaks Langfuse auth; the header MUST say so. Every compose command on this file needs the variable exported, including `config`, `logs` and `down`. The header MUST document the one-line export.

### Documentation in the file

- **FR-P1-21** The file MUST open with a header comment block. It MUST be concise, not the 27B file's 575-line investigation history, and MUST cover:
  - purpose and status (Phase 1, never booted);
  - usage, including the `AGW_LANGFUSE_BASIC_AUTH` export;
  - preconditions: the image-gen server stopped, the 27B stack and the standalone agentgateway project down;
  - the memory budget;
  - ports;
  - a PROVENANCE section listing each engine setting as *recipe-verbatim*, *deviation + reason*, or *unverified*;
  - the Phase 2 follow-ups that stay broken until they are done (LiteLLM and agentgateway still route to `qwen3-8-27b-nvfp4-engine`).
- **FR-P1-22** Each service SHOULD keep the section-divider comment style of the qwen3.8 file.

## Non-functional requirements

- **NFR-P1-01 No side effects.** While implementing and reviewing, the only Docker commands allowed are `docker compose … config`, `docker buildx imagetools inspect`, `docker manifest inspect`, and read-only `docker ps` / `docker inspect` / `docker images`. These are forbidden: `up`, `down`, `start`, `stop`, `restart`, `rm`, `kill`, `pull`, `create`, `run`, `build`, `docker volume …` / `docker network …` writes, and `sudo`.
- **NFR-P1-02 No secret leakage.** `docker compose config` interpolates `.env` secrets. Its full output MUST NOT be printed or written outside the scratchpad. Comparisons print only service and key paths, never values.
- **NFR-P1-03 Valid YAML and compose schema.** Both `docker compose config --quiet` and a YAML parse succeed.

## Decisions

- **D-1 GPU memory default 0.80; the image-gen server must be stopped.**
  - 0.80 is NVIDIA's validated Spark setting: about 17 GiB of KV cache and about 1M tokens.
  - Community data shows 0.70 leaves less than one full 262K sequence of KV (research.md R-7). Running at 0.70 alongside the image-gen server's 18 GB would also exceed this box's safe headroom.
  - Lower values stay possible through `QWEN38_FLASH_GPU_MEMORY_UTILIZATION`. Changing the value invalidates the compile cache.
- **D-2 Pinned community image.** Upstream vLLM can't read the checkpoint's compressed NVFP4 scale format yet (research.md R-3), so the community image is required. It is pinned by digest.
- **D-3 Keep the `:?` guard for `AGW_LANGFUSE_BASIC_AUTH`.** It fails fast instead of silently dropping agentgateway's traces to Langfuse. The friction it adds (every compose command needs the variable) is accepted for Phase 1. Phase 2 adds a launcher script, as `agentgateway-up.sh` does today.
  *Note 2026-10-22 (P3): friction resolved by `scripts/flash-next-compose.sh`; the `:?` guard is kept.*
- **D-4 Same project, ports and container names as the 27B stack.** The stacks are mutually exclusive, like qwen3.8 and qwen3.6. Switching stacks requires bringing the standalone `ai-litellm-agentgateway` project down first, because both define `container_name: agentgateway`.

## Acceptance scenarios (Phase 1 — static only)

- **AS-1** `AGW_LANGFUSE_BASIC_AUTH=dummy docker compose -f docker-compose.qwen3.8-flash-next.yml config --quiet` exits 0.
- **AS-2** `… config --services` lists exactly the 11 services in FR-P1-03.
- **AS-3** The rendered config's top-level `name` is `ai-litellm-proxy`, and its network name is `ai-litellm-proxy_ai-bridge`.
- **AS-4** A normalized comparison of the rendered configs passes, printing key paths only:
  - the carried-over services equal their qwen3.8 versions;
  - `litellm` differs only in `depends_on`;
  - `agentgateway`'s rendered service equals the agentgateway file's (the only intended differences are the top-level network definition and the `:?` message text, which AS-6 covers).
- **AS-5** In the rendered engine service: the image is the pinned digest; the command starts `vllm serve nvidia/Qwen3.8-Flash-Next-FP4-Local`; every R-4 variable and R-5 flag is present with the recipe value; the only additions are those in FR-P1-12; the restart policy is `no`; and `security_opt` contains both unconfined entries.
- **AS-6** Without `AGW_LANGFUSE_BASIC_AUTH` set, `config` fails with the guard's message.
- **AS-7** `git status` shows only the new compose file and the `docs/specs/` additions. No container, image, volume or network was created, changed, or removed: `docker ps -a` before and after is identical.

## Traceability

| Requirement | Artifact | Verification | Status |
|---|---|---|---|
| FR-P1-01, 02, 03 | new compose file | AS-2, AS-3, AS-7 | ✅ |
| FR-P1-04, 05, 06, 07 | new compose file | AS-4 | ✅ |
| FR-P1-08 – 18 | engine service | AS-5 | ✅ static (runtime behavior ⏳ until Phase 3) |
| FR-P1-19, 20 | agentgateway service | AS-4, AS-6 | ✅ |
| FR-P1-21, 22 | header and comments | review | ✅ |
| NFR-P1-01, 02 | process | AS-7, review | ✅ |
| NFR-P1-03 | new compose file | AS-1 | ✅ |
