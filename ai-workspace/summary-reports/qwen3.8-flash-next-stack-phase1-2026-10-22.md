# Qwen3.8-Flash-Next-FP4-Local Stack (Phase 1) — Summary Report

**Date:** 2026-10-22
**Branch:** `fix/anthropic-messages-thinking-passthrough` (working tree only — nothing committed)
**Spec:** [`docs/specs/qwen38-flash-next-stack/phase-1-compose-file/`](../../docs/specs/qwen38-flash-next-stack/phase-1-compose-file/spec.md)
**Status:** Phase 1 complete. The compose file is written, statically validated, and approved by an independent review. It has **never been booted**.

---

## Goal

Add a compose stack for [`nvidia/Qwen3.8-Flash-Next-FP4-Local`](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) as a candidate replacement for `Qwen3.8-27B-NVFP4`. It should be one compose file that also includes agentgateway, so the whole stack starts with a single `up -d`.

Phase 1 covered only creating the compose file. No service was started, stopped, pulled, or recreated, and no end-to-end testing was done.

### Why this model

| | Qwen3.8-27B-NVFP4 (current) | Qwen3.8-Flash-Next-FP4-Local |
|---|---|---|
| Architecture | Dense, 27B | MoE, 125B total / 6B active, plus a 51B n-gram (PLE) table and 4B MTP |
| Decode on this box | **21.1 tok/s** live median (last 24 h) | ~45 tok/s stock recipe, 63–64 tuned on agentic coding (community reports, not measured here) |
| DeepSWE / SWE-bench Multilingual / Toolathlon (BF16, Qwen card) | 42.2 / 73.8 / 67.1 | **58.7 / 81.0 / 73.5** |
| GPQA Diamond (NVIDIA's quantized checkpoints) | 88.01 | **91.5** |
| Upstream vLLM support | Yes (`vllm/vllm-openai:nightly`) | **No.** The new compressed NVFP4 scale format needs the community `eugr/spark-vllm-b12x` image |

---

## What was produced

| File | Change |
|---|---|
| `docker-compose.qwen3.8-flash-next.yml` | **New**, 585 lines |
| `docs/specs/qwen38-flash-next-stack/SPECS.md` | **New**: multi-phase index for this stack: phases table, shared research, ID conventions, carried-over open items |
| `docs/specs/qwen38-flash-next-stack/phase-1-compose-file/spec.md` | **New**: FR-P1-01 – 22, NFR-P1-01 – 03, D-1 – D-4, AS-1 – AS-7, traceability |
| `docs/specs/qwen38-flash-next-stack/research.md` | **New**: shared across phases. Model card recipe (verbatim), image facts, memory budget, sources |
| `docs/specs/qwen38-flash-next-stack/phase-1-compose-file/plan.md` | **New**: reference engine definition, assembly steps, risks |
| `docs/specs/qwen38-flash-next-stack/phase-1-compose-file/tasks.md` | **New**: T001 – T010 plus the review loop, all ticked |

No other repo file was modified. `docker-compose.qwen3.8.yml`, `docker-compose.agentgateway.yml`, `litellm-config.yaml`, `agentgateway/config.yaml`, `.env`, `scripts/` and `CLAUDE.md` are untouched.

### Shape of the new compose file

- **Unchanged from `docker-compose.qwen3.8.yml`:** postgres, clickhouse, redis, minio, minio-init, langfuse-worker, langfuse-web, nemotron-embed-engine. They are byte-identical to the source, including the YAML anchors. `litellm` is identical apart from `depends_on`, which now points at the new engine.
- **Same project as the 27B stack:** project `ai-litellm-proxy`, network `ai-litellm-proxy_ai-bridge`, the same data volumes, engine port `8301`. The two stacks are swapped like qwen3.8 and qwen3.6 are today.
- **New engine, `qwen3-8-flash-next-fp4-engine`:**
  - NVIDIA's DGX Spark recipe from the model card, verbatim: all 14 env vars and every vLLM flag.
  - Image pinned by digest: `eugr/spark-vllm-b12x@sha256:03a95654…` (arm64, CUDA 13.0.2). The current driver (595.99.02) supports it, so **no driver change is needed**.
  - Deviations from the recipe, each documented in the file's PROVENANCE header:
    - `--served-model-name qwen3.8-flash-next`.
    - `--gpu-memory-utilization ${QWEN38_FLASH_GPU_MEMORY_UTILIZATION:-0.80}` and the MTP draft length `${QWEN38_FLASH_NUM_SPECULATIVE_TOKENS:-4}`; both defaults equal the recipe.
    - Bridge network plus port mapping instead of `--network host`.
    - Named cache volumes instead of host bind mounts.
    - `restart: "no"`.
    - A `python3` healthcheck instead of `curl`.
    - `depends_on` the embedding engine being healthy, so vLLM's startup free-memory check doesn't race between the two engines.
- **agentgateway:** merged in, identical to `docker-compose.agentgateway.yml`. It joins the internal network instead of an external one, and the `:?` guard message for `AGW_LANGFUSE_BASIC_AUTH` is rewritten.

---

## Key decisions

| ID | Decision | Why |
|---|---|---|
| D-1 | GPU memory default **0.80**; `local-image-gen-mcp` **must be stopped** while this stack runs | 0.80 is NVIDIA's validated Spark setting (~17 GiB KV, ~1M tokens). Community data at 0.70 shows only 175–240K tokens of KV, less than one full 262K context, and the image server's 18 GB on top would exceed safe headroom. **This corrects my earlier estimate** that 0.68–0.70 could run alongside the image server. |
| D-2 | Community image pinned by digest | Required by the model card; the digest pin avoids a repeat of the 2026-08-24 `:nightly` drift incident |
| D-3 | Keep the `:?` guard on `AGW_LANGFUSE_BASIC_AUTH` | Fails fast instead of silently losing traces. Cost: every compose command on this file, including `logs` and `down`, needs the variable exported. A launcher script is planned for Phase 2. |
| D-4 | Same project, ports and container names as the 27B stack | Matches the existing swap pattern. The standalone agentgateway project must be brought down first, because both define `container_name: agentgateway`. |

---

## Workflow and review

1. **Spec**: written by the main session after researching the model card, the image metadata (inspected without pulling) and the host's memory state.
2. **Implementation** (Sonnet subagent): assembled the file from the two sources and wrote a static validator in the session scratchpad. It renders the configs with `docker compose config`, never prints secret values, and compares only key paths.
3. **Independent review** (separate subagent): re-checked the recipe against the model card, diffed against the sources, executed the healthcheck snippet locally, and found from the image's build history that `curl` and `python3` are installed. Verdict: **APPROVE** with 3 MINOR and 4 NIT findings.
4. **Fixes** (implementer): all 7 applied, then the validator and safety checks were re-run.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | MINOR | The export one-liner run without sourcing `.env` yields `Og==` (base64 of `":"`). That passes the `:?` guard and silently breaks Langfuse auth. | The guard message and header now say to source `.env` first, and explain that `Og==` means the keys were empty |
| 2 | MINOR | "curl present: unverified" was stale | Image history shows `curl` and `python3` apt-installed; research.md and the header were updated |
| 3 | MINOR | KNOWN GAPS understated | Added the `default_fallbacks` / `-nothink` gap and the "switching back" hazard (`restart.sh` / `model-switch.sh` run `down --remove-orphans` on the qwen3.8 file, which also removes this stack's engine and agentgateway) |
| 4 | NIT | Missing blank line before the engine divider | Added |
| 5 | NIT | `seccomp:unconfined` uses Docker's deprecated separator | Changed to `seccomp=unconfined` / `apparmor=unconfined` in the file, spec and plan |
| 6 | NIT | The cold-start wording left out the download | "~10-13 min after a ~103 GB first download" |
| 7 | NIT | Task checkboxes and status markers were inconsistent | Tasks ticked; ⏳ is now used only for "not yet verified on hardware" |

---

## Verification (static only)

Checked after the fixes and independently re-run by the main session:

| Check | Result |
|---|---|
| AS-1: `config --quiet` | ✅ |
| AS-2: exactly 11 services | ✅ |
| AS-3: project `ai-litellm-proxy`, network `ai-litellm-proxy_ai-bridge` | ✅ |
| AS-4: carried-over services equal the source; litellm differs only in `depends_on`; agentgateway's rendered service equal to the source | ✅ |
| AS-5: engine image digest, command, all 14 env vars and every recipe flag, only the allowed additions, `restart: no`, `security_opt` | ✅ |
| AS-6: missing `AGW_LANGFUSE_BASIC_AUTH` → `config` fails with the guard message | ✅ |
| AS-7: `docker ps -a` names and states identical before and after; `git status` adds only the new compose file (plus `docs/specs/`) | ✅ |

The validator ends `RESULT: ALL PASS`: 48 checks, 0 failures.

**Not verified (needs Phase 3):** whether it boots, the actual memory headroom, throughput, `qwen3_xml` tool-calling with Claude Code and Cline, whether `seccomp=unconfined` is really needed for the io_uring reads of the PLE table, and whether the healthcheck's `start_period` of 3600 s is long enough for the first download.

---

## Known gaps (Phase 2)

The stack would come up, but these stay broken until Phase 2:

- `litellm-config.yaml` and `agentgateway/config.yaml` still route `qwen3.8-27b`, `qwen3.8-27b-nothink` and `default_fallbacks` to `qwen3-8-27b-nvfp4-engine`, which doesn't exist in this stack. Neither has a `qwen3.8-flash-next` entry yet.
- There's no launcher script that derives `AGW_LANGFUSE_BASIC_AUTH`.
- `restart.sh` and `model-switch.sh` don't know about this stack. Switching back through them works, but it also removes this stack's agentgateway.
- There's no Langfuse or agentgateway price for `qwen3.8-flash-next`.
- Claude Code's `/model` picker needs a `claude`-prefixed alias to show it.
- `CLAUDE.md` and `docs/models.md` aren't updated yet.

## Next steps

1. **Phase 2:** the routing, launcher, scripts, pricing and docs changes above.
2. **Phase 3, the first boot:**
   - Stop `local-image-gen-mcp` and bring down the standalone agentgateway project and the 27B stack.
   - Optionally pre-download the ~103 GB checkpoint with `hf download`.
   - Bring the stack up, then confirm the KV-cache size in the boot log, `MemAvailable`, tool calling, and the live tok/s with the `llm-throughput-check` skill.
3. **Decide whether it becomes the default**, comparing live tok/s and agent quality against the 27B's 21 tok/s.

## Sources

- [nvidia/Qwen3.8-Flash-Next-FP4-Local](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) · [Qwen/Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) · [nvidia/Qwen3.8-27B-NVFP4](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4)
- [diffbot DGX Spark recipe](https://huggingface.co/diffbot/Qwen3.8-Flash-Next-FP4-Local-DGX-Spark) · [ai-muninn benchmark](https://ai-muninn.com/en/blog/qwen38-flash-next-nvfp4-dgx-spark-vllm-recipe) · [NVIDIA forum: six weeks optimizing](https://forums.developer.nvidia.com/t/six-weeks-optimizing-qwen3-8-flash-next-on-one-dgx-spark-67-5-tok-s-median-decode-80-on-structured-work-reproducible-recipe-with-raw-data/385463)
