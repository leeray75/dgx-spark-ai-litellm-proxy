#!/bin/bash
# =============================================================================
# restart.sh — Full stack restart with system cache clearing
# For NVIDIA DGX Spark (Blackwell GB10) workstation
#
# Usage:
#   ./restart.sh                    # Restart Qwen3-Coder-Next-FP8 (default)
#   ./restart.sh nemotron           # Restart Nemotron-3-Super-120B
#   ./restart.sh clean              # Stop and clear caches
#   ./restart.sh status             # Show container status
#   ./restart.sh --help             # Show this help message
# =============================================================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_QWEN="${PROJECT_DIR}/docker-compose.yml"
COMPOSE_NEMOTRON="${PROJECT_DIR}/docker-compose.nemotron.yml"
CONTAINER_QWEN="qwen3-coder-next-engine"
CONTAINER_NEMOTRON="nemotron-engine"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

# Stop all containers
stop_all() {
    log_info "Stopping all containers..."
    docker compose -f "$COMPOSE_QWEN" down --remove-orphans 2>/dev/null || true
    docker compose -f "$COMPOSE_NEMOTRON" down --remove-orphans 2>/dev/null || true
}

# Start Qwen3-Coder-Next-FP8
start_qwen() {
    log_info "Starting Qwen3-Coder-Next-FP8 stack..."
    docker compose -f "$COMPOSE_QWEN" up -d
}

# Start Nemotron-3-Super-120B
start_nemotron() {
    log_info "Starting Nemotron-3-Super-120B stack..."
    docker compose -f "$COMPOSE_NEMOTRON" up -d
}

# Wait for container to be healthy
wait_for_container() {
    local container=$1
    local model_name=$2
    log_info "Waiting for $model_name to initialize (may take several minutes)..."
    
    local elapsed=0
    local max_wait=600  # 10 minutes
    
    while true; do
        local status
        status=$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || echo "unknown")
        
        if [[ "$status" == "healthy" ]]; then
            log_success "$model_name is healthy!"
            break
        fi
        
        if [[ "$status" == "unhealthy" ]]; then
            log_error "$model_name is unhealthy. Check logs with: docker compose logs"
            exit 1
        fi
        
        printf "."
        sleep 10
        elapsed=$((elapsed + 10))
        
        if [[ $elapsed -ge $max_wait ]]; then
            echo ""
            log_warning "Timeout waiting for $model_name (exceeded ${max_wait}s)"
            log_info "Check logs: docker compose logs -f"
            break
        fi
    done
    echo ""
}

# Full restart with cache clearing
restart_stack() {
    local model=${1:-qwen}
    
    echo ""
    log_info "🚀 Starting Full Stack Restart..."
    echo ""
    
    # 1. Stop containers
    stop_all
    
    # 2. Clear system caches (the Ritual)
    log_info "🧹 Dropping system caches..."
    sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' || log_warning "Cache clearing skipped (requires sudo)"
    
    # 3. Start appropriate stack
    if [[ "$model" == "qwen" ]]; then
        start_qwen
        wait_for_container "$CONTAINER_QWEN" "Qwen3-Coder-Next-FP8"
    elif [[ "$model" == "nemotron" ]]; then
        start_nemotron
        wait_for_container "$CONTAINER_NEMOTRON" "Nemotron-3-Super-120B"
    else
        log_error "Unknown model: $model"
        echo "Valid models: qwen, nemotron"
        exit 1
    fi
    
    echo ""
    log_success "✅ Stack restarted successfully!"
    echo ""
    
    if [[ "$model" == "qwen" ]]; then
        echo "  Qwen3-Coder-Next-FP8:"
        echo "    API:    http://localhost:4000/v1"
        echo "    Engine: http://localhost:8300/v1"
    else
        echo "  Nemotron-3-Super-120B:"
        echo "    API:    http://localhost:4000/v1"
        echo "    Engine: http://localhost:8200/v1"
    fi
    
    echo "  Langfuse: http://localhost:3000"
}

# Show status
show_status() {
    log_info "Container Status..."
    echo ""
    
    local qwen_status="stopped"
    local nemotron_status="stopped"
    
    if docker ps --format '{{.Names}}' | grep -q "^qwen3-coder-next-engine$"; then
        qwen_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_QWEN" 2>/dev/null || echo "running")
        echo "  ${GREEN}Qwen3-Coder-Next-FP8${NC}: $qwen_status (port 8300)"
    else
        echo "  ${RED}Qwen3-Coder-Next-FP8${NC}: stopped (port 8300)"
    fi
    
    if docker ps --format '{{.Names}}' | grep -q "^nemotron-engine$"; then
        nemotron_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_NEMOTRON" 2>/dev/null || echo "running")
        echo "  ${GREEN}Nemotron-3-Super-120B${NC}: $nemotron_status (port 8200)"
    else
        echo "  ${RED}Nemotron-3-Super-120B${NC}: stopped (port 8200)"
    fi
}

# Show help
show_help() {
    echo "restart.sh — Full stack restart with cache clearing"
    echo ""
    echo "Usage:"
    echo "  $0 [model]       — Restart with specified model"
    echo "  $0 status        — Show container status"
    echo "  $0 clean         — Stop all containers"
    echo "  $0 --help        — Show this help message"
    echo ""
    echo "Models:"
    echo "  qwen     — Qwen3-Coder-Next-FP8 (default)"
    echo "  nemotron — Nemotron-3-Super-120B-A12B-NVFP4"
    echo ""
    echo "Examples:"
    echo "  $0              # Restart Qwen3-Coder-Next-FP8"
    echo "  $0 nemotron     # Restart Nemotron-3-Super-120B"
    echo "  $0 status       # Check container status"
    echo "  $0 clean        # Stop all containers"
}

# Main
main() {
    case "${1:-qwen}" in
        qwen|Qwen|QWEN)
            restart_stack "qwen"
            ;;
        nemotron|Nemotron|NEMOTRON)
            restart_stack "nemotron"
            ;;
        clean|Clean|CLEAN)
            stop_all
            log_success "All containers stopped."
            ;;
        status|Status|STATUS)
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