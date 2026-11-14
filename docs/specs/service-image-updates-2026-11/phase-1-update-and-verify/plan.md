# Service image updates (2026-11) · Phase 1 — Plan

```
REPO=/home/leeray75/vscode-workspace/ai-litellm-proxy
S=<session scratchpad>/svcimg            # baseline/, after/, logs, state files
B=~/backups/service-images-20261114      # dumps (chmod 700 dir / 600 files)
DC=./scripts/flash-next-compose.sh       # every compose command on the default stack
```

## Stage A — Prepare (nothing restarts)

1. **State** (FR-P1-02):
   - Save `docker inspect -f '{{.Name}} {{.Image}} {{.State.StartedAt}} {{.RestartCount}}' $(docker ps -aq)` to `$S/state_before.txt`.
   - Save `docker volume ls -q` to `$S/volumes_before.txt`.
   - Version probes:

     ```
     docker exec langfuse-postgres psql -U postgres -Atc 'select version()'
     docker exec langfuse-redis sh -c 'redis-cli -a "$REDIS_AUTH" --no-auth-warning INFO server' | grep redis_version
     curl -s localhost:3000/api/public/health
     docker exec langfuse-clickhouse clickhouse-client -q 'select version()'
     ```

     Add `--user`/`--password` from the container env if `clickhouse-client` needs them. Never echo the values.
2. **Verification battery** (FR-P1-12):
   - Write `$S/battery.py`. It is stdlib-only and gets the master key by parsing `.env` itself; it never prints the key.
   - It runs (a)–(d), (h) and (i). It writes `$S/<phase>/battery.json`, with one row per check: name, PASS or FAIL, detail.
   - For (h), it records the ClickHouse `traces` count and the latest timestamp per environment before the run, waits, then checks again. It counts `LiteLLM_SpendLogs` rows with `spend > 0` and a Flash-Next model since the run started.
   - Then run (e), (f) and (g) with the repo scripts. Reports go to `$S/<phase>/`.
   - Run the whole battery once with `<phase>=baseline`.
3. **Rollback tags** (FR-P1-03): for each of `langfuse-postgres langfuse-redis langfuse-clickhouse langfuse langfuse-worker litellm-proxy agentgateway`:

   ```
   docker tag $(docker inspect -f '{{.Image}}' <ctr>) local/rollback:<ctr>-20261114
   ```

4. **Backups** (FR-P1-04):

   ```
   mkdir -p $B && chmod 700 $B
   docker exec langfuse-postgres pg_dumpall -U postgres | gzip > $B/pg_dumpall.sql.gz
   chmod 600 $B/*
   gunzip -t $B/pg_dumpall.sql.gz
   zcat … | grep -c '^CREATE TABLE'
   ```

   Also dump each database alone (`pg_dump -Fc litellm` and `pg_dump -Fc` for the Langfuse DB). Find the Langfuse DB's name with `psql -Atc "select datname from pg_database"`. The separate dumps let FR-P1-15 restore one database.

   Back up agentgateway's DB:

   ```
   python3 -c "import sqlite3;s=sqlite3.connect('agentgateway/data/data.db');d=sqlite3.connect('$B/agentgateway-data.db');s.backup(d);print(d.execute('pragma integrity_check').fetchone())"
   ```

5. **Cosign** (FR-P1-05):
   - Get the latest `sigstore/cosign` release from the GitHub API. Download `cosign-linux-arm64` and `cosign_checksums.txt` into `$S/bin/`, check the sha256, then `chmod +x`.
   - Run `$S/bin/cosign verify --key <R-2 URL> ghcr.io/berriai/litellm:v1.109.1`, and save the output.
   - Check each image's architecture with `docker buildx imagetools inspect <img> | grep -c 'linux/arm64'`.
6. **Pins** (FR-P1-06):
   - Use `sed` on the exact image strings only.
   - Run `git diff --stat`, then `git diff -U0` to check every changed line is an `image:` line.
   - `config --quiet` for each changed file:
     - the Flash-Next file through `$DC config --quiet`;
     - `docker-compose.agentgateway.yml` with `AGW_LANGFUSE_BASIC_AUTH` exported the way `scripts/agentgateway-up.sh` does it;
     - the other files with plain `docker compose -f <f> config --quiet`. If they need `.env`, run from the repo directory.
7. **Pull** (FR-P1-07):

   ```
   $DC pull postgres redis clickhouse langfuse-web langfuse-worker litellm agentgateway
   ```

## Stage B — Apply, one tier at a time

Helper: wait until each listed container is `healthy`, or `running` when it has no healthcheck.

```
timeout 540 bash -c 'until …; do sleep 10; done'
```

Repeat it as needed, up to 10 minutes per step. After each step, look for `error|fatal|panic|migrat` in `docker logs --since 10m <ctr>`.

1. `$DC up -d --no-deps postgres redis clickhouse`, wait, then probe with `pg_isready`, `PING` and `SELECT 1`.
2. `$DC up -d --no-deps langfuse-worker`, wait, then `$DC up -d --no-deps langfuse-web`, wait.
   - Check health and the version, which should be 3.227.1.
   - Read the migration lines in the log.
3. `$DC up -d --no-deps litellm`, then wait until `curl -s localhost:4000/health/readiness` returns OK.
   - Read the migration line in the log.
   - Look for config warnings about `max_tokens`.
4. `$DC up -d --no-deps agentgateway`, wait, then read the log: config loaded, DB migration done, `/costs` overlay loaded.

## Stage C — Verify

- Re-run the whole battery as `<phase>=after`.
- Run the state record again and compare it with `state_before.txt`. The engine rows MUST be identical.
- Run `docker inspect -f '{{.Name}} {{.State.OOMKilled}}' $(docker ps -aq)`.
- Write `$S/comparison.md` with a table: check × baseline × after.

## Stage D — Decide and roll back

Apply FR-P1-14 to each service. Carry out FR-P1-15 only for services that hit a trigger, and record each decision in `$S/decision.md`.

## Stage E — Docs

- `grep -rnE 'v1\.106\.4|26\.8\.36\.3|agentgateway:v1\.6\.0|v1\.6\.0|3\.225\.14' --include=*.md .`. Exclude the `ai-workspace/` reports and the `docs/specs/*/` history. Classify each hit as current or historical.
- Update the current ones (FR-P1-16).
- Write R-6, the traceability table, `SPECS.md`, the CHANGELOG entry, and tick the tasks.

## Risks

| Risk | Mitigation |
|---|---|
| LiteLLM 1.109's one-way migrations fail, or behave differently with our custom callback or the `/v1/messages` bridge | Battery checks (a) and (b) with a baseline to compare. Per-database `pg_dump` restore plus `local/rollback:litellm-proxy-20261114`. |
| The Langfuse 3.227 ClickHouse migration can't be undone | Patch-level jump on the same major version, as in the 2026-10-27 precedent. If a migration fails, hand back to the user instead of guessing. |
| A Postgres container restart drops LiteLLM/Langfuse connections | Both reconnect. Langfuse and LiteLLM are recreated right after, in tiers 2 and 3. |
| agentgateway 1.7's DB migration or session-key write fails | The online SQLite backup plus the old image. The config is read-only, so the key goes to the DB (R-3). |
| A pulled image isn't arm64, or isn't what the tag claims | The arm64 check, plus cosign for LiteLLM. Pulls by named service only. |
| Secrets end up in dumps or logs | Dumps are outside the repo with mode 600, and secret checks are by count only. |
| Disk | 2.7 TB free. The new images add about 3 GB. |
