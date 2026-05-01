# Changelog

All notable changes to this project will be documented in this file.

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