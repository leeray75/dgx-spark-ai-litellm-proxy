# AI LLM Proxy - Qwen3-Coder-Next-FP8 & Nemotron-3-Super-120B

An OpenAI-compatible LLM proxy running on NVIDIA DGX Spark with Langfuse v3 observability.

## Features

- **Dual Model Support**: Switch between Qwen3-Coder-Next-FP8 (80B) and Nemotron-3-Super-120B (NVFP4)
- **OpenAI-Compatible API**: Drop-in replacement for OpenAI API calls
- **Langfuse v3 Observability**: Full traceability, cost tracking, and analytics
- **vLLM Inference**: High-performance GPU inference with FlashAttention-3 support
- **LiteLLM Proxy**: Virtual key management, spend tracking, rate limiting

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User / Client                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   LiteLLM Proxy     │
                    │   (port 4000)       │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
┌───────▼───────┐    ┌─────────▼─────────┐    ┌───────▼───────┐
│  Qwen3 Engine │    │ Nemotron Engine   │    │  Langfuse UI  │
│  (port 8300)  │    │  (port 8200)      │    │  (port 3000)  │
└───────────────┘    └───────────────────┘    └───────────────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │     Langfuse Infrastructure     │
              │  ┌──────────┐  ┌─────────────┐  │
              │  │PostgreSQL│  │ ClickHouse  │  │
              │  │  (5432)  │  │  (8123)     │  │
              │  └──────────┘  └─────────────┘  │
              │  ┌──────────┐  ┌─────────────┐  │
              │  │   Redis  │  │   MinIO     │  │
              │  │  (6379)  │  │   (9090)    │  │
              │  └──────────┘  └─────────────┘  │
              └─────────────────────────────────┘
```

## Prerequisites

- Docker Desktop or Docker Engine (v24+)
- Docker Compose (v2.20+)
- NVIDIA Container Toolkit (for GPU support)
- Minimum 128GB RAM recommended
- HuggingFace token with read access to models

## Quick Start

1. **Clone or copy this repository**

2. **Create .env file**:
   ```bash
   cp .env.sample .env
   # Edit .env and fill in all required values
   ```

3. **Start the stack**:
   ```bash
   # Start with Qwen3-Coder-Next-FP8
   docker compose up -d
   
   # Or start with Nemotron-3-Super-120B
   docker compose -f docker-compose.nemotron.yml up -d
   ```

4. **Verify services**:
   ```bash
   docker compose ps
   ```

## Model Switching

Use the `model-switch.sh` script to switch between models:

```bash
# Switch to Qwen3-Coder-Next-FP8
./scripts/model-switch.sh qwen

# Switch to Nemotron-3-Super-120B
./scripts/model-switch.sh nemotron

# Check current status
./scripts/model-switch.sh status
```

## Access Points

| Service | URL | Port |
|---------|-----|------|
| Langfuse UI | http://localhost:3000 | 3000 |
| LiteLLM API | http://localhost:4000/v1 | 4000 |
| LiteLLM UI | http://localhost:4000/ui | 4000 |
| Qwen Engine | http://localhost:8300/v1 | 8300 |
| Nemotron Engine | http://localhost:8200/v1 | 8200 |
| MinIO Console | http://localhost:9091 | 9091 |

## Using the API

### OpenAI Compatible

```bash
# Qwen3-Coder-Next-FP8
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3-coder-next",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Nemotron-3-Super-120B
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "nemotron-super",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'
```

## Stopping Services

```bash
# Stop all containers
docker compose down

# Stop and remove volumes (deletes all data!)
docker compose down -v
```

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues.

## Documentation

- [Architecture](docs/architecture.md)
- [Setup Guide](docs/setup.md)
- [Models](docs/models.md)
- [Troubleshooting](docs/troubleshooting.md)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

MIT