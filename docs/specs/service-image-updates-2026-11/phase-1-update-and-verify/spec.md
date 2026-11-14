# Service image updates (2026-11) · Phase 1 — Update and verify

| | |
|---|---|
| **Index** | [../SPECS.md](../SPECS.md) |
| **Status** | ✅ Implemented and reviewed 2026-11-14. The battery passed 17/17 after the update. Independent review took 2 rounds, both APPROVE once fixed: R001 found F1–F6 (all fixed) and R002 found N1 (fixed). Summary report: `ai-workspace/summary-reports/service-image-updates-2026-11-14.md`. Open items: see SPECS.md. |
| **Date** | 2026-11-14 |
| **Depends on** | `qwen38-flash-next-stack` Phase 4 ✅ (commit `e49641d`): the Flash-Next engine is on `19ab778d…`. Shared [../research.md](../research.md) R-1 – R-5 |
| **Supersedes** | The `CLAUDE.md` and `docs/` version statements for LiteLLM (`v1.106.4`), ClickHouse (`26.8.36.3`), agentgateway (`v1.6.0`) and Langfuse (`3.225.14`). They are superseded only for the services kept at the new version. |
| **Next** | [plan.md](plan.md) → [tasks.md](tasks.md) |

## User decisions (2026-11-14)

| # | Question | Decision |
|---|---|---|
| U-1 | Where the spec lives | A **new spec folder**, `docs/specs/service-image-updates-2026-11/`, because these services are shared by every stack |
| U-2 | LiteLLM target | **v1.109.1**, the newest stable, not the 1.106.10 patch line |
| U-3 | Upgrade the LangGraph test venv too? | **No.** Containers only. |
| U-4 | Git | New branch `chore/service-images-2026-11-14` off the Phase 4 commit `e49641d`. One commit at the end. No push. |

## Goal

Move the shared services to the versions in R-1 without restarting any inference engine. Prove each one still works against a baseline taken just before the change. Roll back any service that fails, on its own. Leave the docs accurate.

## Scope

**In scope:**
- **Pinned tags**, changed in **every** compose file that uses them:
  - LiteLLM `v1.106.4` → `v1.109.1`
  - ClickHouse `26.8.36.3` → `26.8.37.168`
  - agentgateway `v1.6.0` → `v1.7.0`
- **Floating tags**, refreshed by pulling: Langfuse web and worker `:3`, `postgres:16-alpine`, `redis:7-alpine`.

**Out of scope:**
- MinIO, which has no public image (R-1).
- The Flash-Next engine, the embedding engine and the rollback-stack engines.
- Moving floating tags to exact versions.
- The LangGraph venv (U-3).
- Any config change unless a release note forces it. None is expected (R-2, R-3).
- Rotating the leaked LiteLLM master key. That is a separate task the user owns, already recorded in Phase 4.

## Functional requirements

### Preparation (no disruption)

- **FR-P1-01 Baseline.** With the current versions running, run the verification battery FR-P1-12 (a)–(i) and save its results to the scratchpad as `baseline/`. A check that already fails on the baseline is a pre-existing failure. It can't trigger a rollback, but it is reported.
- **FR-P1-02 Record the current state.**
  - For every container: name, image ID, `StartedAt` and restart count.
  - `docker volume ls -q`.
  - The running versions of LiteLLM (`/health/readiness` or the startup log), Langfuse (`/api/public/health`), Postgres (`SELECT version()`), Redis (`INFO server`), ClickHouse (`SELECT version()`) and agentgateway (its log or image tag).
- **FR-P1-03 Rollback tags.** Before any pull, tag the **currently running** images of the floating-tag services and of every service being changed:

  ```
  docker tag <running image id> local/rollback:<service>-20261114
  ```

  This is non-destructive. A rollback for a floating tag then doesn't depend on a moved tag.
- **FR-P1-04 Backups.** Store them under `~/backups/service-images-20261114/`, outside the repo, with mode 700 on the directory and 600 on the files.
  - (a) Run `docker exec langfuse-postgres pg_dumpall -U <POSTGRES_USER> | gzip > …/pg_dumpall.sql.gz`. Check it is non-empty and that `gunzip -t` passes. Record the table count from the dump.
  - (b) Back up agentgateway's `agentgateway/data/data.db` with SQLite's online backup, either `sqlite3 .backup` or Python `sqlite3.Connection.backup`. Do not copy the file raw while it is in WAL mode. Then run `PRAGMA integrity_check` on the copy.
  - ClickHouse, Redis and MinIO data are not backed up. The ClickHouse change is a patch on the same LTS line, Redis keeps the same version, and the 2026-10-27 run set this precedent.
- **FR-P1-05 Supply chain.**
  - Run `cosign verify` (R-2 command) on `ghcr.io/berriai/litellm:v1.109.1`. Cosign isn't installed, so download the official `cosign-linux-arm64` release binary into the scratchpad. Check it against the release's published checksum and don't install it system-wide.
  - If cosign can't be obtained or verification fails, **stop and hand back**. Do not pull LiteLLM.
  - Every image MUST have a `linux/arm64` manifest.
- **FR-P1-06 Pins.**
  - Change the three pinned images in every compose file that references them (R-1: LiteLLM and ClickHouse in 5 files, agentgateway in 2). Change nothing else.
  - Keep each line's trailing comment, updating the version and date in it, e.g. `# pinned 2026-11-14 (was v1.106.4)`.
  - Run `config --quiet` on each changed compose file, using `./scripts/flash-next-compose.sh config --quiet` for the Flash-Next file. Each run MUST pass.
- **FR-P1-07 Pull named services only:**

  ```
  ./scripts/flash-next-compose.sh pull postgres redis clickhouse langfuse-web langfuse-worker litellm agentgateway
  ```

  - Never run a bare `pull`, and never pull the engines or MinIO.
  - The standalone `docker-compose.agentgateway.yml` project isn't running, so it doesn't need a pull. It uses the same image tag.

### Apply, one tier at a time

Every step uses `./scripts/flash-next-compose.sh up -d --no-deps <services>`. After each step, wait for that step's services to be healthy, or running for those with no healthcheck. Use bounded polling and give up after 10 minutes per step. Check the logs before the next step.

- **FR-P1-08 Data tier:** `postgres redis clickhouse`.
  - Postgres stays on major 16, so the data directory needs no upgrade.
  - Check Postgres with `pg_isready`, Redis with `PING`, and ClickHouse with `SELECT 1`.
  - Langfuse and LiteLLM reconnect by themselves. Confirm this in their logs, or by the checks in FR-P1-09.
- **FR-P1-09 Langfuse:** `langfuse-worker`, then `langfuse-web`.
  - Langfuse runs Postgres (Prisma) and ClickHouse migrations on start. Its log MUST show them applied without error.
  - `/api/public/health` MUST report `OK` and version `3.227.1`.
- **FR-P1-10 LiteLLM:** `litellm`.
  - The startup log MUST show the Prisma migrations applied (`All migrations have been successfully applied.` or the 1.109 equivalent).
  - It MUST have no config errors (R-2 `max_tokens` check), and its readiness check MUST answer.
- **FR-P1-11 agentgateway:** `agentgateway`.
  - The log MUST show the config loaded and the DB migration complete, with no errors.
  - Port 4100 MUST answer `/v1/models` with the master key.

### Verify

- **FR-P1-12 Verification battery.** Run all of it after FR-P1-11, using exactly the same commands as the baseline. Never print the master key.
  - (a) R-4's 8 LiteLLM checks against `qwen3.8-flash-next`:
    - OpenAI-format thinking, with no `<think>` leak;
    - Anthropic `/v1/messages` thinking blocks;
    - an `input_text` system block (the custom callback);
    - OpenAI streaming;
    - Anthropic streaming, which MUST end with `message_stop`;
    - an OpenAI tool call;
    - an Anthropic `tool_use`;
    - vision.

    Bypass LiteLLM's cache with `"cache": {"no-cache": true}`.
  - (b) The Claude Code discovery alias: `claude-qwen3.8-flash-next` through `/v1/messages`.
  - (c) The embeddings endpoint (`nemotron-3-embed-1b-nvfp4`) MUST return 2048 dimensions.
  - (d) `/v1/models` on LiteLLM MUST list the Flash-Next aliases. Check `/model/info` for `qwen3.8-flash-next`: the `max_input_tokens` and `max_output_tokens` values MUST be unchanged from the baseline.
  - (e) `scripts/test-agentic-capabilities.py --model qwen3.8-flash-next`, through LiteLLM and through agentgateway (`--base-url http://localhost:4100/v1`).
  - (f) `scripts/test-agentic-capabilities-langgraph.py --model qwen3.8-flash-next`, with the venv's Python, through LiteLLM.
  - (g) `scripts/test-reasoning-effort.py --expect-default medium`. This is the full run, which includes the behavior request through LiteLLM.
  - (h) Observability:
    - New ClickHouse `traces` rows within 5 minutes of the battery, for both LiteLLM-generated traces and agentgateway traces (environment `agentgateway-trial`).
    - LiteLLM spend logs: a new row in the `LiteLLM_SpendLogs` table, with cost > 0 for a Flash-Next request.
    - Count rows only. Never print trace contents.
  - (i) agentgateway's cost overlay still loads. Its log shows no error for `/costs`.
- **FR-P1-13 Engines untouched.** The engines' `StartedAt` and restart counts MUST be unchanged from FR-P1-02. Both engines MUST be healthy.

### Decide and roll back (per service)

- **FR-P1-14 Rollback triggers.** Roll back a service if any of these happens:
  - (a) It isn't healthy or running within 10 minutes, or it crash-loops (restart count rising).
  - (b) A migration fails.
  - (c) It is the cause of an FR-P1-12 check that FAILs now but passed on the baseline. Work out which service from logs and from which check failed.
  - (d) Any container has `OOMKilled=true`.

  Tool-selection breadth and Small-budget are informational, as before.
- **FR-P1-15 Rollback steps.** First save the last 300 log lines of the failing service to the scratchpad. Then:
  - **agentgateway:** restore the pins in both files, `cp` the backup over `data.db`, then `up -d --no-deps agentgateway`.
  - **LiteLLM:** its migrations are one-way, so the old version can't use the migrated DB.
    1. Stop `litellm` and `langfuse-web` / `langfuse-worker`.
    2. Restore the `litellm` database from the dump. Only that database is restored, so Langfuse's data is kept.
    3. Restore the pins, then run `up -d --no-deps` for those services.
    4. If the restore itself fails, **stop and hand back**. Leave LiteLLM stopped rather than run it on a mismatched DB.
  - **Langfuse:** same approach, with the `langfuse` DB, its ClickHouse migrations noted in the report, and `local/rollback:langfuse*` images. ClickHouse schema rollback isn't possible. If the Langfuse ClickHouse migrations ran, hand back to the user instead of guessing.
  - **Postgres, Redis or ClickHouse:** point the service at its `local/rollback:` image by restoring the pin or with a temporary image override, then `up -d --no-deps`.
  - After any rollback, re-run the FR-P1-12 checks that cover that service.

### Close-out

- **FR-P1-16 Docs**, for the versions kept:
  - `CLAUDE.md`: the vLLM image table's pinning paragraph, the "Updating service images" section and any `v1.106.4`, `26.8.36.3`, `v1.6.0` or `3.225.14` statements that describe the *current* state. Historical records stay as they are.
  - `docs/architecture.md` and any other `docs/*.md` lines that state current versions.
  - `CHANGELOG.md`: a `[Unreleased] › Changed` entry.
  - Grep the repo for the old versions and sort each hit into current statement or historical record.
- **FR-P1-17** Fill in the shared `research.md` with a new `R-6 (P1)` entry: results, versions confirmed after the update, and the battery table (baseline versus after). Fill in this spec's traceability table and status, and the `SPECS.md` Phases table, Deliverables and Open items.
- **FR-P1-18** Write the summary report `ai-workspace/summary-reports/service-image-updates-2026-11-14.md`. The orchestrator does this after the review.
- **FR-P1-19** One commit on `chore/service-images-2026-11-14`, ending with the repository's attribution line. No push. The orchestrator does this.

## Non-functional requirements

- **NFR-P1-01 Allowed Docker actions.**
  - Allowed:
    - `docker tag` to `local/rollback:*`;
    - `pg_dumpall` / `psql` restore through `docker exec`;
    - the named `pull` from FR-P1-07;
    - `up -d --no-deps` and `stop` through the wrapper, for the 7 in-scope services only;
    - `config`;
    - read-only commands.
  - Not allowed:
    - `down`, a bare `up` or a bare `pull`;
    - `-v`, `--volumes`, `--rmi`, `rm -v` or any `prune`;
    - deleting any image, including old images (they are the rollback);
    - touching `qwen3-8-flash-next-fp4-engine`, `nemotron-embed-engine` or MinIO;
    - sudo, apt or a reboot.
- **NFR-P1-02 Secrets.** `.env` values are never printed, logged or written to files in the repo. `compose config` output and DB dumps stay outside the repo. Use the secret check by count from Phase 4.
- **NFR-P1-03 Files changed.** Only these:
  - the 5 compose files: `docker-compose.yml`, `docker-compose.nemotron.yml`, `docker-compose.qwen3.6.yml`, `docker-compose.qwen3.8.yml`, `docker-compose.qwen3.8-flash-next.yml`;
  - `docker-compose.agentgateway.yml`;
  - `CLAUDE.md`, `CHANGELOG.md` and `docs/*.md`;
  - this spec folder;
  - new report JSONs under `ai-workspace/reports/` named `*-20261114-svcimg-*`;
  - the summary report.
- **NFR-P1-04 Downtime.**
  - Port 4000 is down only while `litellm` restarts, and port 4100 only while `agentgateway` restarts.
  - Langfuse ingestion pauses during its own restarts. LiteLLM's native Langfuse callback buffers or drops traces in that window, which is accepted and noted.
  - The engines keep serving the whole time.

## Decisions

- **D-1 Recreate per service, never `down`.** This keeps the engines up, so there is no 7–20 minute engine reboot and no sudo cache drop.
- **D-2 Tier order: data, then Langfuse, then LiteLLM, then agentgateway.** Dependencies come before the services that use them. LiteLLM comes after Langfuse so its callback has a live target. agentgateway is last because it depends on LiteLLM's key but not the reverse.
- **D-3 Tag the old images locally before pulling.** A floating-tag rollback doesn't need registry archaeology.
- **D-4 LiteLLM at v1.109.1 (U-2).** Its release-note actions were checked against the config (R-2). Its migrations are covered by the Postgres dump and the per-database restore path.
- **D-5 Floating tags stay floating.** This follows `CLAUDE.md`. Only the three already-pinned images get new pins.

## Acceptance scenarios

- **AS-1** The baseline battery, the state record and the version list exist. The rollback tags exist for all 7 services. The backups exist, `gunzip -t` passes, and SQLite `integrity_check` returns `ok`. Cosign verification passes for LiteLLM v1.109.1. Every image is arm64.
- **AS-2** The compose diffs change only the image lines and their trailing comments. Every changed compose file passes `config --quiet`.
- **AS-3** All 7 services run the new versions, healthy or running. The migrations were applied cleanly. No container was OOM-killed.
- **AS-4** The battery after the update matches the baseline. No check that passed on the baseline fails now. The engines' `StartedAt` is unchanged. Traces and spend rows arrive.
- **AS-5** On any rollback: the service is back on its `local/rollback:` image, its checks pass, and the reason is recorded.
- **AS-6** The docs state the new current versions, and historical records are untouched. Every secret check by count is 0. `git status` shows only NFR-P1-03 files.

## Traceability

| Requirement | Verification | Status |
|---|---|---|
| FR-P1-01 – 07 | AS-1, AS-2 | ✅ State, versions, rollback tags, backups (`gunzip -t`, SQLite `integrity_check` ok), cosign verified, every image arm64, six compose files pass `config --quiet`, named pull only. Baseline 16 PASS / 1 FAIL (check 16, pre-existing; R-6) |
| FR-P1-08 – 11 | AS-3 | ✅ Every service healthy or running with 0 restarts and no OOM. Migrations applied (Langfuse 425, LiteLLM 225). The agentgateway log has two pre-existing *warnings* about the session key, not errors (R-6) |
| FR-P1-12 – 13 | AS-4 | ✅ Battery 17 PASS / 0 FAIL after (no baseline PASS regressed). Test scripts (e), (f), (g) match the baseline apart from informational warnings (R-6). Engine StartedAt, restarts and health unchanged |
| FR-P1-14 – 15 | AS-5 | ✅ No trigger fired, so no rollback. AS-5 not exercised (`decision.md`) |
| FR-P1-16 – 17 | AS-6 | ✅ `CLAUDE.md`, `docs/architecture.md`, `CHANGELOG.md` updated; old-version grep hits classified. R-6 written. ⚠️ Secret check: the `LITELLM_MASTER_KEY` value already appears once in committed `CHANGELOG.md` (HEAD `ee78f38`, historical). See `SPECS.md` open items |
| FR-P1-18 – 19 | — | ⏳ Orchestrator (summary report, commit) |
| NFR-P1-01 – 04 | AS-3, AS-4, AS-6, review | ✅ Only the allowed Docker actions were used (no `down`, bare `up`/`pull`, `-v`, `rm`, `rmi` or `prune`; no engine or MinIO touched). ⚠️ NFR-P1-02: the committed CHANGELOG line above (pre-existing, not changed) |
