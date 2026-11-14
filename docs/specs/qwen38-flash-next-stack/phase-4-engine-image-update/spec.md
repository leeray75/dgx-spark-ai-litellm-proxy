# Qwen3.8-Flash-Next stack · Phase 4 — Engine image update

| | |
|---|---|
| **Index** | [../SPECS.md](../SPECS.md) (all phases) |
| **Status** | Implemented 2026-11-14 (T001–T015): **KEEP**. Engine on `19ab778d…`; decode median −4.0% vs baseline, no FR-P4-12 trigger. Reviewed in 2 rounds (both APPROVE; round-1 findings fixed or declined with a reason). Summary report: `ai-workspace/summary-reports/flash-next-engine-image-update-2026-11-14.md`. |
| **Date** | 2026-11-14 |
| **Depends on** | Phase 3 ✅: Flash-Next is the default stack, `scripts/flash-next-compose.sh`, `scripts/check-engine-image.sh`; shared [../research.md](../research.md) R-1 – R-14 (image facts R-3a, boot facts R-12) |
| **Supersedes** | R-3a's *Digest* row and P2 FR-P2-01's pinned digest: the engine moves from `sha256:03a95654…` (built 2026-10-15) to `sha256:19ab778d…` (built 2026-11-02) **only if** this phase's acceptance passes. On rollback nothing is superseded. |
| **Next** | [plan.md](plan.md) → [tasks.md](tasks.md) |

## Problem

The daily image check (`scripts/check-engine-image.sh`, systemd user timer) has reported since 2026-11-10 that `eugr/spark-vllm-b12x:latest` now points to a newer build than the one pinned in `docker-compose.qwen3.8-flash-next.yml`:

| | Digest | Created |
|---|---|---|
| Pinned (running) | `sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595` | 2026-10-15 |
| `:latest` | `sha256:19ab778dd57f019c44caf5df91a671cf688923d1ca9fa8ce92be0c9acb46d215` | 2026-11-02 |

The image is a community build that this checkpoint needs: upstream vLLM can't read its `csf` NVFP4 scale encoding. The new build has no changelog. Its labels and environment match the pinned one: CUDA 13.0.2, NCCL 2.28.3, `TORCH_CUDA_ARCH_LIST=12.1a`, `VLLM_BASE_DIR=/workspace/vllm`. The difference is therefore unknown and can only be judged by booting and testing it.

## Goal

Swap the Flash-Next engine to the new build with minimum downtime, measure it against a fresh baseline from the current build, and either keep it (pin updated, docs updated) or roll back to the old digest automatically on the user's rollback criteria.

## User decisions (2026-11-14)

| # | Question | Decision |
|---|---|---|
| U-1 | Where the spec lives | **Phase 4 of the existing `qwen38-flash-next-stack` spec**, sharing `research.md` (new entry R-15). |
| U-2 | Rollback triggers | **Boot failure or regression.** Roll back if the engine isn't healthy within 60 min, exits, or is OOM-killed, or if a required test fails, or if decode throughput drops by more than 10% against the baseline measured just before the swap (FR-P4-12). |
| U-3 | Memory gate | **Human checkpoint.** Stop the engine and read `MemFree`. If it's below the threshold, hand back so the user can drop caches with sudo, then resume. |
| U-4 | Git | **New branch `chore/engine-image-2026-11-02` off the current HEAD** (`feat/flash-next-reasoning-effort-medium`, 93ce690). Commit at the end. No push and no PR. |

## Scope

**In scope**
- Pull the new image by digest while the current engine keeps serving.
- Measure a baseline on the current image.
- Change the pin in `docker-compose.qwen3.8-flash-next.yml`.
- Recreate **only** the `qwen3-8-flash-next-fp4-engine` service.
- Test the new image, then keep it or roll back.
- Update the docs and the spec, and commit.

**Out of scope**
- Every other service in the stack: no restart and no image change.
- The rollback stacks (`docker-compose.qwen3.8.yml`, `qwen3.6`) and the embedding engine.
- Any change to engine flags, `gpu-memory-utilization`, LiteLLM, agentgateway or prices. Prices are energy per token. If throughput changes materially, the report recommends re-running the `llm-power-cost` measurement but does not change prices.
- Deleting the old image. It stays local as the instant rollback target.
- Host packages, drivers, firmware, reboot.

## Functional requirements

### Preparation (no disruption)

- **FR-P4-01** Pull `eugr/spark-vllm-b12x@sha256:19ab778dd57f019c44caf5df91a671cf688923d1ca9fa8ce92be0c9acb46d215` by digest. Never pull `:latest`. Check that the local image is `arm64`, and record its size and creation time.
- **FR-P4-02** Baseline on the **current** image, run while it still serves:
  - (a) Run `scripts/test-agentic-capabilities.py --base-url http://localhost:8301/v1 --model qwen3.8-flash-next` **3 times**. Save the reports as `ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-engine-baseline-20261114-run{1,2,3}.json`.
  - (b) For each run, record the PASS/WARN/FAIL of every test and the *Decode throughput* tok/s.
  - (c) The **baseline throughput** is the median of the three tok/s values.
  - (d) Record the vLLM log `Avg generation throughput` non-zero samples during the runs (median). This value is informational only.
- **FR-P4-03** Record the engine's `StartedAt` and image ID, plus `docker ps` (name, image, state), `docker volume ls -q` and `/proc/meminfo` (MemTotal, MemFree, MemAvailable, Cached, Buffers, SwapFree).
- **FR-P4-04** Edit `docker-compose.qwen3.8-flash-next.yml`. Change only the digest on the engine's `image:` line and the comment block directly above it. The comment MUST name the new build date and keep the old digest written out in full as the rollback target. No other line may change. `docker compose config` (through the wrapper, output kept in the scratchpad) MUST succeed. The running container is not affected until FR-P4-07.

### Swap

- **FR-P4-05 Idle check.** Check that there is no `Running: [1-9]` in the engine log over the last 2 minutes. If there is, poll every 60 s for up to 10 minutes, then proceed and note it in the report.
- **FR-P4-06 Stop and memory checkpoint.**
  - Run `./scripts/flash-next-compose.sh stop qwen3-8-flash-next-fp4-engine`, then read `/proc/meminfo`.
  - If `MemFree` is **below 95 GiB**, the implementer MUST stop and hand back to the caller with the meminfo numbers. The caller asks the user to run `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'`. Resume only once `MemFree` ≥ 95 GiB, or once the user explicitly says to go ahead.
  - Why 95 GiB: vLLM's startup check needs `0.75 × 121.7 ≈ 91.3 GiB` free, and on GB10 that tracks `MemFree` (R-11, R-12). The 95 GiB threshold adds a margin to that. It is lower than the 105 GiB full-stack gate because the embedding engine and observability services stay up.
- **FR-P4-07 Boot.** Run `./scripts/flash-next-compose.sh up -d --no-deps qwen3-8-flash-next-fp4-engine`.
  - Poll `docker inspect -f '{{.State.Status}} {{.State.Health.Status}}'` every 30 s, with a limit of 60 minutes from `up`.
  - Do the polling in the background or with an until-loop, never with long foreground sleeps.
  - Watch the logs for `Traceback`, `Error`, `OOM` and container exit.
- **FR-P4-08 Boot facts.** Record:
  - the time from `up` to healthy;
  - the weights memory and model-loading time;
  - the KV cache GiB and tokens, and "Maximum concurrency";
  - whether the compile and b12x caches were reused or rebuilt;
  - the vLLM version string, if logged;
  - `/proc/meminfo` once healthy and idle;
  - `OOMKilled` for every container;
  - that all other services kept their `StartedAt`, so they were not restarted.
- **FR-P4-09** Run `GET :8301/v1/models` and LiteLLM `GET :4000/v1/models` (master key from `.env`, never printed). Both MUST list `qwen3.8-flash-next`.

### Tests

- **FR-P4-10** Run the same command as FR-P4-02(a), 3 times, against the new image. Save the reports as `…-engine-new-20261114-run{1,2,3}.json`. Record the results the same way as FR-P4-02(b)–(d).
- **FR-P4-11** Run `scripts/test-agentic-capabilities.py --model qwen3.8-flash-next` through LiteLLM once. Save the report as `…-litellm-new-20261114.json`. Then run `scripts/test-reasoning-effort.py --expect-default medium --skip-behavior`, which checks that the server-side default chat-template kwargs survive the new image.

### Decision

- **FR-P4-12 Keep or roll back (U-2).** Roll back if any of these is true:
  - (a) The engine is not healthy within 60 minutes of `up`, the container exits, or any container has `OOMKilled=true`.
  - (b) `MemAvailable` stays below 3 GiB for 2 minutes or more after the engine is healthy.
  - (c) A **required test** FAILs in any FR-P4-10 or FR-P4-11 run, unless that same test also FAILed in at least one baseline run, which marks it as a pre-existing flake. The required tests are Connectivity, Reasoning presence, Single tool call, Multi-turn tool context, No hallucinated calls, Streaming reconstruction and Vision.
  - (d) The median new decode throughput is below 0.90 × the baseline median.
  - (e) `test-reasoning-effort.py` reports a default other than `medium`.

  Tool-selection breadth and Small-budget are informational, because they are known to be noisy (R-12). They are recorded but never trigger a rollback.
- **FR-P4-13 Rollback steps.**
  1. Save the last 300 engine log lines to the scratchpad.
  2. Restore the old digest in the compose file with `git checkout -- docker-compose.qwen3.8-flash-next.yml`.
  3. Stop the engine and apply the FR-P4-06 memory checkpoint again.
  4. Run `up -d --no-deps qwen3-8-flash-next-fp4-engine` and wait until it is healthy.
  5. Re-run one engine stdlib test to confirm.
  6. Run `scripts/check-engine-image.sh dismiss`, so that the rejected build stops being announced.
  7. The new image stays local for later investigation. The docs record the failed attempt in R-15 and the CHANGELOG. `CLAUDE.md`'s image table is not changed.
- **FR-P4-14 On keep:**
  - Run `scripts/check-engine-image.sh` (check mode). Its notice MUST be gone, which confirms that the pin now equals `:latest`.
  - Update the image row in `CLAUDE.md` (line ~170), `docs/architecture.md` (engine table) and the R-3a *Digest* row. For R-3a, add a dated note next to the row and leave the original text in place.
  - Add a CHANGELOG entry.

### Close-out

- **FR-P4-15** Append `## R-15 (P4) Engine image update to 19ab778d (2026-11-14)` to the shared `research.md`. It records the image facts, baseline and new results (a per-test table), the throughput comparison, the boot facts, the decision and, if the image was rolled back, why.
- **FR-P4-16** Update this spec's traceability table and status. Update `../SPECS.md`: the Phases table row, Deliverables and Open items.
- **FR-P4-17** Write the summary report `ai-workspace/summary-reports/flash-next-engine-image-update-2026-11-14.md`.
- **FR-P4-18** Commit everything on `chore/engine-image-2026-11-02` with one commit. The message MUST end with the repository's attribution line. Do not push.

## Non-functional requirements

- **NFR-P4-01 Allowed Docker actions.**
  - Allowed: `docker pull` by digest; through the wrapper, `stop`, `up -d --no-deps` and `config` for the engine service only; and read-only commands (`ps`, `inspect`, `logs`, `images`, `volume ls`, `buildx imagetools inspect`).
  - Not allowed: `down`; a bare `up`; any `--volumes`, `-v`, `--rmi` or `prune`; `docker rmi` of either engine image; restarting any other service; `apt`, `fwupdmgr`, driver changes or a reboot.
  - `sudo` is run only by the user.
- **NFR-P4-02 Secrets.** `.env` values, `LITELLM_MASTER_KEY`, `HF_TOKEN` and `AGW_LANGFUSE_BASIC_AUTH` are never printed, logged or written to reports. Rendered `compose config` output stays in the scratchpad.
- **NFR-P4-03 Files changed.** Only these:
  - `docker-compose.qwen3.8-flash-next.yml`, `CLAUDE.md`, `docs/architecture.md` and `CHANGELOG.md`;
  - the shared `research.md`, `../SPECS.md` and this phase folder;
  - the new report JSONs under `ai-workspace/reports/`;
  - the summary report.
- **NFR-P4-04 Downtime.** The engine is down only between FR-P4-06 and healthy, plus once more on a rollback. Every other service keeps running.

## Decisions

- **D-1 Engine-only recreate.** `up -d --no-deps <engine>` touches nothing else. LiteLLM and agentgateway resolve the engine by its container name on `ai-bridge`, so they need no restart. During the swap, requests fail instead of queueing.
- **D-2 A fresh baseline on the same day, n=3.** The R-12 numbers were measured at util 0.80 and before `reasoning_effort` was set to medium, so they are not comparable. Three runs on each side, using the median, keep one noisy run from triggering or hiding a 10% regression.
- **D-3 The old image stays local.** A rollback needs no download, and the compile caches keyed to the old build remain in the named volumes.
- **D-4 95 GiB gate, not 105 GiB.** See FR-P4-06.
- **D-5 Flakes don't trigger a rollback.** A required test that already FAILed on the baseline is a pre-existing flake (FR-P4-12c). Breadth and Small-budget are informational.

## Acceptance scenarios

- **AS-1** The new digest is local (`arm64`) and both digests are listed by `docker images --digests`. The three baseline reports exist. The compose diff changes only the engine's `image:` line and its comment, and `compose config` succeeds.
- **AS-2** The engine is healthy on the new image ID within 60 minutes. Every other container's `StartedAt` is unchanged. No container has `OOMKilled`. `docker volume ls -q` matches the baseline.
- **AS-3** Both `/v1/models` endpoints list `qwen3.8-flash-next`.
- **AS-4** The three new engine runs and one LiteLLM run exist, and their results are tabulated against the baseline. No FR-P4-12 trigger is hit, or a rollback was carried out (AS-6).
- **AS-5** On keep: the check script reports no new image. `CLAUDE.md`, `docs/architecture.md`, R-3a, R-15 and the CHANGELOG name `19ab778d…`. The compose comment keeps `03a95654…` as the rollback target.
- **AS-6** On rollback only: the engine is healthy on `03a956544e9f`, one confirmation run passes, the compose file has no diff, the notice is dismissed, and the logs are saved.
- **AS-7** No secret appears in any report, doc or agent output. `git status` after the commit is clean, and the commit touches only NFR-P4-03 files.

## Traceability

| Requirement | Artifact | Verification | Status |
|---|---|---|---|
| FR-P4-01 – 04 | image (`19ab778d…`, arm64, created 2026-11-02), 3 baseline reports, compose diff (comment + `image:` only), `config` rendered to scratchpad | AS-1 | ✅ |
| FR-P4-05 – 09 | idle check (~2 min); stop + checkpoint (MemFree 5.59 GiB → user drop → 111.29 GiB); `up` healthy in 7 m 32 s; boot facts; `/v1/models` on both endpoints | AS-2, AS-3 | ✅ |
| FR-P4-10 – 11 | 3 new engine reports, LiteLLM report, `test-reasoning-effort` default `medium` | AS-4 | ✅ |
| FR-P4-12 – 14 | decision KEEP (`scratchpad/phase4/decision.md`); check script "No new engine image."; CLAUDE.md, architecture.md, R-3a note, CHANGELOG. FR-P4-13 n/a | AS-4, AS-5 | ✅ |
| FR-P4-15 | research.md R-15 appended; R-3a dated note | AS-5 | ✅ |
| FR-P4-16 | this spec's traceability and status; SPECS.md Phases row, Deliverables and Open items | AS-7 | ✅ |
| FR-P4-17 – 18 | summary report, one commit | AS-7 | ⏳ (T017–T018, orchestrator) |
| NFR-P4-01 | Docker actions: `pull` by digest; wrapper `stop`/`up -d --no-deps`/`config` on the engine only; no `down`, `-v`, `rmi`, prune or other service restarts (`StartedAt` check) | AS-2 | ✅ |
| NFR-P4-02 | secret grep (T015). New reports, the docs and the compose file contain no secret, except for one **pre-existing** hit: the LiteLLM master key value is already in the committed `CHANGELOG.md` at HEAD (line 554, added in commit ee78f38, 2026-08-23) and in `ai-workspace/summary-reports/qwen3.8-27b-nvfp4-stack-2026-08-23.md` (same commit). This phase added no secret and did not edit that line (NFR-P4-03, no-delete rule). Finding for the user: rotate the key and scrub it. | AS-7 | ⚠️ (T015) |
| NFR-P4-03 | files changed: see `git status` (T015) | AS-7 | ✅ (T015) |
| NFR-P4-04 | engine down 20:54:35Z → 21:05:08Z (10 m 33 s, incl. the cache-drop wait); other services never stopped | AS-2 | ✅ |

**Deviations (T001–T015):** the T005 idle check took about 2 minutes (within the 10-minute limit). During the T007 boot, a second health poller was started while the first was still running for about 3 minutes, so `phase4/health.log` has interleaved lines for those minutes. The data is unaffected. The P2 spec's FR-P2-01 dated supersession note was not added because that file is outside NFR-P4-03 (see SPECS.md Open items).
