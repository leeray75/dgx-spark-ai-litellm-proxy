# Qwen3.8-Flash-Next stack · Phase 2 — Plan

Facts cited as `research.md R-n` are in the shared [../research.md](../research.md).

Throughout, `$REPO=/home/leeray75/vscode-workspace/ai-litellm-proxy` and `$S=<session scratchpad>/phase2`.

## Stage A — Prepare (27B stack still serving)

1. **Image:** `docker pull eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595`.
2. **Checkpoint:** run this as a background command. It can take a long time; wait for the completion notification rather than polling the log.

   ```bash
   python3 -m venv $S/hfvenv
   $S/hfvenv/bin/pip install -q -U "huggingface_hub[hf_xet]"
   cd $REPO && set -a && source .env && set +a
   $S/hfvenv/bin/hf download nvidia/Qwen3.8-Flash-Next-FP4-Local > $S/download.log 2>&1
   ```

   The default cache, `~/.cache/huggingface/hub`, is the same path the engine bind-mounts.
3. **Verify:** 21 `tensors/model-0000N-of-00021.safetensors` files, the index file, and no `*.incomplete` under the model's blobs.
4. **`litellm-config.yaml`:** add the FR-P2-03 entry after `qwen3.8-27b-nothink`. Check that `git diff --stat litellm-config.yaml` shows only added lines. LiteLLM reads its config at startup, so the running container won't change until Stage D recreates it.
5. **Test scripts:** make the FR-P2-04/05 changes.
   - **Vision test:** build the PNG in memory. Use 8-bit RGB, filter byte 0 per row, `zlib.compress` the IDAT, and compute CRCs with `zlib.crc32`. Send it as
     `messages=[{"role":"user","content":[{"type":"text","text":"What single color fills this image? Answer with one word."},{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}]}]`
     with `max_tokens` around 1024, because reasoning tokens come first.
   - **Throughput test:** a prompt such as "Write a ~400-word technical explanation of how a hash map handles collisions." with `max_tokens` 1024. Use `usage.completion_tokens` divided by wall time. The detail line is `completion_tokens=N, elapsed=Xs, ~Y tok/s (includes prefill/TTFT)`.
   - Register both tests in the same list the other tests use, so they appear in the JSON report and the summary.
6. **Check the scripts:** run `py_compile` and `--help` on both.

## Stage B — Pre-shutdown checks

- Idle check (FR-P2-07): `docker logs --since 2m qwen3-8-27b-nvfp4-engine 2>&1 | grep -E 'Running: [1-9]'`.
- Baselines go to `$S/`: `ps_before.txt`, `volumes_before.txt`, `meminfo_before.txt`.

## Stage C — Shutdown

```bash
docker stop local-image-gen-mcp
cd $REPO && set -a && source .env && set +a
export AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)
docker compose -f docker-compose.agentgateway.yml down
docker compose -f docker-compose.qwen3.8.yml down
```

Then save `meminfo_after_shutdown.txt` and check that `docker volume ls -q` matches the baseline.

**CHECKPOINT (FR-P2-09):** if MemFree is below 105 GiB, stop here and hand back to the caller with the meminfo numbers. The caller asks the user to drop caches and resumes you. Don't wait in a loop.

## Stage D — Boot

```bash
cd $REPO && set -a && source .env && set +a
export AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)
docker compose -f docker-compose.qwen3.8-flash-next.yml up -d
```

- Wait for the engine to become healthy. Use a background poller, or Monitor with an until-loop, polling `docker inspect -f '{{.State.Status}} {{.State.Health.Status}}'` every 30 s with a 60-minute limit. Don't sleep in the foreground.
- While waiting, check `docker logs` periodically for the FR-P2-17 failure conditions.
- Once the engine is healthy, read these from its log:

  ```bash
  docker logs qwen3-8-flash-next-fp4-engine 2>&1 | grep -iE 'model weights took|memory|KV cache|Maximum concurrency|tokens' | tail -20
  ```

## Stage E — Tests

```bash
cd $REPO
python3 scripts/test-agentic-capabilities.py --base-url http://localhost:8301/v1 --model qwen3.8-flash-next \
    --output ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-engine-20261022.json
python3 scripts/test-agentic-capabilities.py --model qwen3.8-flash-next \
    --output ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-litellm-20261022.json
/home/leeray75/vscode-workspace/.venv/bin/python3 scripts/test-agentic-capabilities-langgraph.py --model qwen3.8-flash-next \
    --output ai-workspace/reports/agentic-test-langgraph-qwen38-flash-next-20261022.json
docker logs --since 30m qwen3-8-flash-next-fp4-engine 2>&1 | grep -oE 'Avg generation throughput: [0-9.]+'   # median of non-zero values
```

- The scripts read `LITELLM_MASTER_KEY` from `.env` themselves (`load_api_key_from_env_file`).
- vLLM wasn't started with `--api-key`, so any bearer token works for the direct engine run.

## Stage F — Rollback (only on FR-P2-17 triggers)

Follow FR-P2-17 step by step. `restart.sh` / `model-switch.sh` would also drop caches with sudo and use `--remove-orphans`, so don't use them.

## Risks

| Risk | Mitigation |
|---|---|
| The model is gated (license) and the download returns 403 | Detected in Stage A, before any disruption; report to the user |
| The download takes a long time | It runs while the 27B stack still serves (D-1) |
| vLLM's startup memory check fails because of page cache | Memory checkpoint with a user-run cache drop (FR-P2-09) |
| Healthcheck `python3` missing in the image | Image history says it's installed (R-3a). If health stays `starting` while `/health` answers from the host, report it rather than roll back. |
| `qwen3_xml` tool calls aren't translated as OpenAI `tool_calls` | AS-7 catches it in the direct-engine run. Not a rollback trigger. |
| Restoring the image server with `docker start` fails on the stale network | Restore with compose `up -d` (FR-P2-17) |
| A secret leaks into a report | The scripts store model output only. The reviewer greps the reports for `.env` values (AS-10). |
