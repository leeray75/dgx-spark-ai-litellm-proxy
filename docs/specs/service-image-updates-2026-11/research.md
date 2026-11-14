# Service image updates (2026-11) — Research

Shared facts, gathered on 2026-11-14 with read-only commands: registry metadata through `docker buildx imagetools inspect`, the GitHub releases API, and Docker Hub tags. Nothing was pulled.

## R-1 Running versus available (2026-11-14)

| Service (container) | Compose reference | Running | Available | Pinning style |
|---|---|---|---|---|
| LiteLLM (`litellm-proxy`) | `ghcr.io/berriai/litellm:v1.106.4` | 1.106.4 | **v1.109.1** (2026-11-12; the stable line, which backports security fix #51254 to 1.109.0). Also available: 1.108.9 (LTS line) and 1.106.10 | Exact version tag, in **5 compose files** |
| agentgateway (`agentgateway`) | `cr.agentgateway.dev/agentgateway:v1.6.0` | 1.6.0 | **v1.7.0** (2026-10-27), with an arm64 manifest | Exact version tag, in **2 files**: Flash-Next and `docker-compose.agentgateway.yml` |
| ClickHouse (`langfuse-clickhouse`) | `clickhouse/clickhouse-server:26.8.36.3` | 26.8.36.3 | **26.8.37.168** (2026-11-14, a patch on the 26.8 LTS line) | Exact version tag, in **5 files** |
| Langfuse web and worker (`langfuse`, `langfuse-worker`) | `langfuse/langfuse:3`, `langfuse/langfuse-worker:3` | 3.225.14 (image from 2026-10-26) | **3.227.1** (2026-11-10) | Floating major tag (`:3`), kept that way per `CLAUDE.md` |
| Postgres (`langfuse-postgres`) | `postgres:16-alpine` | 16.15 | **16.16** (2026-11-12) | Floating major tag |
| Redis (`langfuse-redis`) | `redis:7-alpine` | 7.4.12 | 7.4.12, rebuilt 2026-11-09 | Floating major tag |
| MinIO and mc | `minio/minio`, `minio/mc` | Sep 2025 build | none: Docker Hub returns `pull access denied`, and MinIO stopped free community images in late 2025 | **Excluded** |
| Flash-Next engine and embedding engine | digest / dated nightly | — | — | **Excluded** (engines) |

Compose service names: `postgres`, `redis`, `clickhouse`, `langfuse-web`, `langfuse-worker`, `litellm`, `agentgateway`. `litellm-proxy` has `restart: always`. Every other service is `unless-stopped`.

## R-2 LiteLLM 1.106.4 → 1.109.1: release-note actions checked against `litellm-config.yaml`

There is no 1.107 line. The 1.108.0 notes are a raw PR list; 1.109.0 has a structured "Action required" section and a "Removed" list.

| Action or removal | Applies here? |
|---|---|
| String fallback targets must be lists (#48943) | No. `default_fallbacks: ["qwen3.8-flash-next"]` is already a list. |
| The `disk` cache backend was removed (#48114) | No. `cache_params.type: redis`. |
| `rpm` caps now need `optional_pre_call_checks` (#48873) | No. No `rpm` is set. |
| Gemini sampling params; Lens Helm chart | No. Not used here. |
| Responses-only fields bridged to chat (1.108.7, #48655) | No. `drop_params: true` is set, and `enable_responses_api: false`. |
| Azure/tenant request tags must move to metadata (1.108.6, #51254) | No. |
| The legacy `max_tokens` **cost-map** field was removed (#48471) | **Verify.** The three Flash-Next entries set `model_info.max_tokens: 262144` alongside `max_input_tokens` and `max_output_tokens`. This should be ignored at worst. Check that the proxy starts cleanly and that the `/v1/models` and `/model/info` context limits are still right. |
| `dall-e` support was removed; the old usage UI page was removed | No. |

Changes that touch paths this repo uses, to cover in verification:
- Many `/v1/messages` bridge fixes, including streamed bridged spend, `input_tokens` in `message_start`, and canceled streams. The `anthropic_input_text_fix` callback and the Claude Code path (`claude-qwen3.8-flash-next`) must be re-tested.
- `CustomLogger` now receives only the async failure hook on async failures (#47124). The repo callback implements only `async_pre_call_hook`, so this should be unaffected.
- The pre-migration check is now a rolled-back dry run (#48961). The Prisma migrations are **one-way**, so a Postgres backup is mandatory before the first start.
- The native Langfuse callback (`success_callback: ["langfuse"]`) is used, not `langfuse_otel`. The OTel v2 changes don't apply.

Supply chain: LiteLLM 1.82.7 and 1.82.8 on PyPI were compromised (March 2026, per `CLAUDE.md`). Images since then are cosign-signed with the key in BerriAI/litellm commit `e82a3c6`:

```
cosign verify --key https://raw.githubusercontent.com/BerriAI/litellm/e82a3c646908ba0a6ee0beddc4310d7a6cac4065/cosign.pub ghcr.io/berriai/litellm:v1.109.1
```

`cosign` isn't installed on the host.

## R-3 agentgateway 1.6.0 → 1.7.0: breaking changes checked against `agentgateway/config.yaml`

| Change | Applies here? |
|---|---|
| `AGENTGATEWAY_MESSAGES_PREFER_COMPLETIONS` removed; Messages requests prefer Responses when the provider supports it | No. `vllm-qwen38-flash` is a `custom` provider that declares only `completions` (see the comment in `config.yaml`). |
| MCP sessions are always encrypted in standalone mode; the key is stored in the config file or DB | Low. The config is mounted `:ro`, and the DB `sqlite:///data/data.db` is writable, so the key goes to the DB. `/mcp/image-gen` is unused while Flash-Next runs. |
| Prompt guards scan tool output; CEL header lists; loopback blocked for dynamic backends; `serviceTier` normalized | No. None of these is configured. |
| Error responses carry fewer details | Cosmetic |
| Request-log DB migration on startup (backfill) | `agentgateway/data/data.db` is about 31 MB. Back it up first. **The migration is one-way:** rolling back means restoring the backup. |

## R-4 Procedure from the 2026-10-27 update (`ai-workspace/summary-reports/service-image-updates-2026-10-27.md`, `CLAUDE.md` "Updating service images")

- Change pins in **every** compose file that uses the image. They share container names and volumes.
- Back up Postgres with `pg_dumpall`.
- Pull **named services only**, never a bare `pull`. A bare pull once moved floating engine tags (the 2026-08-24 incident).
- Verification used then (8/8 passed):
  - OpenAI-format thinking, with no `<think>` leak;
  - Anthropic-format thinking blocks;
  - an `input_text` system block (the custom callback);
  - OpenAI and Anthropic streaming;
  - OpenAI and Anthropic tool calls;
  - vision.

  Also checked: embeddings, Langfuse `/api/public/health`, new ClickHouse `traces` rows, agentgateway, and `config --quiet` on every compose file.
- That update used a full `down` and `up` with a cache drop. **This time the engines must not restart.** Recreate individual services with `up -d --no-deps <svc>`, so no cache drop and no sudo are needed.

## R-5 Current health baseline (2026-11-14, before this work)

- Flash-Next engine `19ab778d…` healthy. `test-agentic-capabilities.py`: 10/10 through agentgateway, and every required test PASS through LiteLLM and direct.
- LangGraph test: 5 PASS and 1 WARN (reasoning not surfaced by `langchain_openai`), both through LiteLLM and through agentgateway.
- Reports are in the session scratchpad `phase4/`.
- Postgres `litellm` DB 110 MB. Disk free 2.7 TB. Host `MemAvailable` about 16.6 GiB with everything up.

## R-6 (P1) Result of the update, 2026-11-14

All seven services were recreated one at a time with `up -d --no-deps`, through `flash-next-compose.sh`. The engines and MinIO were not touched: their StartedAt, restart counts, health and OOM state are unchanged. Nothing was rolled back. The battery run is in the table below.

**Versions after the update (confirmed)**

| Service | Before | After | Evidence |
|---|---|---|---|
| LiteLLM | `v1.106.4` | **`v1.109.1`** | cosign verified, digest `sha256:11175975…`; arm64 manifest; readiness `healthy`, db `connected` |
| ClickHouse | `26.8.36.3` | **`26.8.37.168`** | `select version()`; `SELECT 1` OK; no schema migration logged by Langfuse |
| agentgateway | `v1.6.0` | **`v1.7.0`** | log `version: 1.7.0`; request-log schema ready; `/v1/models` on `:4100` answers |
| Langfuse web / worker | `3.225.14` | **`3.227.1`** | `/api/public/health` `OK`, version `3.227.1`; 425 Prisma migrations, all applied |
| Postgres | `16.15` | **`16.16`** | `select version()` |
| Redis | `7.4.12` (2026-07 build) | `7.4.12` (rebuilt 2026-11-09) | `PING` `PONG`; healthy |

cosign: `cosign-linux-arm64` from the latest release (v3.1.4), checked against `cosign_checksums.txt`, then `verify --key` on `ghcr.io/berriai/litellm:v1.109.1` exited 0.

**Battery (FR-P1-12 a, b, c, d, h, i), baseline versus after**

| Check | Baseline | After |
|---|---|---|
| 01 OpenAI thinking, no `<think>` leak | PASS | PASS |
| 02 Anthropic thinking blocks | PASS | PASS |
| 03 `input_text` callback (+ 03b plain-text control) | PASS | PASS |
| 04 OpenAI streaming | PASS | PASS |
| 05 Anthropic streaming ends `message_stop` | PASS | PASS |
| 06 OpenAI tool call | PASS | PASS |
| 07 Anthropic `tool_use` | PASS | PASS |
| 08 vision | PASS | PASS |
| 09 `claude-qwen3.8-flash-next` via `/v1/messages` | PASS | PASS |
| 10 embeddings, 2048 dims | PASS | PASS |
| 11 `/v1/models` lists the aliases | PASS | PASS |
| 12 `/model/info` limits (262144 / 262144) | PASS (recorded) | unchanged, PASS |
| 13 agentgateway chat on `:4100` | PASS | PASS |
| 14 new ClickHouse traces | PASS (litellm 11, agentgateway-trial 1) | PASS (litellm 11, agentgateway-trial 2) |
| 15 LiteLLM SpendLogs rows with cost > 0 | PASS (10/10) | PASS (10/10) |
| 16 agentgateway cost overlay log has no error | FAIL (pre-existing file-watch warning from 2026-10-27) | PASS |

Total: 16 PASS / 1 FAIL at baseline, 17 PASS / 0 FAIL after. No check that passed at baseline fails now.

Check 16 is negative-only: it FAILs if any cost-related log line contains error, fail or warn. It cannot prove the overlay loaded. The positive evidence is that the live 1.7.0 log contains `watching model catalog files count=1` (one match, checked 2026-11-14). The baseline FAIL to after PASS therefore reflects a fresh log with no negative line, plus that positive line.

Test scripts (FR-P1-12 e, f, g):
- agentic through LiteLLM: 9 PASS, 1 WARN (small-budget, informational) at both baseline and after;
- agentic through agentgateway: 10 PASS at baseline, 9 PASS + 1 WARN after (the same small-budget warning; with `max_tokens=20` the content comes back empty, not `\n\n`);
- LangGraph: 5 PASS, 1 WARN (reasoning presence, known) at both;
- reasoning effort: the server default is `medium` at both (PASS), and https is kept in all trials. The nothink medians (n=2) moved from 8.15 s to 13.25 s, which is not conclusive at this sample size; see `comparison.md`.

**Findings from the update**
- R-3 was wrong about the agentgateway session key. agentgateway 1.7.0 logs `failed to write generated session key ... Read-only file system` and `no session key configured; MCP session IDs are not encrypted`. The 1.6.0 log had the same two lines, so this predates the update. It is not fixed here, and it is not on the path that serves traffic (`/mcp/image-gen` is off).
- The LiteLLM startup warning about "7 migrations NEWER than any migration this LiteLLM version ships" (present on 1.106.4) is gone on 1.109.1.
- The LiteLLM value of `LITELLM_MASTER_KEY` already appears in the committed `CHANGELOG.md` (commit `ee78f38`, 2026-08-23, a historical record; the same value is also in `ai-workspace/summary-reports/qwen3.8-27b-nvfp4-stack-2026-08-23.md` from that commit). It is not from this update, and it is left for the user to handle (see `SPECS.md` open items).
