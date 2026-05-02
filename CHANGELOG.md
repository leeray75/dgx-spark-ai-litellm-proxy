# Changelog

All notable changes to this project will be documented in this file.

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