# AI LLM Proxy - Qwen3.6-27B-FP8, Qwen3-Coder-Next-FP8 & Nemotron-3-Super-120B

An OpenAI-compatible LLM proxy running on **NVIDIA DGX Spark (Blackwell GB10)** with Langfuse v3 observability.

> **Hardware:** NVIDIA DGX Spark workstation with GB10 Superchip (128 GB unified memory) and NVIDIA Blackwell architecture GPUs.

## Features

- **Triple Model Support**: Switch between Qwen3.6-27B-FP8 (default), Qwen3-Coder-Next-FP8 (80B), and Nemotron-3-Super-120B (NVFP4)
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
      ┌────────────────────────┼────────────────────────┐
      │                        │                        │
┌─────▼───────┐    ┌───────────▼──────────┐    ┌────────▼───────┐
│ Qwen3.6 Engine│    │ Qwen3-Coder Engine   │    │  Langfuse UI   │
│  (port 8301)  │    │   (port 8300)        │    │  (port 3000)   │
└───────────────┘    └──────────────────────┘    └────────────────┘
      │                        │                        │
      │                ┌──────▼───────┐                  │
      │                │Nemotron Engine│                  │
      │                │ (port 8200)  │                  │
      │                └──────────────┘                  │
      └────────────────────────┼─────────────────────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │    Langfuse Infrastructure│
                 │  ┌──────────┐ ┌──────────┐│
                 │  │PostgreSQL│ │ ClickHouse││
                 │  │  (5432)  │ │  (8123)  ││
                 │  └──────────┘ └──────────┘│
                 │  ┌──────────┐ ┌──────────┐│
                 │  │   Redis  │ │   MinIO  ││
                 │  │  (6379)  │ │  (9090)  ││
                 │  └──────────┘ └──────────┘│
                 └───────────────────────────┘
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
   # Start with Qwen3.6-27B-FP8 (default)
   docker compose -f docker-compose.qwen3.6.yml up -d
   
   # Or start with Qwen3-Coder-Next-FP8
   docker compose up -d
   
   # Or start with Nemotron-3-Super-120B
   docker compose -f docker-compose.nemotron.yml up -d
   ```

4. **Verify services**:
   ```bash
   docker compose ps
   ```

## Scripts

### model-switch.sh

Switch between models:

```bash
# Switch to Qwen3.6-27B-FP8 (DEFAULT)
./scripts/model-switch.sh qwen3.6

# Switch to Qwen3-Coder-Next-FP8
./scripts/model-switch.sh qwen

# Switch to Nemotron-3-Super-120B
./scripts/model-switch.sh nemotron

# Check current status
./scripts/model-switch.sh status
```

### restart.sh

Full stack restart with system cache clearing (for NVIDIA DGX Spark Blackwell GB10):

```bash
# Restart with Qwen3.6-27B-FP8 (default)
./scripts/restart.sh

# Restart with Qwen3.6-27B-FP8
./scripts/restart.sh qwen3.6

# Restart with Qwen3-Coder-Next-FP8
./scripts/restart.sh qwen

# Restart with Nemotron-3-Super-120B
./scripts/restart.sh nemotron

# Check container status
./scripts/restart.sh status

# Stop all containers
./scripts/restart.sh clean
```

> **Note:** The restart script includes the "Ritual" - clearing system caches via `sudo sync; echo 3 > /proc/sys/vm/drop_caches` - to ensure optimal performance on DGX Spark.

## Access Points

| Service | URL | Port |
|---------|-----|------|
| Langfuse UI | http://localhost:3000 | 3000 |
| LiteLLM API | http://localhost:4000/v1 | 4000 |
| LiteLLM UI | http://localhost:4000/ui | 4000 |
| Qwen3.6 Engine | http://localhost:8301/v1 | 8301 |
| Qwen3-Coder Engine | http://localhost:8300/v1 | 8300 |
| Nemotron Engine | http://localhost:8200/v1 | 8200 |
| MinIO Console | http://localhost:9091 | 9091 |

## Using the API

### OpenAI Compatible

```bash
# Qwen3.6-27B-FP8 (default)
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "qwen3.6-27b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

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

### Claude Code

Configure Claude Code to use the LiteLLM proxy for local LLM access.

#### Setting Up Claude Code

**Location of Claude Code Settings:**

| Platform | File Location |
|----------|---------------|
| **Windows** | `C:\Users\<username>\.claude\settings.json` |
| **macOS/Linux** | `~/.claude/settings.json` |

**Steps to configure:**

1. Open your Claude Code settings file (`settings.json`)
2. Add the following configuration:

```json
{
  "defaultShell": "bash",
  "env": {
    "BASH_ENV": "/home/leeray/.bashrc",
    "ANTHROPIC_BASE_URL": "http://localhost:4000",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-litellm-master-key",
    "ANTHROPIC_SMALL_FAST_MODEL": "claude-haiku-4-6",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"
  }
}
```

3. Save the file and restart Claude Code

**Environment Variable Reference:**

| Variable | Description | Example |
|----------|-------------|---------|
| `defaultShell` | Shell to use | `"bash"` |
| `BASH_ENV` | Bash environment file | `"/home/leeray/.bashrc"` |
| `ANTHROPIC_BASE_URL` | LiteLLM proxy endpoint | `"http://localhost:4000"` |
| `ANTHROPIC_AUTH_TOKEN` | Your LiteLLM master key | `"sk-..."` |
| `ANTHROPIC_SMALL_FAST_MODEL` | Fast model for background tasks | `"claude-haiku-4-6"` |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | Reduce non-essential logs | `"1"` |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | Disable experimental features | `"1"` |

**Available Claude Code model names:**

| Model Name | Purpose | Backend Model |
|------------|---------|---------------|
| `claude-sonnet-4-6` | Main tasks, complex reasoning | Qwen3.6-27B-FP8 |
| `claude-haiku-4-6` | Fast/background tasks | Qwen3.6-27B-FP8 |

> **Note:** Replace `ANTHROPIC_BASE_URL` with your actual server address. If running on a remote server, use the public URL or VPN address (e.g., `http://spark-8013.taileaa4a8.ts.net:4000`).

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
- [AI Agent Configuration](docs/agents.md)

## AI Agents & Clients

The LiteLLM proxy provides an OpenAI-compatible API and works with many AI agents and tools:

| Agent/Tool | API Model | Port | Purpose |
|------------|-----------|------|---------|
| Claude Code | `claude-sonnet-4-6`, `claude-haiku-4-6` | 4000 | Terminal-based AI assistant |
| Cline Code | `qwen3.6-27b`, `qwen3-coder-next`, `nemotron-super` | 4000 | VS Code AI assistant |
| Cursor IDE | `qwen3.6-27b`, `qwen3-coder-next`, `nemotron-super` | 4000 | AI-powered code editor |
| Continue | `qwen3.6-27b`, `qwen3-coder-next`, `nemotron-super` | 4000 | Open-source AI assistant |
| Codeium | `qwen3.6-27b`, `qwen3-coder-next`, `nemotron-super` | 4000 | AI coding assistant |
| OpenWebUI | Direct endpoint | 3000 | Web-based LLM interface |
| OpenAI SDK | `qwen3.6-27b`, `qwen3-coder-next`, `nemotron-super` | 4000 | Python/JavaScript clients |

**Full documentation:** See [AI Agent Configuration](docs/agents.md) for detailed setup guides.

> **Note:** All agents support the same backend models - Qwen3.6-27B-FP8, Qwen3-Coder-Next-FP8, and Nemotron-3-Super-120B.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

MIT