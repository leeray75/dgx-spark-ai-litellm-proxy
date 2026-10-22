# Troubleshooting Guide

## Common Issues

### 1. Model Loading Timeout

**Problem**: Engine container keeps restarting during model loading.

**Symptoms**:
- Container shows `Restarting` status
- Logs show "Loading model weights..."
- Health check fails repeatedly

**Solution**:

The initial model loading can take 10-60 minutes (first boot includes FlashInfer fp8_gemm autotuning). Subsequent starts are typically 5-15 minutes due to persistent cache in the engine's own `vllm-*compile-cache` volume.

```bash
# Check container logs
./scripts/flash-next-compose.sh logs -f qwen3-8-flash-next-fp4-engine   # Flash-Next (default; first boot up to ~19 min)
docker compose logs -f qwen3-8-27b-nvfp4-engine    # Qwen3.8-27B (rollback)
docker compose logs -f qwen3-6-35b-nvfp4-engine    # Qwen3.6 (retired rollback)
docker compose logs -f nemotron-embed-engine
docker compose logs -f qwen3-coder-next-engine
docker compose logs -f nemotron-engine

# Wait for loading to complete
# The health check has a 3600s start_period for the chat engine (Flash-Next/Qwen3.8/Qwen3.6)
# and 900s start_period for the embedding engine
```

**If loading fails**:
1. Check GPU memory: `nvidia-smi`
2. Verify HF_TOKEN is correct in `.env`
3. Ensure enough disk space for model cache
4. Check FlashInfer autotune cache: `docker compose logs qwen3-8-27b-nvfp4-engine | grep -i flashinfer` (swap container name for the qwen3.6 rollback)

---

### 2. Connection Refused on Port 4000

**Problem**: LiteLLM proxy returns connection refused.

**Symptoms**:
```bash
curl: (7) Failed to connect to localhost port 4000: Connection refused
```

**Solution**:

1. Check all services are running:
```bash
docker compose ps
```

2. Check LiteLLM logs:
```bash
docker compose logs litellm
```

3. Verify the vLLM engine is healthy:
```bash
curl http://localhost:8301/health  # Flash-Next (default), Qwen3.8-27B or Qwen3.6 — whichever stack is running
curl http://localhost:8302/health  # For Embedding Engine (Qwen3.8/3.6 stacks)
curl http://localhost:8300/health  # For Qwen3-Coder
curl http://localhost:8200/health  # For Nemotron
```

4. Restart the stack:
```bash
docker compose restart litellm
```

---

### 3. Langfuse UI Not Loading

**Problem**: Langfuse web UI shows "Service Unavailable" or times out.

**Symptoms**:
- http://localhost:3000 doesn't load
- Browser shows connection timeout

**Solution**:

1. Check Langfuse services:
```bash
docker compose ps | grep langfuse
```

2. Verify PostgreSQL is healthy:
```bash
docker compose exec postgres pg_isready
```

3. Check Langfuse logs:
```bash
docker compose logs langfuse-web
docker compose logs langfuse-worker
```

4. Verify environment variables:
```bash
# Check NEXTAUTH_SECRET is set
grep NEXTAUTH_SECRET .env
```

---

### 4. GPU Out of Memory (OOM)

**Problem**: Container exits with OOM error.

**Symptoms**:
```
vLLM OOM: Cannot allocate memory for model weights
```

**Solution**:

1. Reduce GPU memory usage in compose file:

```yaml
# In docker-compose.yml, adjust gpu-memory-utilization
qwen3-coder-next-engine:
  environment:
    VLLM_GPU_MEMORY_UTILIZATION: "0.75"  # Reduce from 0.88
```

2. Reduce max model length:
```yaml
command:
  --max-model-len 131072  # Reduce from 262144
```

3. Reduce max sequences:
```yaml
command:
  --max-num-seqs 8  # Reduce from 16
```

---

### 4a. "No available memory for the cache blocks" (Qwen3.8, real incident)

**Problem**: Engine crashes on first boot, `docker inspect` shows the container restarting.

**Symptoms**:
```
ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization`
when initializing the engine (this flag also controls CPU memory reservation on the CPU
backend, despite its name).
```
Preceded by a log line like:
```
CUDA graph memory profiling is enabled (default since v0.21.0). The current
--gpu-memory-utilization=0.4000 is equivalent to --gpu-memory-utilization=0.3841 without
CUDA graph memory profiling. To maintain the same effective KV cache size as before,
increase --gpu-memory-utilization to 0.4159.
```

**Why this happened**: `docker-compose.qwen3.8.yml` initially carried `--gpu-memory-utilization 0.4` over from
qwen3.6 by analogy — untested for this model. On real first boot it left literally zero room for KV cache after
weights (~22.13 GiB) and CUDA-graph memory profiling, which for this checkpoint includes profiling the vision
encoder/multimodal path. (An earlier version of this note said qwen3.6 is text-only and skips that profiling — it
isn't; qwen3.6 also has a vision encoder. The larger dense weights are the more likely difference.)

**Solution**:

1. This is already fixed in the current `docker-compose.qwen3.8.yml` (`--gpu-memory-utilization 0.6`, confirmed
   working with 13.96 GiB KV cache available). If you see this error, check you're on the current file version.
2. If it recurs (e.g. after raising `--max-model-len` or other config that increases the memory footprint), raise
   `--gpu-memory-utilization` further and recreate: `docker compose -f docker-compose.qwen3.8.yml up -d
   --force-recreate qwen3-8-27b-nvfp4-engine`.
3. The log line quoted above (right before the crash) tells you the exact breakeven value for your current
   config — treat that as a floor, not a target; leave real headroom above it for actual KV cache.

---

### 4b. Same OOM hits qwen3.6 after a `docker pull vllm/vllm-openai:nightly` (real incident, 2026-08-24)

**Problem**: `docker-compose.qwen3.6.yml`'s engine, previously stable for weeks at `--gpu-memory-utilization 0.4`,
suddenly hits the exact same `ValueError: No available memory for the cache blocks` crash described in 4a above.

**Why this happened**: `docker-compose.qwen3.6.yml` and `docker-compose.qwen3.8.yml` both reference the
**mutable** `:nightly` tag, not a pinned digest. A `docker pull vllm/vllm-openai:nightly` run to investigate
qwen3.8's throughput (see CHANGELOG.md) silently upgraded qwen3.6's engine too, on its next restart, to a vLLM
build it had never been validated against — reproducing the identical CUDA-graph-memory-profiling issue.

**Solution**:

1. This is already fixed in the current `docker-compose.qwen3.6.yml` (`--gpu-memory-utilization 0.6`, confirmed
   working with 24.54 GiB KV cache available). If you see this error, check you're on the current file version.
2. Check which build you're actually running before assuming the file is wrong:
   ```bash
   docker exec qwen3-6-35b-nvfp4-engine python3 -c "import vllm; print(vllm.__version__)"
   ```
3. **Before running `docker pull vllm/vllm-openai:nightly` for any reason** (including investigating a different
   compose file entirely), know that it affects both `docker-compose.qwen3.6.yml` and
   `docker-compose.qwen3.8.yml` simultaneously, since neither is pinned to a digest yet. Re-test both stacks after
   any such pull, not just the one you were originally investigating.

---

### 4c. Flash-Next fails at startup: free memory below the target (startup memory check, cache drop)

**Problem**: The Flash-Next engine (`--gpu-memory-utilization 0.80`) exits at startup with a free-memory error, or `./scripts/model-switch.sh flash` aborts with "MemFree is … GiB, below the 105 GiB".

**Cause**: vLLM refuses to start when free memory is below `gpu-memory-utilization × total` (0.80 × 121.7 GiB ≈ 97 GiB). On GB10 the CUDA free figure tracks `MemFree`, **not** `MemAvailable`, so page cache (for example from downloading the 96 GiB checkpoint) makes it fail even when `MemAvailable` is high. Measured 2026-10-22: after the download and with the 27B stack down, `MemFree` was only 9.7 GiB while `MemAvailable` was 117.6 GiB.

**Solution**:

1. Check: `grep -E 'MemFree|MemAvailable' /proc/meminfo`
2. Stop everything that holds GPU memory first (`./scripts/restart.sh clean` or the target stack's `down`; `docker stop local-image-gen-mcp` — it holds ~18 GB and Flash-Next at 0.80 cannot share).
3. Drop the page cache (needs sudo, run it yourself): `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'`
4. Re-run `./scripts/restart.sh flash` (does steps 2-3 itself) or `./scripts/model-switch.sh flash`. Preview with `DRY_RUN=1` (any non-empty value other than `0` is a dry run).
   `model-switch.sh flash` has two gates: a **pre-stop** gate that aborts (exit 2) *before stopping anything* when page cache (Cached+Buffers) is ≥ 10 GiB (121.7 GiB total − 105 GiB needed free − ~5 GiB baseline ≈ 11.7, rounded down; dropping caches while the old stack runs is harmless), and a **post-stop** gate that aborts (exit 3) when `MemFree` is still under 105 GiB after the old stack was stopped. On exit 3 the previous stack is **already stopped and nothing is serving**: the message prints the sudo drop command and the exact re-run command.
5. Do not lower `--gpu-memory-utilization` as a workaround: 0.70 leaves less KV cache than one 262,144-token sequence (see `docs/specs/qwen38-flash-next-stack/research.md` R-7), and changing it invalidates the compile cache.

---

### 4d. `local-image-gen-mcp` can't reach the network after a stack switch (stale network)

**Problem**: After switching stacks, a stopped `local-image-gen-mcp` fails to start or can't resolve other containers, or agentgateway's `/mcp/image-gen` returns "backends required DNS resolution which failed".

**Cause**: `docker compose … down` removes the `ai-litellm-proxy_ai-bridge` network and the next `up` creates a new one with the same name but a new ID. A stopped `local-image-gen-mcp` still references the old one (observed 2026-10-22: `0f655f48…` vs live `c84d4eac…`). It is also deliberately **off** while Flash-Next runs, so this error is expected there.

**Solution**: bring it back with its own compose `up -d` (not `docker start`), only when the 27B stack (not Flash-Next) is running:

```bash
cd ~/vscode-workspace/local-image-gen-mcp/docker
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
```

`./scripts/restart.sh qwen3.8` / `./scripts/model-switch.sh qwen3.8` do this automatically after the 27B engine is healthy (and then run `./scripts/agentgateway-up.sh`).

---

### 4e. Requests for `qwen3.8-27b` / `qwen3.8-27b-nothink` (removed aliases) behave unexpectedly

**What happens (user decision U-5, 2026-10-22: intended, documented behaviour)**: since 2026-10-22 the `qwen3.8-27b` / `qwen3.8-27b-nothink` aliases are removed (Flash-Next is the default).
- **LiteLLM (`:4000`) does not fail.** `default_fallbacks: ["qwen3.8-flash-next"]` also catches removed and unknown model names, so the request returns 200, served by Flash-Next with **thinking ON**, and the response echoes the requested name in `model`. Nothing in the response says a fallback happened (check the Langfuse model name `openai/qwen3.8-flash-next`).
- **`qwen3.8-27b-nothink` callers silently lose no-think** (reasoning tokens appear, small `max_tokens` budgets can come back empty). Fix the client: use `qwen3.8-flash-next-nothink` (for Goose, `GOOSE_SUBAGENT_MODEL`).
- **agentgateway (`:4100`) is strict:** 404 `model_not_found` for the same names.

**Solution**: use `qwen3.8-flash-next` / `qwen3.8-flash-next-nothink` (or `claude-qwen3.8-flash-next` in Claude Code) and update client configs. To go back to the 27B, uncomment the ROLLBACK blocks in `litellm-config.yaml` and `agentgateway/config.yaml` before `./scripts/model-switch.sh qwen3.8`.

---

### 5. HF_TOKEN Authentication Failed

**Problem**: Model cannot be downloaded from HuggingFace.

**Symptoms**:
```
HuggingFaceAPIError: 401 Unauthorized
```

**Solution**:

1. Verify HF_TOKEN in `.env`:
```bash
grep HF_TOKEN .env
```

2. Test HF_TOKEN manually:
```bash
export HF_TOKEN=your_token_here
huggingface-cli login
```

3. Ensure token has read access to the model:
- Visit https://huggingface.co/settings/tokens
- Check token permissions

---

### 6. Port Already in Use

**Problem**: Port conflict prevents service from starting.

**Symptoms**:
```
Bind for 0.0.0.0:4000 failed: port is already allocated
```

**Solution**:

1. Find what's using the port:
```bash
# Port 4000
lsof -i :4000

# Port 3000
lsof -i :3000
```

2. Kill the conflicting process:
```bash
kill -9 <PID>
```

3. Or change ports in `docker-compose.yml`:
```yaml
ports:
  - "4001:4000"  # Change host port
```

---

### 7. Virtual Key Data Encryption Lost

**Problem**: Virtual keys no longer decrypt after restart.

**Symptoms**:
- LiteLLM UI shows "Invalid key"
- Spend tracking data is unreadable

**Solution**:

⚠️ **CRITICAL**: `LITELLM_SALT_KEY` must never change after keys are created.

1. Stop the stack:
```bash
docker compose down
```

2. Verify `LITELLM_SALT_KEY` in `.env` hasn't changed

3. If key changed, you must regenerate all virtual keys:
```bash
# Delete old keys from database
# Regenerate them via LiteLLM API
```

---

### 7a. FlashInfer Autotune Hangs on First Boot

**Problem**: vLLM engine stuck in "Tuning fp8_gemm" phase for over an hour on first boot.

**Symptoms**:
- Logs show repeated "Tuning fp8_gemm" entries
- Boot takes 60+ minutes instead of 5-15 minutes
- No cache-load message in logs

**Solution**:

1. Verify you're using a nightly image built after 2026-05-31:
```bash
docker inspect --format '{{.Config.Image}}' qwen3-8-27b-nvfp4-engine   # or qwen3-6-35b-nvfp4-engine for rollback
```

2. Check for cache-load message:
```bash
docker compose logs qwen3-8-27b-nvfp4-engine | grep -i "flashinfer.*cache"   # or qwen3-6-35b-nvfp4-engine
```

3. If cache is disabled, force re-tune and escape hatch:
```bash
# Clear the cache volume to force fresh autotuning
docker volume rm ai-litellm-proxy_vllm-qwen38-compile-cache   # or ai-litellm-proxy_vllm-compile-cache for rollback
docker compose -f docker-compose.qwen3.8.yml up -d qwen3-8-27b-nvfp4-engine
```

4. If output looks wrong after cache load, disable persistent cache:
```bash
# Add to vLLM environment:
VLLM_DISABLE_FLASHINFER_AUTOTUNE_CACHE=1
```

---

### 7b. Langfuse Events Not Showing

**Problem**: API requests are tracked but traces don't appear in UI.

**Symptoms**:
- Requests succeed
- Langfuse UI shows empty traces

**Solution**:

1. Check Redis queue:
```bash
docker compose exec redis redis-cli -a $(grep REDIS_AUTH .env | cut -d= -f2) KEYS '*'
```

2. Check Langfuse Worker logs:
```bash
docker compose logs langfuse-worker
```

3. Verify ClickHouse is accepting data:
```bash
docker compose exec clickhouse clickhouse-client \
  --query "SELECT count(*) FROM langfuse_traces"
```

4. Check environment variables:
```bash
# Verify these are set correctly in .env
grep LANGFUSE_PUBLIC_KEY .env
grep LANGFUSE_SECRET_KEY .env
```

---

## Log Files

### Access Logs

```bash
# All services
docker compose logs -f

# Specific service
./scripts/flash-next-compose.sh logs -f qwen3-8-flash-next-fp4-engine   # Flash-Next (default)
docker compose logs -f qwen3-8-27b-nvfp4-engine    # Qwen3.8-27B (rollback)
docker compose logs -f qwen3-6-35b-nvfp4-engine    # Qwen3.6 (retired rollback)
docker compose logs -f nemotron-embed-engine
docker compose logs -f qwen3-coder-next-engine
docker compose logs -f nemotron-engine
docker compose logs -f litellm
docker compose logs -f langfuse-web
docker compose logs -f langfuse-worker

# PostgreSQL
docker compose exec postgres tail -f /var/log/postgresql/postgresql.log

# ClickHouse
docker compose exec clickhouse tail -f /var/log/clickhouse-server/clickhouse-server.log

# Redis
docker compose exec redis redis-cli -a <REDIS_AUTH> LOG GET
```

### Docker Compose Diagnostic Commands

```bash
# Check container status (Flash-Next stack: use ./scripts/flash-next-compose.sh ps -a, plain compose needs AGW_LANGFUSE_BASIC_AUTH)
docker compose ps -a

# Check network connectivity
docker compose exec litellm ping -c 3 qwen3-8-flash-next-fp4-engine   # default; or qwen3-8-27b-nvfp4-engine / qwen3-6-35b-nvfp4-engine for the rollbacks
docker compose exec litellm ping -c 3 nemotron-embed-engine
docker compose exec litellm ping -c 3 qwen3-coder-next-engine
docker compose exec litellm ping -c 3 langfuse

# Inspect container details
docker compose inspect litellm
docker compose inspect qwen3-8-flash-next-fp4-engine   # default; or qwen3-8-27b-nvfp4-engine / qwen3-6-35b-nvfp4-engine for the rollbacks
docker compose inspect nemotron-embed-engine

# Execute commands in container
docker compose exec litellm cat /app/config.yaml
docker compose exec postgres pg_isready
docker compose exec clickhouse clickhouse-client --query "SELECT 1"
```

---

## Getting Help

If you encounter an issue not documented here:

1. Check all logs: `docker compose logs -f`
2. Verify `.env` has all required values
3. Run `docker compose down && docker compose up -d` to restart
4. Ensure sufficient system resources (RAM, GPU memory)
5. Check Docker version: `docker --version` (should be 24+)