# Qwen3.8-Flash-Next stack · Phase 2 — First boot and tests

| | |
|---|---|
| **Index** | [../SPECS.md](../SPECS.md) (all phases) |
| **Status** | ✅ Implemented and reviewed 2026-10-22 (review findings fixed); Flash-Next stack left running |
| **Date** | 2026-10-22 |
| **Depends on** | Phase 1 ✅: `docker-compose.qwen3.8-flash-next.yml`; shared [../research.md](../research.md) R-1 – R-11 |
| **Supersedes** | Index phase plan of 2026-10-22: this phase was "Phase 3 — first boot". Routing work moves to Phase 3, except the LiteLLM alias (FR-P2-03), which the tests need. |
| **Next** | [plan.md](plan.md) → [tasks.md](tasks.md) |

## Problem

The Phase 1 compose file has never run. We don't know whether the Flash-Next engine boots on this box, how much KV cache it gets, or whether tool calling, reasoning, vision and streaming work with this checkpoint and its `qwen3_xml` parser. We also don't know its real decode speed against the 27B's 21 tok/s. The existing agentic test scripts can test it, but they don't cover vision or decode speed.

## Goal

Replace the running 27B stack with the Flash-Next stack on this machine, then test the new model through the engine directly and through LiteLLM. The Flash-Next stack is left running at the end. The 27B stack is only restored if the new engine fails to boot.

## Scope

**In scope**
- Preparation that doesn't disrupt anything: pull the pinned image and pre-download the checkpoint while the 27B stack is still up.
- Shut down the 27B stack, the standalone agentgateway project and `local-image-gen-mcp`.
- Bring up `docker-compose.qwen3.8-flash-next.yml` and record the boot facts.
- Add a `qwen3.8-flash-next` alias to `litellm-config.yaml`. This is additive only.
- Extend `scripts/test-agentic-capabilities.py` and `scripts/test-agentic-capabilities-langgraph.py`, then run them against the new model.
- Roll back to the 27B stack only if the engine fails to boot.

**Out of scope (Phase 3)**
- `agentgateway/config.yaml` routes.
- `default_fallbacks`, a `-nothink` alias, a `claude`-prefixed alias, and prices.
- A launcher script, `restart.sh` / `model-switch.sh` support, and `CLAUDE.md` / `docs/` updates.
- Making this the default stack.

## Functional requirements

### Preparation (no disruption)

- **FR-P2-01** Pull the engine image by digest, `eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595`, while the 27B stack is still running. Never pull `:latest`.
- **FR-P2-02** Download the full checkpoint `nvidia/Qwen3.8-Flash-Next-FP4-Local` into the host cache `~/.cache/huggingface/hub` before any shutdown. Use a throwaway venv in the session scratchpad: no `hf` CLI is installed on the host, and nothing is installed system-wide. `HF_TOKEN` comes from `.env` and is never printed. If the download returns 401 or 403 (license not accepted), stop and report it; the user must accept the terms on Hugging Face.
- **FR-P2-03** Add one entry to `litellm-config.yaml`, directly after the `qwen3.8-27b-nothink` entry:
  - `model_name: qwen3.8-flash-next`
  - `model: openai/qwen3.8-flash-next`
  - `api_base: http://qwen3-8-flash-next-fp4-engine:8000/v1`
  - `api_key: "none"`
  - `model_info`: 262144 for max/input/output tokens, and `supports_tool_choice`, `supports_function_calling`, `supports_vision` all `true`. No cost fields; prices are Phase 3.
  - A comment block in the file's existing style.

  No other line in the file may change. The entry is harmless under the other stacks; it fails only when called, like the `qwen3.6-35b-a3b` alias.
- **FR-P2-04** Extend `scripts/test-agentic-capabilities.py`. Existing tests and their defaults stay as they are (default model `qwen3.8-27b`, default base URL LiteLLM):
  - **(a) Vision test.** Build a solid-red PNG of at least 64×64 with the standard library only (`zlib` + `struct`) and send it as a `data:image/png;base64,…` `image_url` content part. Ask for the single color. PASS if the answer contains "red".
  - **(b) Decode throughput test.** One request of about 400–600 output tokens. Report `completion_tokens`, wall time and tok/s in the detail. It is informational: PASS whenever `completion_tokens > 0`, and it never fails on speed.
  - **(c)** Make the small-budget WARN text model-neutral, so it no longer points only at `docker-compose.qwen3.8.yml`.
  - **(d)** Update the docstring: new tests, and examples for `qwen3.8-flash-next` via LiteLLM and directly against the engine at `http://localhost:8301/v1`.
- **FR-P2-05** Extend `scripts/test-agentic-capabilities-langgraph.py`: add `--base-url` (default `http://localhost:4000/v1`) and `--api-key` (default `LITELLM_MASTER_KEY` / `.env`) if they aren't there. Update the docstring examples. Test logic stays the same.
- **FR-P2-06** Both scripts MUST still pass `python3 -m py_compile` and `--help` before any shutdown.

### Shutdown

- **FR-P2-07** Before shutting down, check that the 27B engine is idle: no `Running: [1-9]` in its log over the last 2 minutes. If it isn't idle, poll every 60 s for up to 10 minutes, then proceed anyway and note it in the report. Record a baseline: `docker ps -a` (name, state), `docker volume ls -q`, `/proc/meminfo` (MemTotal, MemFree, MemAvailable, Cached, SwapFree).
- **FR-P2-08** Shut down in this order:
  1. `docker stop local-image-gen-mcp`. Stop only; don't remove or recreate.
  2. The standalone agentgateway: `docker compose -f docker-compose.agentgateway.yml down`, with `AGW_LANGFUSE_BASIC_AUTH` derived after sourcing `.env`, as in `scripts/agentgateway-up.sh`.
  3. `docker compose -f docker-compose.qwen3.8.yml down`.

  `-v`, `--volumes`, `--rmi` and `docker volume rm` / `prune` MUST NOT be used. No data volume may disappear.
- **FR-P2-09 Memory checkpoint.** After shutdown, record `/proc/meminfo`. If MemFree is below 105 GiB, the implementer MUST stop and ask the user to drop the page cache. That needs `sudo`, which only the user can run:

  ```
  sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
  ```

  Resume only once MemFree is at least 105 GiB, or once the user explicitly says to go ahead. On GB10, CUDA's free-memory figure, which vLLM's startup check uses, doesn't count reclaimable page cache (R-11). `restart.sh` drops caches before every engine start for this reason.

### Boot

- **FR-P2-10** Start the stack with `docker compose -f docker-compose.qwen3.8-flash-next.yml up -d`, with `AGW_LANGFUSE_BASIC_AUTH` derived as in Phase 1's header. Defaults only: no `QWEN38_FLASH_*` overrides.
- **FR-P2-11** Wait until `qwen3-8-flash-next-fp4-engine` is `healthy`. Poll `docker inspect` every 30 s and watch the logs for `Traceback`, `Error`, `OOM` and container exit. Limit: 60 minutes from `up`.
- **FR-P2-12** Record from the boot log and the host:
  - weights memory, KV-cache GiB and tokens, and "Maximum concurrency";
  - the time from `up` to healthy;
  - `/proc/meminfo` once healthy and idle;
  - `OOMKilled` for every container;
  - state and health of all 11 services.
- **FR-P2-13** Check `GET http://localhost:8301/v1/models` lists `qwen3.8-flash-next`, and that LiteLLM's `GET http://localhost:4000/v1/models` (master key) lists it too.

### Tests

- **FR-P2-14** Run `scripts/test-agentic-capabilities.py` twice:
  - **(1)** directly against the engine: `--base-url http://localhost:8301/v1 --model qwen3.8-flash-next`;
  - **(2)** through LiteLLM: `--model qwen3.8-flash-next`.

  Save the JSON reports as `ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-{engine,litellm}-20261022.json`.
- **FR-P2-15** Run the LangGraph test with `/home/leeray75/vscode-workspace/.venv/bin/python3` through LiteLLM. Save the report as `ai-workspace/reports/agentic-test-langgraph-qwen38-flash-next-20261022.json`.
- **FR-P2-16** Record decode throughput two ways:
  - the vision/throughput test's tok/s;
  - the vLLM log's `Avg generation throughput` samples while the tests run (median of non-zero samples).

  Compare against the 27B baselines: 21.1 tok/s live median, and the reports `ai-workspace/reports/agentic-test-{stdlib,langgraph}-20260916.json`.

### Rollback (boot failure only)

- **FR-P2-17** Roll back only if one of these happens:
  - the engine isn't healthy within 60 minutes;
  - the engine container exits, or `OOMKilled=true` on any container;
  - MemAvailable stays below 3 GiB for 2 minutes or more.

  Steps:
  1. Save the last 300 engine log lines to the scratchpad.
  2. `docker compose -f docker-compose.qwen3.8-flash-next.yml down` (no `-v`).
  3. `docker compose -f docker-compose.qwen3.8.yml up -d`, and wait for the 27B engine to be healthy.
  4. `./scripts/agentgateway-up.sh`.
  5. Restore `local-image-gen-mcp` with `docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml up -d`, run from `~/vscode-workspace/local-image-gen-mcp`. Use this, not `docker start`: the `ai-litellm-proxy_ai-bridge` network was recreated, so the stopped container's network reference is stale (R-11).

  Test failures MUST NOT trigger a rollback.

## Operational gap while this stack is up

`qwen3.8-27b`, `qwen3.8-27b-nothink` and LiteLLM's `default_fallbacks` target the absent 27B engine, and agentgateway's qwen3.8 route does too, so they fail until Phase 3 fixes the routing. Only `qwen3.8-flash-next` (via LiteLLM or the engine on `:8301`) works.

## Non-functional requirements

- **NFR-P2-01 Allowed Docker actions.** Only the commands named in FR-P2-01, 08, 10 and 17, plus read-only commands (`ps`, `inspect`, `logs`, `images`, `volume ls`, `compose config`). Not allowed: `docker system/volume/image prune`, `rm -v`, `--volumes`, `--rmi`, any change to the NVIDIA driver or packages, `apt`, `fwupdmgr`, or a reboot. `sudo` is run only by the user.
- **NFR-P2-02 Secrets.** `.env` values, the master key and `AGW_LANGFUSE_BASIC_AUTH` are never printed, logged, or written to reports. Rendered `compose config` output stays in the scratchpad.
- **NFR-P2-03 Files changed.** Only `litellm-config.yaml`, the two test scripts, the three new report JSONs, and the Phase 2 spec and index docs. Nothing else in either repo.
- **NFR-P2-04 No commits.**

## Decisions

- **D-1 Pre-download before shutdown.** That cuts downtime from about 103 GB of download plus boot to boot only. The 27B stack keeps serving while the download runs.
- **D-2 The memory checkpoint is a human step.** Dropping the page cache needs `sudo`, and the Bash tool can't run it (global CLAUDE.md rule 5).
- **D-3 Keep Flash-Next running at the end, even if some tests fail.** The user asked to switch to it. Test results inform Phase 3. Only a boot failure triggers a rollback.
- **D-4 Test both the direct engine and LiteLLM.** The direct run isolates model and parser behavior. The LiteLLM run covers the path Cline, Claude Code and OpenCode actually use, including any reasoning or tool-call translation.

## Acceptance scenarios

- **AS-1** The image is present locally under the pinned digest. The checkpoint snapshot has all 21 shards plus `model.safetensors.index.json`, with no `.incomplete` files. Both are true before any shutdown.
- **AS-2** Both test scripts pass `py_compile` and `--help`. The stdlib script has the vision and throughput tests. The `litellm-config.yaml` diff is exactly one added entry.
- **AS-3** After shutdown: `qwen3-8-27b-nvfp4-engine`, the standalone `agentgateway` and `local-image-gen-mcp` are not running. `docker volume ls -q` matches the baseline.
- **AS-4** All 11 Flash-Next stack services are running, and those with healthchecks are healthy. No container has `OOMKilled=true`.
- **AS-5** The boot log shows a KV cache of at least 262,144 tokens ("Maximum concurrency" ≥ 1.00x). Weights, KV GiB, tokens, concurrency and boot time are recorded.
- **AS-6** Both `/v1/models` endpoints list `qwen3.8-flash-next`.
- **AS-7** In both stdlib runs, these PASS: Connectivity, Reasoning presence, Single tool call, Multi-turn tool context, No hallucinated calls, Streaming reconstruction and Vision. Tool selection breadth is at least 3/4, the 27B baseline. Small-budget may be PASS or WARN. Any other outcome is reported, with no rollback.
- **AS-8** The LangGraph run completes and is compared with the 27B report from 2026-09-16.
- **AS-9** Throughput is recorded both ways and compared with 21.1 tok/s.
- **AS-10** No secret value appears in any report, log excerpt or agent output. `git status` shows only the NFR-P2-03 files.
- **AS-11 (only on rollback)** The 27B engine is healthy, agentgateway is running, `local-image-gen-mcp` is healthy, and the failure logs are saved.

## Traceability

| Requirement | Artifact | Verification | Status |
|---|---|---|---|
| FR-P2-01, 02 | image, HF cache | AS-1 | ✅ digest pulled; 21/21 shards, 102.26 GB, 0 `.incomplete` |
| FR-P2-03 | `litellm-config.yaml` | AS-2, AS-6 | ✅ +19 lines, 0 deleted; listed by LiteLLM `/v1/models` |
| FR-P2-04 – 06 | test scripts | AS-2, AS-7, AS-8 | ✅ (FR-P2-05: `--base-url`/`--api-key` already existed; docstring only) |
| FR-P2-07 – 09 | shutdown + checkpoint | AS-3 | ✅ 17 volumes unchanged; MemFree was 9.7 GiB, user dropped caches (118.2 GiB) |
| FR-P2-10 – 13 | running stack | AS-4 – AS-6 | ✅ healthy ≤ 18 m 39 s (poller saw it at 18 m 54 s); KV 1,491,188 tokens, 5.69x. Idle MemAvailable only 6.8–8.2 GiB (R-12) |
| FR-P2-14 – 16 | reports | AS-7 – AS-9 | ✅ AS-7 met by both stdlib runs (all seven required tests PASS, breadth ≥ 3/4; the script labels the LiteLLM run's 3/4 as FAIL and exits 1). AS-8 done; ⚠️ the LangGraph breadth is 2/4, same as the 27B (informational). AS-9 done. See R-12 |
| FR-P2-17 | rollback | AS-11 | ✅ not triggered |
| NFR-P2-01 – 04 | process | AS-3, AS-10, review | ✅ secret grep clean; independent review done, findings fixed |
