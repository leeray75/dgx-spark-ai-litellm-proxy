# Qwen3.8-Flash-Next stack · Phase 4 — Plan

Facts cited as `research.md R-n` are in the shared [../research.md](../research.md).

Throughout:

```
REPO=/home/leeray75/vscode-workspace/ai-litellm-proxy
S=<session scratchpad>/phase4
NEW=eugr/spark-vllm-b12x@sha256:19ab778dd57f019c44caf5df91a671cf688923d1ca9fa8ce92be0c9acb46d215
OLD=eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595
ENG=qwen3-8-flash-next-fp4-engine
```

Every compose command goes through `./scripts/flash-next-compose.sh`, which derives `AGW_LANGFUSE_BASIC_AUTH`. Without it, the compose file's `:?` guard fails.

## Stage A — Prepare (engine still serving)

1. Run `docker pull $NEW`. It is about 28 GB, so run it in the background and wait for it to finish. Then:

   ```bash
   docker image inspect $NEW --format '{{.Id}} {{.Architecture}} {{.Size}} {{.Created}}'
   ```

2. Record the baseline facts in `$S/`:
   - `docker inspect -f '{{.Name}} {{.Image}} {{.State.StartedAt}}' $(docker ps -q)` → `startedat_before.txt`
   - `docker ps` → `ps_before.txt`
   - `docker volume ls -q` → `volumes_before.txt`
   - `/proc/meminfo` → `meminfo_before.txt`
3. Run the baseline 3 times, one after another, not in parallel:

   ```bash
   cd $REPO
   for i in 1 2 3; do
     python3 scripts/test-agentic-capabilities.py --base-url http://localhost:8301/v1 --model qwen3.8-flash-next \
       --output ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-engine-baseline-20261114-run$i.json
   done
   ```

   - The script exits 1 when any test FAILs. That is expected and is not a reason to stop.
   - Take tok/s from the *Decode throughput* test's detail (`~Y tok/s`).
   - Note the UTC start and end times, then extract the samples:

     ```bash
     docker logs --since <start> --until <end> $ENG 2>&1 | grep -oE 'Avg generation throughput: [0-9.]+'
     ```

4. Edit the compose file:
   - Replace the digest on the engine's `image:` line.
   - Rewrite the comment above it, for example:

     ```
     # Community image required: upstream vLLM can't read the checkpoint's
     # compressed NVFP4 scale format ("csf") yet. Pinned by digest (= :latest on 2026-11-14,
     # arm64, CUDA 13.0.2, built 2026-11-02; Phase 4) — never use the mutable tag.
     # Rollback: sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595 (built 2026-10-15)
     ```

   - Check that `git diff --stat` shows one file with a small diff.
   - Run `./scripts/flash-next-compose.sh config > $S/config.yml`. The output contains secrets, so it stays in the scratchpad and is never printed.
   - Run `grep -c 19ab778d $S/config.yml`.

## Stage B — Swap

1. **Idle check:**

   ```bash
   docker logs --since 2m $ENG 2>&1 | grep -cE 'Running: [1-9]'
   ```

2. Run `./scripts/flash-next-compose.sh stop $ENG`, then save `/proc/meminfo` to `$S/meminfo_after_stop.txt`.
3. **⛔ CHECKPOINT:**
   - If `MemFree` is below 95 GiB, stop and return to the caller with MemFree, MemAvailable and Cached. Don't wait in a loop.
   - The caller has the user drop caches, then resumes you.
   - The engine is down during this wait. That is accepted.
4. Run `./scripts/flash-next-compose.sh up -d --no-deps $ENG` and record the UTC time.
5. **Wait:**
   - Use a background loop that polls `docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' $ENG` every 30 s until `healthy`, `exited`, or 3600 s pass, and writes each sample to `$S/health.log`.
   - While it runs, check the logs with `docker logs --since 5m $ENG 2>&1 | grep -E 'Traceback|Error|OOM'`.
6. **Boot facts:**

   ```bash
   docker logs $ENG 2>&1 | grep -iE 'model loading took|weights|KV cache|Maximum concurrency|version|cache|compil' | tail -40
   ```

   - Save `/proc/meminfo` once healthy and idle.
   - Run `docker inspect -f '{{.Name}} {{.State.OOMKilled}}' $(docker ps -aq)`.
   - Compare `StartedAt` with the baseline. Only `$ENG` may differ.
   - Check that `docker volume ls -q` matches the baseline.
7. **Models:**

   ```bash
   curl -s localhost:8301/v1/models
   curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:4000/v1/models
   ```

   Source `.env` in a subshell for the master key and don't echo it.

## Stage C — Tests

- Repeat the Stage A step 3 loop, with `new` in place of `baseline`.
- Run the LiteLLM test once:

  ```bash
  python3 scripts/test-agentic-capabilities.py --model qwen3.8-flash-next \
    --output ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-litellm-new-20261114.json
  ```

- Run `python3 scripts/test-reasoning-effort.py --expect-default medium --skip-behavior`.
- Spot-check `MemAvailable` (`grep MemAvailable /proc/meminfo`) during and after the runs.

## Stage D — Decide

Build the table `test × {baseline run1-3, new run1-3, litellm-new}` and apply FR-P4-12 (a)–(e) exactly as written. Write the decision and its reason to `$S/decision.md`.

- **Keep** → go to Stage E.
- **Roll back** → follow FR-P4-13, then go to Stage E with the rollback wording.

## Stage E — Close-out

- **On keep:**
  - Run `./scripts/check-engine-image.sh`, then `./scripts/check-engine-image.sh show`. It must print "No new engine image."
  - Edit:
    - the `CLAUDE.md` line ~170 row: digest `19ab778d…`, created 2026-11-02, "= `:latest` on 2026-11-14", previous build `03a95654…` kept locally as the rollback;
    - the `docs/architecture.md` engine row (line ~73);
    - R-3a: add a dated note under the table.
  - Add a CHANGELOG entry under `[Unreleased]`, in a `### Changed` section (create it if it's missing).
- Write R-15, the spec traceability table and status, and the SPECS.md row, Deliverables and Open items. Do this for both outcomes.
- The summary report and the commit come last (T017 – T018), after the review loop.

## Risks

| Risk | Mitigation |
|---|---|
| The new build can't load `csf` NVFP4 or the b12x flags | It's a boot failure, so the rollback in FR-P4-13 applies. The old image is local, so rollback takes about 5 min plus boot. |
| The b12x and compile caches rebuild, so the first boot is slow (≤ 19 min seen in R-12) | 60-minute limit. The caches stay in the named volumes, and the old image's entries are not deleted. |
| The pull fills the page cache, so `MemFree` is low after stop | The FR-P4-06 human checkpoint. |
| One noisy test run triggers or masks a regression | n=3 medians and the flake rule (D-2, D-5). |
| Agent traffic hits the engine during the swap | Idle check. LiteLLM returns errors while the engine is down. Accepted. |
| A secret leaks into `compose config` output | Write it only to `$S`, never to stdout. The reviewer greps for secrets (AS-7). |
| Another service gets restarted by accident | Only `--no-deps $ENG` is allowed. The `StartedAt` comparison catches anything else. |
