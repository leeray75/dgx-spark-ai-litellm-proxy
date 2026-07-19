# Troubleshooting Guide

## Common Issues

### 1. Model Loading Timeout

**Problem**: Engine container keeps restarting during model loading.

**Symptoms**:
- Container shows `Restarting` status
- Logs show "Loading model weights..."
- Health check fails repeatedly

**Solution**:

The initial model loading can take 10-60 minutes (Qwen3.6 first boot includes FlashInfer fp8_gemm autotuning). Subsequent starts are typically 5-15 minutes due to persistent cache in the `vllm-compile-cache` volume.

```bash
# Check container logs
docker compose logs -f qwen3-6-35b-nvfp4-engine
docker compose logs -f nemotron-embed-engine
docker compose logs -f qwen3-coder-next-engine
docker compose logs -f nemotron-engine

# Wait for loading to complete
# The health check has a 3600s start_period for Qwen3.6 (chat engine)
# and 900s start_period for the embedding engine
```

**If loading fails**:
1. Check GPU memory: `nvidia-smi`
2. Verify HF_TOKEN is correct in `.env`
3. Ensure enough disk space for model cache
4. Check FlashInfer autotune cache: `docker compose logs qwen3-6-35b-nvfp4-engine | grep -i flashinfer`

**If loading fails**:
1. Check GPU memory: `nvidia-smi`
2. Verify HF_TOKEN is correct in `.env`
3. Ensure enough disk space for model cache

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
curl http://localhost:8301/health  # For Qwen3.6-35B
curl http://localhost:8302/health  # For Embedding Engine (Qwen3.6 stack)
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
docker inspect --format '{{.Config.Image}}' qwen3-6-35b-nvfp4-engine
```

2. Check for cache-load message:
```bash
docker compose logs qwen3-6-35b-nvfp4-engine | grep -i "flashinfer.*cache"
```

3. If cache is disabled, force re-tune and escape hatch:
```bash
# Clear the cache volume to force fresh autotuning
docker volume rm ai-litellm-proxy_vllm-compile-cache
docker compose up -d qwen3-6-35b-nvfp4-engine
```

4. If output looks wrong after cache load, disable persistent cache:
```bash
# Add to vLLM environment:
VLLM_DISABLE_FLASHINFER_AUTOTUNE_CACHE=1
```

---

### 7b. Langfuse Events Not Showing
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
docker compose logs -f qwen3-6-35b-nvfp4-engine
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
# Check container status
docker compose ps -a

# Check network connectivity
docker compose exec litellm ping -c 3 qwen3-6-35b-nvfp4-engine
docker compose exec litellm ping -c 3 nemotron-embed-engine
docker compose exec litellm ping -c 3 qwen3-coder-next-engine
docker compose exec litellm ping -c 3 langfuse

# Inspect container details
docker compose inspect litellm
docker compose inspect qwen3-6-35b-nvfp4-engine
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