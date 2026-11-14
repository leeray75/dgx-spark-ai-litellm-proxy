# Service Image Updates (2026-11) — Summary Report

**Date:** 2026-11-14
**Branch:** `chore/service-images-2026-11-14` (off the Phase 4 commit `e49641d`)
**Spec:** [`docs/specs/service-image-updates-2026-11/`](../../docs/specs/service-image-updates-2026-11/SPECS.md) (Phase 1). Facts are in [research.md](../../docs/specs/service-image-updates-2026-11/research.md) R-1 – R-6.
**Result:** all 7 shared services were updated and verified. **No rollback** was needed, and **no inference engine was restarted**.

---

## Overview

The shared services used by every stack were moved to their current releases. Each service was recreated on its own with `up -d --no-deps`, and the work followed spec-driven development:

- a spec, plan and tasks;
- a Haiku implementer;
- an independent Sonnet reviewer, for up to 5 rounds.

This differs from the 2026-10-27 update, which used a full `down` and `up` plus a sudo cache drop. This time the Flash-Next engine and the embedding engine kept serving the whole time.

| Service | Before | After | How |
|---|---|---|---|
| LiteLLM | v1.106.4 | **v1.109.1** | Pin, in 5 compose files. The cosign signature was verified. |
| agentgateway | v1.6.0 | **v1.7.0** | Pin, in 2 compose files |
| ClickHouse | 26.8.36.3 | **26.8.37.168** | Pin, in 5 compose files (26.8 LTS patch) |
| Langfuse web and worker | 3.225.14 | **3.227.1** | Floating `:3` refreshed |
| Postgres | 16.15 | **16.16** | Floating `16-alpine` refreshed |
| Redis | 7.4.12 | 7.4.12 (rebuilt 2026-11-09) | Floating `7-alpine` refreshed |
| MinIO, both engines | unchanged | — | Out of scope. MinIO has no public image. |

## User decisions

| # | Decision |
|---|---|
| U-1 | New spec folder `docs/specs/service-image-updates-2026-11/`, because these services are shared across stacks |
| U-2 | LiteLLM **v1.109.1**, the newest stable, rather than the 1.106.10 patch line |
| U-3 | Containers only. The LangGraph test venv is not upgraded. |
| U-4 | New branch, one commit, no push |

## Safety measures

- **Release notes checked against the config before any change (R-2, R-3).**
  - None of LiteLLM 1.108/1.109's "Action required" or "Removed" items applies. Fallbacks were already lists, the cache is Redis, and `drop_params` is on.
  - The `max_tokens` cost-map removal was verified: `/model/info` limits are unchanged.
  - agentgateway 1.7's switch to the Responses format doesn't apply, because the vLLM provider declares only `completions`.
- **Supply chain.** `cosign verify` on `ghcr.io/berriai/litellm:v1.109.1` passed, using the BerriAI/litellm key from commit `e82a3c6`. Cosign v3.1.4 was checksum-checked and run from the scratchpad, not installed. Every image has a `linux/arm64` manifest.
- **Backups,** in `~/backups/service-images-20261114/` (dir 700, files 600):
  - `pg_dumpall` (170 tables; `gunzip -t` OK);
  - a dump of each database (`litellm`, and the Langfuse DB `postgres`), so each can be restored on its own;
  - an online SQLite backup of agentgateway's `data.db` (`integrity_check` = ok).
- **Rollback images.** Before pulling, every running image was tagged as `local/rollback:<container>-20261114`. A rollback for a floating tag therefore doesn't depend on the registry.
- **Pull by name only.** Never a bare `pull`, never the engines or MinIO.

## Apply (UTC)

| Time | Step | Result |
|---|---|---|
| 22:22:55 | `postgres redis clickhouse` | All healthy by 22:23:14 |
| 22:23:33 | `langfuse-worker` | Running, "No background migrations to run" |
| 22:24:48 | `langfuse-web` | Healthy, 3.227.1. 425 Prisma migrations, all applied. |
| 22:25:16 | `litellm` | Ready at 22:25:30, so port 4000 was down for about 14 s. 225 migrations, all applied. No config warnings. |
| 22:25:38 | `agentgateway` | 1.7.0. Request-log schema migrated, listener up. Port 4100 was down only while the container was recreated; the exact window wasn't measured. |

- After the apply, every recreated service had 0 restarts and no container was OOM-killed.
- `qwen3-8-flash-next-fp4-engine`, `nemotron-embed-engine` and `langfuse-minio` have the same `StartedAt` as before.
- All 23 volumes are intact.

## Verification

The same stdlib `battery.py` was run before (22:19) and after (22:26):

| Check | Baseline | After |
|---|---|---|
| LiteLLM: OpenAI thinking (no `<think>` leak); Anthropic thinking blocks; `input_text` callback plus a control; OpenAI and Anthropic streaming (`message_stop`); OpenAI tool call and Anthropic `tool_use`; vision | 9/9 PASS | 9/9 PASS |
| Claude Code alias `claude-qwen3.8-flash-next` through `/v1/messages` | PASS | PASS |
| Embeddings (2048 dims), `/v1/models` aliases, `/model/info` limits 262144 / 262144 | PASS | PASS |
| agentgateway chat on :4100 | PASS | PASS |
| New ClickHouse traces (LiteLLM and `agentgateway-trial`) | PASS | PASS |
| New LiteLLM spend rows with cost > 0 | PASS (10/10) | PASS (10/10) |
| agentgateway cost-overlay log has no error | FAIL (pre-existing 2026-10-27 file-watch warning) | PASS (fresh log; negative-only check, plus a positive `watching model catalog files` line) |
| **Total** | **16 / 1** | **17 / 0** |

| Test script | Baseline | After |
|---|---|---|
| Agentic, through LiteLLM | 9 PASS, 1 WARN | 9 PASS, 1 WARN |
| Agentic, through agentgateway | 10 PASS | 9 PASS, 1 WARN (Small-budget is informational: an empty result versus `\n\n` at max_tokens=20) |
| LangGraph, through LiteLLM | 5 PASS, 1 WARN | 5 PASS, 1 WARN |
| Reasoning effort (default `medium`, https kept) | PASS | PASS |

For the no-think timing (8.15 s → 13.25 s median), see the caveat below. No check that passed on the baseline fails after.

## Review loop

| Round | Verdict | Findings | Implementer response |
|---|---|---|---|
| 1 | CHANGES REQUESTED | **F1 (major):** the docs blamed Phase 4's `e49641d` for the leaked master key; the right commit is `ee78f38` (2026-08-23). F2–F6 (minor or nit): a wrong description of the first invalid baseline run, one table cell, check 16 being negative-only, an upstream commit attribution, and an unexplained no-think timing | All 6 fixed, none declined |
| 2 | APPROVE | N1 (minor): "line 565" was the working-tree line, not the committed one | Fixed. The line number was removed in favour of the stable "2026-08-23 entry". |

The reviewer independently checked:
- the versions, by querying each service;
- the engines' `StartedAt`, the rollback tags, and the backups and their permissions;
- the migration log lines;
- that the trace and spend checks count only rows newer than each run;
- that the baseline was run in full before the apply;
- `config --quiet` on all 6 compose files;
- a count-only secret grep, which found 0 secrets in the diff, the spec and the scratchpad.

## Files changed

- Compose pins, with trailing comments updated: `docker-compose.yml`, `docker-compose.nemotron.yml`, `docker-compose.qwen3.6.yml`, `docker-compose.qwen3.8.yml`, `docker-compose.qwen3.8-flash-next.yml` and `docker-compose.agentgateway.yml`.
- `CLAUDE.md`: the current pins, plus the variant of "Updating service images" that recreates services one at a time.
- `docs/architecture.md` and `CHANGELOG.md`.
- `docs/specs/service-image-updates-2026-11/` (new).
- This report.

## Rollback (per service)

Each service's old image is available as `local/rollback:<container>-20261114`.

- **agentgateway:**
  1. Restore the `v1.6.0` pins.
  2. Copy the backup over `agentgateway/data/data.db`.
  3. Run `./scripts/flash-next-compose.sh up -d --no-deps agentgateway`.
- **LiteLLM or Langfuse:** their migrations are one-way.
  1. Stop the service.
  2. Restore only its database with `pg_restore` from `~/backups/service-images-20261114/`.
  3. Restore the old pin or image, then run `up -d --no-deps`.
  4. Langfuse ran no ClickHouse schema migration this time.
- **Postgres, Redis or ClickHouse:** point the service at the `local/rollback:` image, then run `up -d --no-deps`.

## Open items

| Item | Owner |
|---|---|
| **Security (from before this work):** the `LITELLM_MASTER_KEY` value is committed in `CHANGELOG.md` (the 2026-08-23 entry) and in `ai-workspace/summary-reports/qwen3.8-27b-nvfp4-stack-2026-08-23.md`. Both come from commit `ee78f38`, which is pushed to `origin`. **Rotate the key.** Scrubbing the files doesn't remove it from history. | user |
| agentgateway has no MCP session key: `failed to write generated session key … Read-only file system`, because the config is mounted `:ro`. This was already the case on 1.6.0. R-3 assumed the key would go to the DB, which was wrong. Set `config.session.key` or `SESSION_KEY` before re-enabling `/mcp/image-gen`. | future change |
| No-think latency went from 8.15 s to 13.25 s median, but with n=2 and different output lengths (330–841 tokens) this is inconclusive. Re-check under real traffic, or with more trials. | optional |
| Delete the backups and the `local/rollback:*-20261114` images once you trust the new versions. | user |
| The LangGraph test venv is behind (langgraph 1.2.11 → 1.2.22; langchain-core and langchain-openai 1.6 → 1.8). Out of scope (U-3). | optional |
