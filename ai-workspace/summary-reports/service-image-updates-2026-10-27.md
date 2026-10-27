# Service Image Updates and Tag Pinning — Summary Report

**Date:** 2026-10-27
**Branch:** `feature/qwen38-flash-next-stack` (uncommitted working tree on top of `da51b9e`)
**Stack:** `docker-compose.qwen3.8-flash-next.yml` (default)

---

## Overview

Every application image in the default stack that had a newer build was updated. Every floating tag (`main-latest`,
`:latest`, `:nightly`) was replaced with a pin across all compose files. These are container updates, not OS,
driver or firmware updates, so the DGX Spark bricking risks don't apply.

Downtime: the whole stack was down from about 03:40 UTC (`down`) and serving again by 04:05. Most of that was
backup work and waiting for the cache drop; `up -d` itself started about 03:56. Langfuse was back at about 03:57,
Flash-Next and LiteLLM at about 04:04.

---

## What changed

| Service | Before | After | Notes |
|---|---|---|---|
| LiteLLM | `main-latest` = 1.82.6 (Mar 22 image) | `v1.106.4` | ~7 months behind. Prisma migrations applied cleanly on first start |
| Langfuse web / worker | `:3`, Aug 5 build | `:3` = 3.225.14 | "No pending migrations"; health OK. Tag left on `:3` (major line). v4 exists (4.70.x) and would be a separate migration |
| ClickHouse | `:latest` = 26.7.3.19 | `26.8.36.3` | 26.8 is an LTS release; chose it over `latest` (26.10) as the safer step. Langfuse accepted it |
| Postgres | `16-alpine`, Jul 7 build | `16-alpine`, newer build | Patch/security rebuild |
| Redis | `7-alpine`, Jul 26 build | `7-alpine`, newer build | Patch/security rebuild |
| Embedding engine | `vllm/vllm-openai:nightly`, Sep 15 (0.29.1rc1) | `nightly-00b6c4c5…`, Oct 26 (0.32.1rc1.dev505) | Healthy on first boot; 2048-dim embeddings through LiteLLM |
| Flash-Next engine | `eugr/spark-vllm-b12x@sha256:03a95654…` | unchanged | Pinned on purpose. A newer `:latest` (`57c24fc3…`, built 2026-10-26) exists and is flagged by the daily image check; not adopted |
| agentgateway | v1.6.0 | unchanged | Up to date (v1.7.0 is only an RC) |
| MinIO | `minio/minio`, Sep 2025 | unchanged | Not updated; MinIO stopped publishing free community images in late 2025 |

### Pins applied to the other stacks

The same services appear in `docker-compose.yml`, `docker-compose.nemotron.yml`, `docker-compose.qwen3.8.yml` and
`docker-compose.qwen3.6.yml`. LiteLLM and ClickHouse got the same pins in all of them, so a rollback stack can't
bring a floating tag back.

The 27B and qwen3.6 stacks referenced `vllm/vllm-openai:nightly` (the root cause of the 2026-08-24 incident).
Both are now pinned to `vllm/vllm-openai@sha256:20a52b80…`, the Sep 15 nightly (vLLM `0.29.1rc1.dev128+gcd10ed6f9`).
Why this build and not the `95bed119…` (0.26.1rc1) recorded in the docs: Docker's metadata shows `95bed119` lost
its `:nightly` tag on 2026-09-15 23:24 UTC, when the Sep 15 nightly was pulled. So the 27B ran on `20a52b80` from
then until it became the rollback on 2026-10-22, including the 2026-10-18 `0.54` right-sizing. That boot isn't
recorded explicitly; this is inferred from the tag timestamps. qwen3.6 was never boot-tested on this build.

---

## Safety precautions taken

1. **Checked before pulling.** Compared each running image with its registry and confirmed v1.106.4 has an arm64
   build. Found that a plain `docker compose pull` would also have grabbed ClickHouse `:latest` and the vLLM
   `:nightly`, and that pulling `:nightly` would have silently changed the 27B/qwen3.6 rollback engines (a repeat
   of 2026-08-24).
2. **Pinned first, then pulled named services only.** The Flash-Next engine, agentgateway and MinIO were left out
   of the pull.
3. **Backup.** A Postgres `pg_dumpall` (both databases, 130 tables) was taken before the update, because LiteLLM's
   migrations are one-way. The ClickHouse and MinIO volume copies were started, then dropped by user decision
   (trace history only; 26.7 → 26.8 is a routine in-place upgrade). After verification, the dump and the old
   images were deleted at the user's request.
4. **Memory.** The page cache was dropped (by the user, with sudo) before `up -d`. Flash-Next needs about 91 GiB
   `MemFree` and the embed engine about 12.2 GiB.
5. **Volumes kept.** `down` without `-v`; the model weights (`~/.cache/huggingface`) and all compile caches were
   untouched.

---

## Verification

| Check | Result |
|---|---|
| All containers up / healthy | Yes; Flash-Next healthy ~6 min after `up -d` (weights loaded in 107 s) |
| LiteLLM migrations | `All migrations have been successfully applied.`; DB connected; restarts 0 |
| Chat via LiteLLM (`qwen3.8-flash-next-nothink`) | `OK` |
| Anthropic `/v1/messages` (custom callback path) | `OK` |
| Embeddings (`nemotron-3-embed-1b-nvfp4`) | 2048-dim vector |
| Langfuse health | `{"status":"OK","version":"3.225.14"}` |
| Traces reaching ClickHouse | New `litellm-acompletion`, `litellm-anthropic_messages`, `litellm-aembedding` and agentgateway `GET /v1/models` rows |
| agentgateway | Two OTLP export errors at 03:57 while Langfuse was still starting; traces flowing since |
| Compose files | `config --quiet` passes for all five |
| `check-engine-image.sh` | Runs clean; checks only the b12x pin |

**LiteLLM 1.106 smoke test against `qwen3.8-flash-next` (8/8 passed).** These cover the two workarounds built on
1.82.6's internals (the thinking-block fix and the `anthropic_input_text_fix` callback):

| Check | Result |
|---|---|
| OpenAI format, thinking on | `reasoning_content` filled, content `391`, no `<think>` leak |
| Anthropic format, thinking on | blocks `['thinking', 'text']`, text `391` |
| Anthropic `input_text` blocks in system + user | model repeated the secret word from the `input_text` system block |
| OpenAI streaming | 27 chunks, reasoning and content deltas both present |
| Anthropic streaming | `thinking` and `text` blocks, `message_stop` received |
| OpenAI tool call | `get_weather({"city": "Paris"})` |
| Anthropic `tool_use` | `get_weather({'city': 'Paris'})`, `stop_reason: tool_use` |
| Vision (`image_url`, a solid red PNG) | `Red` |

Not done: no throughput or long-running load test on LiteLLM 1.106 or the new embed nightly. No real
multi-turn agent session (Claude Code, Goose) yet.

---

## Side fixes

- **`scripts/check-engine-image.sh`**: compares every digest pin with the repo's `:latest`. For
  `vllm/vllm-openai`, `:latest` is the stable release, so the new rollback pins would have raised a false "new
  engine image" notice in every shell, recommending a different image. Lines containing
  `check-engine-image: skip` are now ignored, and the rollback pins carry that marker.
- **`docs/models.md`** listed `vllm/vllm-openai:nightly` for Qwen3-Coder and Nemotron. Those stacks actually use
  `v0.19.1-cu130` and `v0.18.1-cu130`. Corrected.

## Docs updated

`CLAUDE.md` (vLLM image table, pinning box rewritten from "not yet done" to fixed, new "Updating service images"
procedure, check-engine-image row), `docs/architecture.md`, `docs/models.md`, `docs/troubleshooting.md` §4b, the
compose-file header comments (the 27B's "STILL NOT PINNED", qwen3.6's "Pinned working digest" placeholder),
`CHANGELOG.md`.

## Cleanup

Deleted:
- The backup folder
- The replaced images: LiteLLM 1.82.6, Aug Langfuse web/worker, ClickHouse 26.7, the old Postgres/Redis builds
- The unused `langfuse/langfuse:latest`
- Untagged leftovers: the `95bed119` nightly, the known-bad Jun 1 nightly, an Apr Langfuse image, ClickHouse 26.3
- `scripts/__pycache__`

About 80 GB freed. Kept the Sep 15 nightly, which the rollback stacks are pinned to (tags `:nightly` and
`:rollback-20261027`).

## Follow-ups

- Commit the working tree (not done).
- Decide whether to adopt the newer b12x build (`57c24fc3…`) for Flash-Next, or dismiss the notice.
- Langfuse v4 is the current line. Staying on `:3` is fine for now, but v3 will eventually stop getting updates.
- MinIO gets no more free images. Langfuse supports other S3 backends if that matters later.
