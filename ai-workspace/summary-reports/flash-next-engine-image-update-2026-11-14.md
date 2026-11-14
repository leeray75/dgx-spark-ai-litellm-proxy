# Flash-Next Engine Image Update — Summary Report

**Date:** 2026-11-14
**Branch:** `chore/engine-image-2026-11-02` (off `feat/flash-next-reasoning-effort-medium` @ `93ce690`)
**Spec:** [`docs/specs/qwen38-flash-next-stack/phase-4-engine-image-update/`](../../docs/specs/qwen38-flash-next-stack/phase-4-engine-image-update/spec.md) (Phase 4). Facts are in [research.md R-15](../../docs/specs/qwen38-flash-next-stack/research.md).
**Result:** **KEPT.** The Flash-Next engine now runs `eugr/spark-vllm-b12x@sha256:19ab778d…` (built 2026-11-02).

---

## Overview

From 2026-11-10 on, the daily image check (`scripts/check-engine-image.sh`) reported that `eugr/spark-vllm-b12x:latest` had moved past the pinned build. The new build has no changelog. Its CUDA, NCCL and architecture settings match the old one, so the only way to judge it was to boot it and test it. The swap followed spec-driven development:

- spec, plan and tasks;
- a Haiku implementer;
- an independent Sonnet reviewer, with up to 5 review rounds;
- one human checkpoint for the sudo cache drop.

| | Digest | Built |
|---|---|---|
| Before | `sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595` | 2026-10-15 |
| After | `sha256:19ab778dd57f019c44caf5df91a671cf688923d1ca9fa8ce92be0c9acb46d215` | 2026-11-02 |

The new vLLM version string is `0.1.dev21830+g8244d1c44.d20261102`. The old image is still local as the rollback target, and the compose comment gives its full digest.

## User decisions

| # | Decision |
|---|---|
| U-1 | Phase 4 of the existing `qwen38-flash-next-stack` spec |
| U-2 | Roll back on a boot failure, a required-test FAIL, or a decode-throughput drop of more than 10% |
| U-3 | Human checkpoint for the memory gate. The threshold is set at MemFree ≥ 95 GiB, not 105 GiB, because only the engine restarts and it needs about 91.3 GiB. |
| U-4 | New branch, one commit, no push |

## Results

Three engine-direct runs were made on each image, plus one run through LiteLLM on the new image.

| Test | Old ×3 | New ×3 | New via LiteLLM |
|---|---|---|---|
| Connectivity, Reasoning, Single tool, Multi-turn, No hallucinated calls, Streaming, Vision | all PASS | all PASS | all PASS |
| Tool-selection breadth (informational) | 4/4, 4/4, 4/4 | 4/4, 4/4, 4/4 | 4/4 |
| Small-budget (informational) | WARN ×3 | WARN, WARN, PASS | PASS |
| Decode tok/s | 42.7 / 42.4 / 40.5 → **median 42.4** | 40.1 / 40.7 / 41.7 → **median 40.7** | 42.1 |
| vLLM log `Avg generation throughput`, median (11 samples each) | 43.1 | 42.1 | — |

- Decode throughput is **−4.0%**. That is within the noise between runs and well above the 38.16 tok/s rollback limit.
- `test-reasoning-effort.py` reports the default is still `medium`.

### Boot and memory

| | 2026-10-22 boot (old, 0.75) | 2026-11-14 boot (new, 0.75) |
|---|---|---|
| `up` → healthy | ~5 min (warm caches) | 7 m 32 s (b12x: 207 cache entries reused, 126 compiled) |
| Weights | 70.32 GiB | 70.32 GiB (load took 194 s) |
| KV cache | 16.7 GiB / 888,648 tokens / 3.39x | **18.44 GiB / 981,083 tokens / 3.74x** |
| MemAvailable, healthy and idle | ~20.8 GiB | 18.35 GiB (17.6–17.9 GiB during the tests) |

- No container was OOM-killed.
- Only the engine's `StartedAt` changed. The other 14 containers were not restarted, and the 23 volumes are unchanged.
- Engine downtime was about **10.5 min** (stop at 20:54:35Z, healthy at 21:05:08Z). That includes the wait for the cache drop.
- After the swap, `check-engine-image.sh show` prints "No new engine image."

## Timeline (UTC)

| Time | Event |
|---|---|
| ~20:49 | New image pulled by digest (27.6 GB; most layers were shared) |
| 20:50–20:52 | 3 baseline runs on the old image |
| 20:54:35 | Engine stopped. MemFree was 5.59 GiB, so the run paused at the ⛔ checkpoint |
| ~20:57 | User dropped caches; MemFree was then 111.29 GiB |
| 20:57:36 | `up -d --no-deps qwen3-8-flash-next-fp4-engine` |
| 21:05:08 | Engine healthy |
| after 21:05 | 3 new engine runs, 1 LiteLLM run, reasoning-effort check. Decision: KEEP |

## Review loop

| Round | Verdict | Findings | Implementer response |
|---|---|---|---|
| 1 | APPROVE | F1 container count (22 → 14); F2 the leak was attributed to the wrong commit (93ce690 → ee78f38); F3 line 558 → 554 at HEAD; F4 stale KV figures in `docs/architecture.md`, `docs/models.md` and `docs/troubleshooting.md`; F5 two R-15 values had no saved evidence | F1–F3 and F5 fixed. F4 fixed in `architecture.md` with a dated note. `models.md` and `troubleshooting.md` were **declined** because they are outside the NFR-P4-03 file list, and logged as an Open item instead. |
| 2 | APPROVE | none | — |

The reviewer independently checked:
- every per-test result and tok/s value against the 7 report JSONs, and recomputed the medians;
- the boot-log figures and the meminfo conversions;
- the live image ID and health;
- the `StartedAt` and volume lists;
- the file list against NFR-P4-03;
- a count-only secret grep of the diff and the new files, which found 0 secrets.

## Files changed

- `docker-compose.qwen3.8-flash-next.yml`: the engine's `image:` digest and its comment, which keeps the rollback digest.
- `CLAUDE.md` (image table row), `docs/architecture.md` (engine row, plus a dated KV note) and `CHANGELOG.md` (`[Unreleased] › Changed`).
- `docs/specs/qwen38-flash-next-stack/`:
  - `SPECS.md`: the Phase 4 row, Deliverables and Open items;
  - `research.md`: a dated note under R-3a and the new R-15;
  - `phase-4-engine-image-update/`: spec, plan and tasks.
- `ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-engine-{baseline,new}-20261114-run{1,2,3}.json` and `…-litellm-new-20261114.json`.
- This report.

## Rollback

```bash
# 1. Restore the old pin. The digest is in the compose comment, or use: git revert <this commit>
# 2. Swap the engine:
./scripts/flash-next-compose.sh stop qwen3-8-flash-next-fp4-engine
# if MemFree < 95 GiB: sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
./scripts/flash-next-compose.sh up -d --no-deps qwen3-8-flash-next-fp4-engine
```

## Open items

| Item | Owner |
|---|---|
| **Security (from before this phase):** the LiteLLM master key is committed in `CHANGELOG.md` (HEAD line 554) and in `ai-workspace/summary-reports/qwen3.8-27b-nvfp4-stack-2026-08-23.md`. Both come from commit `ee78f38` (2026-08-23), which was pushed to `origin` on several branches. **Rotate `LITELLM_MASTER_KEY`.** Removing it from the files alone doesn't help, because it stays in history. | user |
| `docs/models.md:19` and `docs/troubleshooting.md:217` still give the old KV figures (16.7 GiB / 888,648 / 3.39x) | next docs edit |
| Supersession note next to P2 FR-P2-01's digest (P2 spec is outside NFR-P4-03) | next edit of the P2 spec |
| Prices are energy per token, and decode is about 4% slower. That is within the noise, so there was no re-measurement. Re-run `llm-power-cost` after about a day of real traffic if you want to confirm. | optional |
| The old image `03a95654…` (28.1 GB) is still local as the rollback. Remove it with `docker rmi` once you trust the new build. | user |
