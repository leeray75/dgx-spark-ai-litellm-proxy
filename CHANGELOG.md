# Changelog

All notable changes to this project will be documented in this file.

## [1.2.1] - 2026-05-04

### Changed

- **Qwen3.6 GPU memory utilization** reduced from 0.85 to 0.60 — provides headroom for large context windows and speculative decoding, reducing OOM risk under peak load
- **Qwen3.6 max sequences** reduced from 32 to 20 — matches lower memory budget, improves per-request latency consistency

### Removed

- **`--language-model-only` flag** from Qwen3.6 vLLM args — no longer needed/compatible with current vLLM version

## [1.2.0] - 2026-05-03

### Added

- Qwen3.6-27B-FP8 support (new default model)
- Vision support in LiteLLM for Qwen3.6 (image analysis)
- `qwen3_reasoning_parser.py` script for proper reasoning token handling
- `qwen3.6` model option in `model-switch.sh` and `restart.sh` scripts

### Changed

- **Default model**: Qwen3.6-27B-FP8 now serves as the default model
- **Claude Code aliases**: Updated to `claude-sonnet-4-6` and `claude-haiku-4-6`
- **LiteLLM config**: Added `qwen3.6-27b` model entry with vision support

### Improvements

- Full 262K context window support for Qwen3.6-27B-FP8
- Better token efficiency with native reasoning parser
- Optimized GPU memory utilization (~111GB for Qwen3.6 vs ~118GB for Coder-Next)

### Configuration

- New compose file: `docker-compose.qwen3.6.yml` - standalone stack with Qwen3.6 as default
- LiteLLM config updated with vision-enabled model entries
- `--reasoning-parser qwen3` added to prevent thinking token leakage in output
- `--default-chat-template-kwargs '{"preserve_thinking":true}'` for proper reasoning

### Architecture

- **Langfuse Services**: Web UI, Worker, PostgreSQL, ClickHouse, Redis, MinIO
- **Inference Engines**: 
  - vLLM for Qwen3.6-27B-FP8 (port 8301) - DEFAULT
  - vLLM for Qwen3-Coder-Next-FP8 (port 8300)
  - vLLM for Nemotron-3-Super-120B (port 8200)
- **Proxy Layer**: LiteLLM with OTEL tracing to Langfuse

### Breaking Changes

- None - all changes are additive and backwards compatible

## [1.1.1] - 2026-05-02

### Fixed

- AI agent documentation now uses correct native model names (`qwen3-coder-next`, `nemotron-super`) instead of Claude model names
- Updated `README.md` and `docs/agents.md` to reflect correct model mappings for all AI agents

### Changed

- Documentation consistency: All AI agent configurations now reference native backend models

### Performance

- Qwen3 engine memory utilization increased from 0.88 to 0.92
- Max sequences increased from 16 to 32
- Max batched tokens increased from 16384 to 32768
- Added scheduler-delay-factor (0.3) for improved decode throughput
- Added Redis exact-match prompt caching for 100% identical requests
- Added 16GB shared memory and ulimits for vLLM container stability
- PostgreSQL tuned with shared_buffers=512MB, work_mem=16MB, WAL compression
- ClickHouse memory capped to 30% of RAM
- LiteLLM log level reduced to warning

### Configuration

- Updated LiteLLM model token limits to match vLLM `--max-model-len` (262K input, 16K output)
- Added LiteLLM stream_timeout (300s) for better stalled stream detection
- Redis cache configuration moved to litellm-config.yaml for explicit configuration
- Disabled Redis RDB snapshots and AOF for pure queue/cache workload

## [1.1.0] - 2026-05-02

### Added

- Claude Code support with `claude-sonnet-4-5` and `claude-haiku-4-5` model names
- LiteLLM configuration updates for better model routing and compatibility

## [1.0.0] - 2025-05-01

### Added

- Initial release of AI LLM Proxy project
- Support for Qwen3-Coder-Next-FP8 (80B, FP8 quantization)
- Support for Nemotron-3-Super-120B-A12B-NVFP4 (NVFP4 quantization)
- Langfuse v3 observability with ClickHouse backend
- LiteLLM OpenAI-compatible proxy
- Dual-model switching via `model-switch.sh` script
- Docker Compose configuration for both models
- Comprehensive documentation in `docs/` folder
- Example environment file (`.env.sample`)
- PostgreSQL initialization script for LiteLLM database
- MinIO S3-compatible blob storage for Langfuse
- Redis event queue for Langfuse async processing

### Architecture

- **Langfuse Services**: Web UI, Worker, PostgreSQL, ClickHouse, Redis, MinIO
- **Inference Engines**: vLLM for Qwen3-Coder-Next-FP8 and Nemotron-3-Super-120B
- **Proxy Layer**: LiteLLM with OTEL tracing to Langfuse

### Known Issues

- Initial model loading may take ~10 minutes on first start
- Requires NVIDIA GPU with at least 80GB VRAM for Nemotron-3-Super
- DGX Spark (GB10) with 128GB unified memory recommended

## [Unreleased] - Planned

### Planned Features

- [ ] Kubernetes deployment configuration
- [ ] Helm charts for Langfuse integration
- [ ] Prometheus/Grafana monitoring stack
- [ ] Auto-scaling configuration
- [ ] Multi-node deployment support
- [ ] Model versioning and rollback support
- [ ] API rate limiting per user/key
- [ ] Cost allocation by project/team

### Documentation

- [ ] API reference documentation
- [ ] Model comparison guide
- [ ] Performance benchmarks
- [ ] Security best practices
- [ ] Backup and disaster recovery guide