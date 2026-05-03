#!/bin/bash
# =============================================================================
# model-switch.sh — Switch between AI models (Qwen3.6-27B-FP8, Qwen3-Coder-Next-FP8, and Nemotron-3-Super-120B)
#
# Usage:
#   ./model-switch.sh qwen3.6  — Switch to Qwen3.6-27B-FP8 (DEFAULT)
#   ./model-switch.sh qwen     — Switch to Qwen3-Coder-Next-FP8
#   ./model-switch.sh nemotron — Switch to Nemotron-3-Super-120B-A12B-NVFP4
#   ./model-switch.sh status   — Show current model status
#   ./model-switch.sh --help   — Show this help message
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - .env file created with required credentials
#   - HuggingFace token in .env for model downloads
# =============================================================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_QWEN36="${PROJECT_DIR}/docker-compose.qwen3.6.yml"
COMPOSE_QWEN="${PROJECT_DIR}/docker-compose.yml"
COMPOSE_NEMOTRON="${PROJECT_DIR}/docker-compose.nemotron.yml"
ENV_FILE="${PROJECT_DIR}/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored messages
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if .env exists
check_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        log_error ".env file not found!"
        echo "Please create a .env file from .env.sample:"
        echo "  cp .env.sample .env"
        echo "Then fill in all required values."
        exit 1
    fi
}

# Check if required environment variables are set
check_env_vars() {
    local missing=0
    local required_vars=(
        "HF_TOKEN"
        "LITELLM_MASTER_KEY"
        "POSTGRES_PASSWORD"
        "CLICKHOUSE_PASSWORD"
        "MINIO_ROOT_PASSWORD"
        "REDIS_AUTH"
        "LANGFUSE_ENCRYPTION_KEY"
        "LANGFUSE_SALT"
        "NEXTAUTH_SECRET"
    )

    for var in "${required_vars[@]}"; do
        if ! grep -q "^${var}=" "$ENV_FILE"; then
            log_error "Missing required variable: $var"
            missing=1
        fi
    done

    if [[ $missing -eq 1 ]]; then
        exit 1
    fi
}

# Stop all containers
stop_all() {
    log_info "Stopping all containers..."
    if [[ -f "$COMPOSE_QWEN36" ]]; then
        docker compose -f "$COMPOSE_QWEN36" down --remove-orphans 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_QWEN" ]]; then
        docker compose -f "$COMPOSE_QWEN" down --remove-orphans 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_NEMOTRON" ]]; then
        docker compose -f "$COMPOSE_NEMOTRON" down --remove-orphans 2>/dev/null || true
    fi
}

# Switch to Qwen3.6-27B-FP8 (DEFAULT)
switch_to_qwen36() {
    log_info "Switching to Qwen3.6-27B-FP8..."
    stop_all
    
    log_info "Starting Qwen3.6-27B-FP8 engine (port 8301)..."
    docker compose -f "$COMPOSE_QWEN36" up -d
    
    log_success "✓ Switched to Qwen3.6-27B-FP8"
    echo ""
    echo "Access points:"
    echo "  Langfuse UI:    http://localhost:3000"
    echo "  LiteLLM API:    http://localhost:4000"
    echo "  vLLM Engine:    http://localhost:8301/v1"
    echo "  Model:          Qwen/Qwen3.6-27B-FP8"
}

# Switch to Qwen3-Coder-Next-FP8
switch_to_qwen() {
    log_info "Switching to Qwen3-Coder-Next-FP8..."
    stop_all
    
    log_info "Starting Qwen3-Coder-Next-FP8 engine (port 8300)..."
    docker compose -f "$COMPOSE_QWEN" up -d
    
    log_success "✓ Switched to Qwen3-Coder-Next-FP8"
    echo ""
    echo "Access points:"
    echo "  Langfuse UI:    http://localhost:3000"
    echo "  LiteLLM API:    http://localhost:4000"
    echo "  vLLM Engine:    http://localhost:8300/v1"
    echo "  Model:          Qwen/Qwen3-Coder-Next-FP8"
}

# Switch to Nemotron-3-Super-120B-A12B-NVFP4
switch_to_nemotron() {
    log_info "Switching to Nemotron-3-Super-120B-A12B-NVFP4..."
    stop_all
    
    log_info "Starting Nemotron-3-Super-120B engine (port 8200)..."
    docker compose -f "$COMPOSE_NEMOTRON" up -d
    
    log_success "✓ Switched to Nemotron-3-Super-120B-A12B-NVFP4"
    echo ""
    echo "Access points:"
    echo "  Langfuse UI:    http://localhost:3000"
    echo "  LiteLLM API:    http://localhost:4000"
    echo "  vLLM Engine:    http://localhost:8200/v1"
    echo "  Model:          nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4"
}

# Show current status
show_status() {
    log_info "Checking container status..."
    echo ""
    
    local qwen36_running=false
    local qwen_running=false
    local nemotron_running=false
    
    if docker ps --format '{{.Names}}' | grep -q "^qwen3-6-27b-engine$"; then
        qwen36_running=true
        echo "  ${GREEN}Qwen3.6-27B-FP8${NC}: running (port 8301)"
    else
        echo "  ${RED}Qwen3.6-27B-FP8${NC}: stopped (port 8301)"
    fi
    
    if docker ps --format '{{.Names}}' | grep -q "^qwen3-coder-next-engine$"; then
        qwen_running=true
        echo "  ${GREEN}Qwen3-Coder-Next-FP8${NC}: running (port 8300)"
    else
        echo "  ${RED}Qwen3-Coder-Next-FP8${NC}: stopped (port 8300)"
    fi
    
    if docker ps --format '{{.Names}}' | grep -q "^nemotron-engine$"; then
        nemotron_running=true
        echo "  ${GREEN}Nemotron-3-Super-120B${NC}: running (port 8200)"
    else
        echo "  ${RED}Nemotron-3-Super-120B${NC}: stopped (port 8200)"
    fi
    
    echo ""
    
    if $qwen36_running; then
        log_success "Current model: Qwen3.6-27B-FP8"
    elif $qwen_running && ! $nemotron_running; then
        log_success "Current model: Qwen3-Coder-Next-FP8"
    elif $nemotron_running && ! $qwen_running; then
        log_success "Current model: Nemotron-3-Super-120B-A12B-NVFP4"
    elif $qwen_running && $nemotron_running; then
        log_warning "Warning: Both engines appear to be running!"
    else
        log_info "No models currently running."
        echo ""
        echo "Start a model with:"
        echo "  $0 qwen3.6  — Start Qwen3.6-27B-FP8 (default)"
        echo "  $0 qwen     — Start Qwen3-Coder-Next-FP8"
        echo "  $0 nemotron — Start Nemotron-3-Super-120B-A12B-NVFP4"
    fi
}

# Show help
show_help() {
    echo "model-switch.sh — Switch between AI models"
    echo ""
    echo "Usage:"
    echo "  $0 <model>     — Switch to specified model"
    echo "  $0 status      — Show current model status"
    echo "  $0 --help      — Show this help message"
    echo ""
    echo "Models:"
    echo "  qwen3.6   — Qwen3.6-27B-FP8 (default, 27B dense, vision-enabled)"
    echo "  qwen      — Qwen3-Coder-Next-FP8 (80B total, FP8 quant)"
    echo "  nemotron  — Nemotron-3-Super-120B-A12B-NVFP4 (NVFP4 quant)"
    echo ""
    echo "Examples:"
    echo "  $0 qwen3.6    # Switch to Qwen3.6-27B-FP8 (default)"
    echo "  $0 qwen       # Switch to Qwen3-Coder-Next-FP8"
    echo "  $0 nemotron   # Switch to Nemotron-3-Super-120B"
    echo "  $0 status     # Check which model is running"
}

# Main
main() {
    if [[ ! -f "$SCRIPT_DIR/model-switch.sh" ]]; then
        # Script is being sourced, don't run main
        return
    fi

    case "${1:-help}" in
        qwen3.6|Qwen3.6|QWEN3.6)
            check_env
            check_env_vars
            switch_to_qwen36
            ;;
        qwen|Qwen|QWEN)
            check_env
            check_env_vars
            switch_to_qwen
            ;;
        nemotron|Nemotron|NEMOTRON)
            check_env
            check_env_vars
            switch_to_nemotron
            ;;
        status|Status|STATUS)
            check_env
            show_status
            ;;
        --help|-h|help)
            show_help
            ;;
        *)
            log_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi