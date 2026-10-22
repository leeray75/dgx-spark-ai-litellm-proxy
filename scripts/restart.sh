#!/bin/bash
# =============================================================================
# restart.sh — Full stack restart with system cache clearing
# For NVIDIA DGX Spark (Blackwell GB10) workstation
#
# Usage:
#   ./restart.sh                    # Restart Qwen3.8-Flash-Next-FP4-Local (DEFAULT since 2026-10-22)
#   ./restart.sh qwen3.8-flash      # Same (aliases: flash, flash-next)
#   ./restart.sh qwen3.8            # Restart Qwen3.8-27B-NVFP4 (rollback — see the warning it prints)
#   ./restart.sh qwen3.6            # Restart Qwen3.6-35B-A3B-NVFP4 (retired rollback — see CHANGELOG.md)
#   ./restart.sh qwen               # Restart Qwen3-Coder-Next-FP8
#   ./restart.sh nemotron           # Restart Nemotron-3-Super-120B
#   ./restart.sh clean              # Stop and clear caches
#   ./restart.sh status             # Show container status
#   ./restart.sh --help             # Show this help message
#
#   DRY_RUN=1 ./restart.sh [model]  # print every mutating command (docker compose
#                                   # up/down, docker stop, sudo, agentgateway-up.sh)
#                                   # instead of running it; read-only checks still run.
#                                   # Any non-empty DRY_RUN other than 0 is a dry run
#                                   # (1, true, yes ...); unset/empty/0 runs for real
# =============================================================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FLASH="${PROJECT_DIR}/docker-compose.qwen3.8-flash-next.yml"
FLASH_COMPOSE="${PROJECT_DIR}/scripts/flash-next-compose.sh"
COMPOSE_AGW="${PROJECT_DIR}/docker-compose.agentgateway.yml"
COMPOSE_QWEN38="${PROJECT_DIR}/docker-compose.qwen3.8.yml"
COMPOSE_QWEN36="${PROJECT_DIR}/docker-compose.qwen3.6.yml"
COMPOSE_QWEN="${PROJECT_DIR}/docker-compose.yml"
COMPOSE_NEMOTRON="${PROJECT_DIR}/docker-compose.nemotron.yml"
ENV_FILE="${PROJECT_DIR}/.env"
CONTAINER_FLASH="qwen3-8-flash-next-fp4-engine"
CONTAINER_QWEN38="qwen3-8-27b-nvfp4-engine"
CONTAINER_QWEN36="qwen3-6-35b-nvfp4-engine"
CONTAINER_QWEN="qwen3-coder-next-engine"
CONTAINER_NEMOTRON="nemotron-engine"
CONTAINER_IMAGE_GEN="local-image-gen-mcp"
IMAGE_GEN_DIR="${HOME}/vscode-workspace/local-image-gen-mcp/docker"
# vLLM refuses to start when free memory < gpu-memory-utilization x total; the
# Flash-Next engine asks for 0.80 x 121.7 GiB, and CUDA's free figure on GB10
# tracks MemFree (not MemAvailable), so a cache drop is needed first.
FLASH_MIN_FREE_GIB=105
# Flash-Next's first boot took up to 18m39s (b12x compile); allow an hour.
FLASH_WAIT_SECONDS=3600
DROP_CACHES_CMD="sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'"

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

# DRY_RUN=1 prints a mutating command instead of executing it. EVERY command
# that changes state (docker compose up/down, docker stop, sudo,
# agentgateway-up.sh) must go through this wrapper.
# Dry run is on for any non-empty DRY_RUN other than "0" (DRY_RUN=1, true, yes ...);
# unset, empty or 0 runs for real. Fail-safe: an unfamiliar value never executes.
is_dry_run() {
    [[ -n "${DRY_RUN:-}" && "${DRY_RUN:-}" != "0" ]]
}

# Printed commands use %q quoting so they are copy-pasteable. The internal
# with_agw_env helper is shown as the real docker compose command it wraps.
run() {
    if is_dry_run; then
        if [[ "${1:-}" == "with_agw_env" ]]; then
            shift
            printf '[dry-run] (with AGW_LANGFUSE_BASIC_AUTH derived from .env)'
        else
            printf '[dry-run]'
        fi
        printf ' %q' "$@"
        echo
    else
        "$@"
    fi
}

# After stop_all: nothing that holds the GPU, and no agentgateway (a stale
# standalone one clashes on the container name "agentgateway"), may still run.
verify_stopped() {
    if is_dry_run; then
        echo "[dry-run] would verify that no engine container or agentgateway is still running"
        return 0
    fi
    local c
    for c in qwen3-8-flash-next-fp4-engine qwen3-8-27b-nvfp4-engine qwen3-6-35b-nvfp4-engine \
             qwen3-coder-next-engine nemotron-engine agentgateway; do
        if docker ps --format '{{.Names}}' | grep -qx "$c"; then
            log_error "$c is still running after stop_all; refusing to start a new stack (stop it by hand, then re-run)."
            exit 1
        fi
    done
}

# Run a command with AGW_LANGFUSE_BASIC_AUTH derived from .env (needed by the
# agentgateway compose files' :? guard, even for `down`). Secrets are not echoed.
with_agw_env() {
    (
        set -a
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        set +a
        if [[ -z "${LANGFUSE_PUBLIC_KEY:-}" || -z "${LANGFUSE_SECRET_KEY:-}" ]]; then
            echo "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY empty in .env" >&2
            exit 1
        fi
        export AGW_LANGFUSE_BASIC_AUTH
        AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)
        "$@"
    )
}

# Stop all containers
stop_all() {
    log_info "Stopping all containers..."
    if [[ -f "$COMPOSE_FLASH" ]]; then
        run "$FLASH_COMPOSE" down --remove-orphans 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_AGW" ]]; then
        # Standalone agentgateway project (ai-litellm-agentgateway)
        run with_agw_env docker compose -f "$COMPOSE_AGW" down 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_QWEN38" ]]; then
        run docker compose -f "$COMPOSE_QWEN38" down --remove-orphans 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_QWEN36" ]]; then
        run docker compose -f "$COMPOSE_QWEN36" down --remove-orphans 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_QWEN" ]]; then
        run docker compose -f "$COMPOSE_QWEN" down --remove-orphans 2>/dev/null || true
    fi
    if [[ -f "$COMPOSE_NEMOTRON" ]]; then
        run docker compose -f "$COMPOSE_NEMOTRON" down --remove-orphans 2>/dev/null || true
    fi
}

# Is a container running? (read-only)
container_running() {
    docker ps --format '{{.Names}}' | grep -q "^$1\$"
}

# MemFree from /proc/meminfo in GiB (read-only)
memfree_gib() {
    awk '/^MemFree:/ {printf "%.1f", $2/1024/1024}' /proc/meminfo
}

# Stop local-image-gen-mcp if it is running (it holds ~18 GB that Flash-Next
# at 0.80 cannot share; user decision U-3 keeps it off while Flash-Next runs).
stop_image_gen() {
    if container_running "$CONTAINER_IMAGE_GEN"; then
        log_info "Stopping $CONTAINER_IMAGE_GEN (Flash-Next at 0.80 leaves no room for it)..."
        run docker stop "$CONTAINER_IMAGE_GEN"
    elif is_dry_run; then
        echo "[dry-run] $CONTAINER_IMAGE_GEN is not running now; if it were: docker stop $CONTAINER_IMAGE_GEN"
    fi
}

# Warn (never abort) when MemFree is below what the Flash-Next engine needs.
flash_memory_check() {
    local free
    free=$(memfree_gib)
    if awk -v f="$free" -v m="$FLASH_MIN_FREE_GIB" 'BEGIN{exit !(f < m)}'; then
        log_warning "MemFree is ${free} GiB, below the ${FLASH_MIN_FREE_GIB} GiB the Flash-Next engine needs at startup."
        if is_dry_run; then
            echo "  (dry run: containers were not stopped and caches not dropped, so this reading is not representative)"
        else
            echo "  The engine may refuse to start. Drop caches and re-run:"
            echo "    $DROP_CACHES_CMD"
        fi
    else
        log_success "MemFree is ${free} GiB (>= ${FLASH_MIN_FREE_GIB} GiB needed by Flash-Next)"
    fi
}

# Start Qwen3.8-Flash-Next-FP4-Local (+ its agentgateway) via the wrapper
start_flash() {
    log_info "Starting Qwen3.8-Flash-Next-FP4-Local stack..."
    run "$FLASH_COMPOSE" up -d
}

# Start Qwen3.8-27B-NVFP4
start_qwen38() {
    log_info "Starting Qwen3.8-27B-NVFP4 stack..."
    run docker compose -f "$COMPOSE_QWEN38" up -d
}

# Start Qwen3.6-35B-A3B-NVFP4
start_qwen36() {
    log_info "Starting Qwen3.6-35B-A3B-NVFP4 stack..."
    run docker compose -f "$COMPOSE_QWEN36" up -d
}

# Start Qwen3-Coder-Next-FP8
start_qwen() {
    log_info "Starting Qwen3-Coder-Next-FP8 stack..."
    run docker compose -f "$COMPOSE_QWEN" up -d
}

# Start Nemotron-3-Super-120B
start_nemotron() {
    log_info "Starting Nemotron-3-Super-120B stack..."
    run docker compose -f "$COMPOSE_NEMOTRON" up -d
}

# Wait for container to be healthy. Optional 3rd argument: max wait in seconds
# (default 600). Sets WAIT_HEALTHY=true|false.
wait_for_container() {
    local container=$1
    local model_name=$2
    local max_wait=${3:-600}  # default 10 minutes
    WAIT_HEALTHY=false

    if is_dry_run; then
        echo "[dry-run] wait for $container (timeout ${max_wait}s)"
        WAIT_HEALTHY=true
        return 0
    fi

    log_info "Waiting for $model_name to initialize (may take several minutes)..."

    local elapsed=0

    while true; do
        local status
        status=$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || echo "unknown")

        if [[ "$status" == "healthy" ]]; then
            log_success "$model_name is healthy!"
            WAIT_HEALTHY=true
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

# Prominent warning for the 27B rollback target: with the 2026-10-22 default
# switch its LiteLLM / agentgateway aliases are commented out. Lists each item
# that still needs restoring. Never edits configs.
warn_27b_rollback() {
    local todo=() lc="${PROJECT_DIR}/litellm-config.yaml" ac="${PROJECT_DIR}/agentgateway/config.yaml"
    grep -q '^  - model_name: qwen3.8-27b$' "$lc" 2>/dev/null || todo+=("litellm-config.yaml: qwen3.8-27b alias is NOT active (uncomment the ROLLBACK block)")
    grep -q '^  - model_name: qwen3.8-27b-nothink$' "$lc" 2>/dev/null || todo+=("litellm-config.yaml: qwen3.8-27b-nothink alias is NOT active (same ROLLBACK block)")
    grep -q '^  default_fallbacks: \["qwen3.8-27b"\]' "$lc" 2>/dev/null || todo+=("litellm-config.yaml: default_fallbacks is not [\"qwen3.8-27b\"] (set it back)")
    grep -q '^  - name: qwen3.8-27b$' "$ac" 2>/dev/null || todo+=("agentgateway/config.yaml: qwen3.8-27b model is NOT active (uncomment the vllm-qwen38 provider and both 27B models)")
    echo ""
    log_warning "ROLLBACK to Qwen3.8-27B-NVFP4: the qwen3.8-27b / qwen3.8-27b-nothink aliases were retired 2026-10-22 (commented ROLLBACK blocks)."
    echo "    This script does not edit configs. Until they are restored, LiteLLM has no 27B route (requests may be"
    echo "    served by default_fallbacks instead) and agentgateway answers 404."
    if [[ ${#todo[@]} -eq 0 ]]; then
        log_info "All 27B aliases, default_fallbacks and the agentgateway route are already active."
    else
        local item
        for item in "${todo[@]}"; do
            log_warning "$item"
        done
    fi
    echo "    After restoring, run ./scripts/agentgateway-sync-costs.py so the cost overlay prices vllm-qwen38/qwen3.8-27b"
    echo "    (and restart litellm if it is already running)."
    echo ""
}

# After the 27B engine is healthy: restore what the Flash-Next default stopped
restore_after_27b() {
    if [[ "$WAIT_HEALTHY" != "true" ]]; then
        log_warning "27B engine not healthy yet; skipping image-gen and agentgateway restore. Run later:"
        echo "    (cd $IMAGE_GEN_DIR && docker compose -f docker-compose.yml -f docker-compose.override.yml up -d)"
        echo "    $SCRIPT_DIR/agentgateway-up.sh"
        return 0
    fi
    # compose up -d, not docker start: the ai-bridge network is recreated when a
    # stack goes down, and a stopped image-gen container keeps the stale one.
    log_info "Restoring $CONTAINER_IMAGE_GEN (compose up -d in $IMAGE_GEN_DIR)..."
    (cd "$IMAGE_GEN_DIR" && run docker compose -f docker-compose.yml -f docker-compose.override.yml up -d) \
        || log_warning "Could not restore $CONTAINER_IMAGE_GEN"
    log_info "Restoring the standalone agentgateway..."
    run "$SCRIPT_DIR/agentgateway-up.sh" || log_warning "Could not restore the standalone agentgateway"
}

# Full restart with cache clearing
restart_stack() {
    local model=${1:-qwen3.8-flash}

    echo ""
    log_info "🚀 Starting Full Stack Restart..."
    if is_dry_run; then
        log_info "DRY RUN: mutating commands are printed, not executed"
    fi
    echo ""

    if [[ "$model" == "qwen3.8" ]]; then
        warn_27b_rollback
    fi

    # 1. Stop containers
    stop_all
    verify_stopped

    # Flash-Next at 0.80 cannot share memory with the image-gen server
    if [[ "$model" == "qwen3.8-flash" ]]; then
        stop_image_gen
    fi

    # 2. Clear system caches (the Ritual)
    log_info "🧹 Dropping system caches..."
    run sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' || log_warning "Cache clearing skipped (requires sudo)"

    # 3. Start appropriate stack
    if [[ "$model" == "qwen3.8-flash" ]]; then
        flash_memory_check
        start_flash
        wait_for_container "$CONTAINER_FLASH" "Qwen3.8-Flash-Next-FP4-Local" "$FLASH_WAIT_SECONDS"
    elif [[ "$model" == "qwen3.8" ]]; then
        start_qwen38
        wait_for_container "$CONTAINER_QWEN38" "Qwen3.8-27B-NVFP4"
        restore_after_27b
    elif [[ "$model" == "qwen3.6" ]]; then
        start_qwen36
        wait_for_container "$CONTAINER_QWEN36" "Qwen3.6-35B-A3B-NVFP4"
    elif [[ "$model" == "qwen" ]]; then
        start_qwen
        wait_for_container "$CONTAINER_QWEN" "Qwen3-Coder-Next-FP8"
    elif [[ "$model" == "nemotron" ]]; then
        start_nemotron
        wait_for_container "$CONTAINER_NEMOTRON" "Nemotron-3-Super-120B"
    else
        log_error "Unknown model: $model"
        echo "Valid models: qwen3.8-flash, qwen3.8, qwen3.6, qwen, nemotron"
        exit 1
    fi

    echo ""
    if is_dry_run; then
        log_success "DRY RUN complete: no command was executed."
    else
        log_success "✅ Stack restarted successfully!"
    fi
    echo ""

    if [[ "$model" == "qwen3.8-flash" ]]; then
        echo "  Qwen3.8-Flash-Next-FP4-Local:"
        echo "    API:    http://localhost:4000/v1"
        echo "    Engine: http://localhost:8301/v1"
        echo "    agentgateway: http://localhost:4100/v1"
    elif [[ "$model" == "qwen3.8" ]]; then
        echo "  Qwen3.8-27B-NVFP4:"
        echo "    API:    http://localhost:4000/v1"
        echo "    Engine: http://localhost:8301/v1"
    elif [[ "$model" == "qwen3.6" ]]; then
        echo "  Qwen3.6-35B-A3B-NVFP4:"
        echo "    API:    http://localhost:4000/v1"
        echo "    Engine: http://localhost:8301/v1"
    elif [[ "$model" == "qwen" ]]; then
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

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-8-flash-next-fp4-engine$"; then
        local flash_status
        flash_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_FLASH" 2>/dev/null || echo "running")
        echo -e "  ${GREEN}Qwen3.8-Flash-Next-FP4-Local${NC}: $flash_status (port 8301)"
    else
        echo -e "  ${RED}Qwen3.8-Flash-Next-FP4-Local${NC}: stopped (port 8301)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-8-27b-nvfp4-engine$"; then
        local qwen38_status
        qwen38_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_QWEN38" 2>/dev/null || echo "running")
        echo -e "  ${GREEN}Qwen3.8-27B-NVFP4${NC}: $qwen38_status (port 8301)"
    else
        echo -e "  ${RED}Qwen3.8-27B-NVFP4${NC}: stopped (port 8301)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-6-35b-nvfp4-engine$"; then
        local qwen36_status
        qwen36_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_QWEN36" 2>/dev/null || echo "running")
        echo -e "  ${GREEN}Qwen3.6-35B-A3B-NVFP4${NC}: $qwen36_status (port 8301)"
    else
        echo -e "  ${RED}Qwen3.6-35B-A3B-NVFP4${NC}: stopped (port 8301)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-coder-next-engine$"; then
        local qwen_status
        qwen_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_QWEN" 2>/dev/null || echo "running")
        echo -e "  ${GREEN}Qwen3-Coder-Next-FP8${NC}: $qwen_status (port 8300)"
    else
        echo -e "  ${RED}Qwen3-Coder-Next-FP8${NC}: stopped (port 8300)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^nemotron-engine$"; then
        local nemotron_status
        nemotron_status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER_NEMOTRON" 2>/dev/null || echo "running")
        echo -e "  ${GREEN}Nemotron-3-Super-120B${NC}: $nemotron_status (port 8200)"
    else
        echo -e "  ${RED}Nemotron-3-Super-120B${NC}: stopped (port 8200)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^agentgateway$"; then
        echo -e "  ${GREEN}agentgateway${NC}: running (ports 4100 API/MCP, 4101 UI)"
    else
        echo -e "  ${RED}agentgateway${NC}: stopped (ports 4100 API/MCP, 4101 UI)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^local-image-gen-mcp$"; then
        echo -e "  ${YELLOW}local-image-gen-mcp${NC}: running (do not combine with Flash-Next at 0.80)"
    else
        echo -e "  ${RED}local-image-gen-mcp${NC}: stopped"
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
    echo "  DRY_RUN=1 $0 [model]  — Print mutating commands instead of running them (any value but 0 counts)"
    echo ""
    echo "Models:"
    echo "  qwen3.8-flash — Qwen3.8-Flash-Next-FP4-Local (DEFAULT, 125B MoE ~6B active, vision-enabled, ~38-48 tok/s;"
    echo "                  aliases: flash, flash-next; stops local-image-gen-mcp; first boot up to ~19 min)"
    echo "  qwen3.8   — Qwen3.8-27B-NVFP4 (rollback, 27B dense, vision-enabled, ~21-25 tok/s;"
    echo "              restore the ROLLBACK blocks in litellm-config.yaml / agentgateway/config.yaml first)"
    echo "  qwen3.6   — Qwen3.6-35B-A3B-NVFP4 (retired rollback, 35B MoE 3B activated, vision-capable, ~40-45 tok/s live)"
    echo "  qwen      — Qwen3-Coder-Next-FP8 (80B total, FP8 quant)"
    echo "  nemotron  — Nemotron-3-Super-120B-A12B-NVFP4 (NVFP4 quant)"
    echo ""
    echo "Examples:"
    echo "  $0              # Restart Qwen3.8-Flash-Next-FP4-Local (default)"
    echo "  $0 flash        # Same"
    echo "  $0 qwen3.8      # Restart Qwen3.8-27B-NVFP4 (rollback)"
    echo "  $0 qwen3.6      # Restart Qwen3.6-35B-A3B-NVFP4 (retired rollback)"
    echo "  $0 qwen         # Restart Qwen3-Coder-Next-FP8"
    echo "  $0 nemotron     # Restart Nemotron-3-Super-120B"
    echo "  $0 status       # Check container status"
    echo "  $0 clean        # Stop all containers"
}

# Main
main() {
    case "${1:-qwen3.8-flash}" in
        qwen3.8-flash|Qwen3.8-flash|flash|Flash|FLASH|flash-next|Flash-Next|FLASH-NEXT)
            restart_stack "qwen3.8-flash"
            ;;
        qwen3.8|Qwen3.8|QWEN3.8)
            restart_stack "qwen3.8"
            ;;
        qwen3.6|Qwen3.6|QWEN3.6)
            restart_stack "qwen3.6"
            ;;
        qwen|Qwen|QWEN)
            restart_stack "qwen"
            ;;
        nemotron|Nemotron|NEMOTRON)
            restart_stack "nemotron"
            ;;
        clean|Clean|CLEAN)
            stop_all
            verify_stopped
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
