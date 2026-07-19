# Setup Guide

This guide covers installation of the **AI LLM Proxy** stack on an **NVIDIA DGX Spark (Blackwell GB10)** workstation.

## Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 64 GB | 128 GB |
| GPU | 1x NVIDIA RTX 4090 (24GB) | 1x GB10 (128GB unified) - NVIDIA DGX Spark |
| Storage | 500 GB SSD | 1 TB NVMe SSD |
| CPU | 16 cores | 32+ cores |

> **Note:** This project is specifically optimized for the NVIDIA DGX Spark Blackwell GB10 workstation with 128 GB unified memory.

### Software Requirements

- **Docker Engine**: 24.0+ or Docker Desktop 4.29+
- **Docker Compose**: v2.20+
- **NVIDIA Container Toolkit**: For GPU support
- **HuggingFace Account**: With read access to models

### Install NVIDIA Container Toolkit

```bash
# Add the package repositories
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install the toolkit
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Restart Docker
sudo systemctl restart docker

# Verify installation
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi
```

## Installation Steps

### 1. Clone or Copy the Project

```bash
cd /home/leeray75/vscode-workspace/ai-litellm-proxy
```

### 2. Create Environment File

```bash
cp .env.sample .env
```

### 3. Configure Environment Variables

Edit `.env` with your values:

```bash
# Required: HuggingFace token (must have read access to models)
HF_TOKEN=hf_your_huggingface_token_here

# Required: Langfuse API keys (create project at localhost:3000)
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key

# Required: Passwords and secrets
POSTGRES_PASSWORD=your-secure-postgres-password
CLICKHOUSE_PASSWORD=your-clickhouse-password
MINIO_ROOT_PASSWORD=your-minio-password
REDIS_AUTH=your-redis-password

# Langfuse secrets (generate with: openssl rand -hex 32)
NEXTAUTH_SECRET=your-nextauth-secret
LANGFUSE_SALT=your-langfuse-salt
LANGFUSE_ENCRYPTION_KEY=your-32-byte-hex-key

# LiteLLM
LITELLM_MASTER_KEY=sk-your-master-key
LITELLM_SALT_KEY=your-32-byte-hex-salt
```

### 4. Generate Required Secrets

```bash
# Generate secure random values
openssl rand -hex 32  # For LANGFUSE_ENCRYPTION_KEY
openssl rand -hex 32  # For LANGFUSE_SALT
openssl rand -hex 32  # For NEXTAUTH_SECRET
openssl rand -hex 32  # For LITELLM_SALT_KEY
```

### 5. Start the Stack

#### Start with Qwen3.6-35B-A3B-NVFP4 (default):

```bash
docker compose -f docker-compose.qwen3.6.yml up -d
```

#### Or start with Qwen3-Coder-Next-FP8:

```bash
docker compose up -d
```

#### Or start with Nemotron-3-Super-120B:

```bash
docker compose -f docker-compose.nemotron.yml up -d
```

### 6. Verify Services

```bash
# Check container status
docker compose ps

# View logs
docker compose logs -f

# Check specific service logs
docker compose logs -f qwen3-6-35b-nvfp4-engine   # For Qwen3.6
docker compose logs -f nemotron-embed-engine    # For Embedding (Qwen3.6 stack)
docker compose logs -f qwen3-coder-next-engine     # For Qwen3-Coder
docker compose logs -f nemotron-engine             # For Nemotron
```

### 7. Wait for Services to Start

- **First start**: May take ~10-35 minutes for model loading (Qwen3.6 first boot includes FlashInfer fp8_gemm autotuning); results persist in `vllm-compile-cache` volume
- **Subsequent starts**: Typically ~5-15 minutes when cache is loaded from `vllm-compile-cache` volume
- **Cache invalidation**: Changing `--gpu-memory-utilization`, `--max-num-batched-tokens`, `--max-model-len`, or the vLLM image version forces a full re-tune on next boot
- **Langfuse**: Wait until UI is accessible at http://localhost:3000
- **vLLM Engine**: Check `/health` endpoint returns 200

```bash
# Check vLLM health
curl http://localhost:8301/health  # For Qwen3.6-35B
curl http://localhost:8302/health  # For Embedding Engine (Qwen3.6 stack)
curl http://localhost:8300/health  # For Qwen3-Coder
curl http://localhost:8200/health  # For Nemotron
```

## Post-Installation

### Access the Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Langfuse UI | http://localhost:3000 | Create account on first login |
| LiteLLM UI | http://localhost:4000/ui | Use `LITELLM_MASTER_KEY` |
| MinIO Console | http://localhost:9091 | `minio` / `MINIO_ROOT_PASSWORD` |

### Test the API

```bash
# Set your master key
export LITELLM_MASTER_KEY=sk-your-master-key

# Test Qwen3.6-35B-A3B-NVFP4 (default)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.6-35b-a3b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Test Qwen3-Coder-Next-FP8
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3-coder-next",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Test Nemotron-3-Super-120B
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "nemotron-super",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Test Embedding Model
curl http://localhost:4000/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "nemotron-3-embed-1b-nvfp4",
    "input": "query: Hello world"
  }'
```

## Model Switching

To switch between models after installation:

```bash
# Switch to Qwen3.6-35B-A3B-NVFP4 (default)
./scripts/model-switch.sh qwen3.6

# Switch to Qwen3-Coder-Next-FP8
./scripts/model-switch.sh qwen

# Switch to Nemotron-3-Super-120B
./scripts/model-switch.sh nemotron

# Check current status
./scripts/model-switch.sh status
```

## Updating Configuration

1. Stop the stack: `docker compose down`
2. Edit `.env` with new values
3. Restart the stack: `docker compose up -d`

## Uninstall

```bash
# Stop and remove containers
docker compose down

# Remove volumes (deletes all data!)
docker compose down -v