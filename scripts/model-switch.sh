#!/bin/bash
# =============================================================================
# model-switch.sh — Switch between AI models (Qwen3.8-Flash-Next-FP4-Local,
# Qwen3.8-27B-NVFP4, Qwen3.6-35B-A3B-NVFP4, Qwen3-Coder-Next-FP8, and
# Nemotron-3-Super-120B)
#
# Usage:
#   ./model-switch.sh flash    — Switch to Qwen3.8-Flash-Next-FP4-Local (DEFAULT since 2026-10-22;
#                                aliases: qwen3.8-flash, flash-next)
#   ./model-switch.sh qwen3.8  — Switch to Qwen3.8-27B-NVFP4 (rollback — see the warning it prints)
#   ./model-switch.sh qwen3.6  — Switch to Qwen3.6-35B-A3B-NVFP4 (retired rollback)
#   ./model-switch.sh qwen     — Switch to Qwen3-Coder-Next-FP8
#   ./model-switch.sh nemotron — Switch to Nemotron-3-Super-120B-A12B-NVFP4
#   ./model-switch.sh status   — Show current model status
#   ./model-switch.sh --help   — Show this help message
#
#   DRY_RUN=1 ./model-switch.sh <model>  — print every mutating command (docker
#       compose up/down, docker stop, sudo, agentgateway-up.sh) instead of
#       running it; read-only checks still run. Any non-empty DRY_RUN other
#       than 0 is a dry run (1, true, yes ...); unset/empty/0 runs for real
#
# Memory gates for `flash` (vLLM refuses to start unless free memory >= 0.80 x
# 121.7 GiB, and on GB10 that tracks MemFree, not MemAvailable; this script has
# no cache drop of its own, it never runs sudo):
#   1. PRE-STOP gate, before anything is stopped: if page cache (Cached+Buffers)
#      is >= 10 GiB, abort (exit 2) and print the sudo drop_caches command. The
#      10 GiB figure is MemTotal 121.7 - 105 GiB needed free - ~5 GiB baseline
#      held by the OS and observability containers (~11.7, rounded down).
#      Dropping caches while the old stack runs is harmless. With nothing running
#      MemFree itself is also checked here.
#   2. POST-STOP gate, after the old stack is stopped: if MemFree is still below
#      105 GiB, abort (exit 3) BEFORE starting. The previous stack is then already
#      STOPPED and nothing is serving; the message prints the drop command and
#      the exact re-run command. ./scripts/restart.sh drops caches itself.
# Exit codes: 2 = pre-stop gate, 3 = post-stop gate, 1 = other errors.
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
CONTAINER_IMAGE_GEN="local-image-gen-mcp"
IMAGE_GEN_DIR="${HOME}/vscode-workspace/local-image-gen-mcp/docker"
# vLLM refuses to start when free memory < gpu-memory-utilization x total; the
# Flash-Next engine asks for 0.80 x 121.7 GiB, and CUDA's free figure on GB10
# tracks MemFree (not MemAvailable). This script has no cache drop of its own.
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
        # HF_TOKEN lives in ~/.bashrc, not .env (the .env line is a comment), so
        # a variable that is already exported in the environment also counts.
        if ! grep -q "^${var}=" "$ENV_FILE" && [[ -z "${!var:-}" ]]; then
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

# Is any GPU-holding container running? (read-only)
any_gpu_container_running() {
    local c
    for c in qwen3-8-flash-next-fp4-engine qwen3-8-27b-nvfp4-engine qwen3-6-35b-nvfp4-engine \
             qwen3-coder-next-engine nemotron-engine local-image-gen-mcp; do
        container_running "$c" && return 0
    done
    return 1
}

# MemFree from /proc/meminfo in GiB (read-only)
memfree_gib() {
    awk '/^MemFree:/ {printf "%.1f", $2/1024/1024}' /proc/meminfo
}

# Page cache (Cached+Buffers) in GiB (read-only)
pagecache_gib() {
    awk '/^(Cached|Buffers):/ {s+=$2} END {printf "%.1f", s/1024/1024}' /proc/meminfo
}

# Maximum page cache tolerated before stopping anything. Derivation:
# MemTotal 121.7 GiB - 105 GiB (FLASH_MIN_FREE_GIB) - ~5 GiB baseline held by the
# OS and observability containers = ~11.7, rounded down to 10. If more than that
# is cache, MemFree cannot reach 105 GiB even after the old stack is gone.
FLASH_MAX_CACHE_GIB=10

# PRE-STOP gate (exit 2): too much page cache. Nothing has been stopped yet and
# dropping caches while the old stack runs is harmless.
flash_cache_gate() {
    local cache
    cache=$(pagecache_gib)
    if awk -v c="$cache" -v m="$FLASH_MAX_CACHE_GIB" 'BEGIN{exit !(c >= m)}'; then
        log_error "Page cache (Cached+Buffers) is ${cache} GiB, at or above ${FLASH_MAX_CACHE_GIB} GiB: MemFree could not reach the ${FLASH_MIN_FREE_GIB} GiB Flash-Next needs, even with the old stack stopped. Nothing has been stopped."
        echo "  Drop the page cache (harmless while the current stack runs), then re-run this script:"
        echo "    $DROP_CACHES_CMD"
        if is_dry_run; then
            echo "[dry-run] would abort here (exit 2); continuing only to show the remaining steps"
            return 0
        fi
        exit 2
    fi
    log_success "Page cache is ${cache} GiB (< ${FLASH_MAX_CACHE_GIB} GiB)"
}

# MemFree gate for Flash-Next: MemFree must be >= FLASH_MIN_FREE_GIB.
#   stopped=0 (nothing was running, nothing stopped): exit 2
#   stopped=1 (after stop_all): exit 3, loud about the old stack being down
# Under a dry run it only reports what would happen.
flash_memory_gate() {
    local when=$1 stopped=${2:-0} free
    free=$(memfree_gib)
    if awk -v f="$free" -v m="$FLASH_MIN_FREE_GIB" 'BEGIN{exit !(f < m)}'; then
        log_error "MemFree is ${free} GiB ($when), below the ${FLASH_MIN_FREE_GIB} GiB the Flash-Next engine needs at startup (vLLM checks free memory, and on GB10 that tracks MemFree)."
        if [[ "$stopped" == "1" ]]; then
            log_error "The previous stack has been STOPPED - nothing is serving. Flash-Next was NOT started."
            echo "  1. Drop the page cache (run it yourself, needs sudo):"
            echo "       $DROP_CACHES_CMD"
            echo "  2. Re-run:  $SCRIPT_DIR/model-switch.sh flash"
            echo "  (./scripts/restart.sh flash does the stop, the cache drop and the start in one go.)"
        else
            echo "  Nothing has been stopped. Drop the page cache, then re-run this script:"
            echo "    $DROP_CACHES_CMD"
        fi
        if is_dry_run; then
            echo "[dry-run] would abort here (exit $((stopped == 1 ? 3 : 2))); continuing only to show the remaining steps"
            return 0
        fi
        exit $((stopped == 1 ? 3 : 2))
    fi
    log_success "MemFree is ${free} GiB ($when; >= ${FLASH_MIN_FREE_GIB} GiB needed by Flash-Next)"
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

# Wait for container to be healthy. Optional 3rd argument: max wait in seconds
# (default 600). Sets WAIT_HEALTHY=true|false. Only used by the flash and
# qwen3.8 (27B) paths; the other targets return right after `up -d` as before.
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

# Switch to Qwen3.8-Flash-Next-FP4-Local (DEFAULT as of 2026-10-22 — see
# docker-compose.qwen3.8-flash-next.yml). Brings up the whole stack including
# its own agentgateway via scripts/flash-next-compose.sh.
switch_to_flash() {
    log_info "Switching to Qwen3.8-Flash-Next-FP4-Local..."
    if is_dry_run; then
        log_info "DRY RUN: mutating commands are printed, not executed"
    fi

    # Gate 1 (pre-stop): too much page cache -> abort before touching anything.
    flash_cache_gate
    # If nothing GPU-holding is running, MemFree already reflects what the new
    # engine would see, so check it now too. Otherwise MemFree still includes the
    # memory the running stack holds and is judged after the stop (gate 2).
    if any_gpu_container_running; then
        log_info "A model engine or $CONTAINER_IMAGE_GEN is running: MemFree is checked after it is stopped."
    else
        flash_memory_gate "before stopping anything" 0
    fi

    stop_all
    verify_stopped
    stop_image_gen
    # Gate 2 (post-stop): the old stack is already down if this aborts (exit 3).
    flash_memory_gate "after stopping the old stack" 1

    log_info "Starting Qwen3.8-Flash-Next-FP4-Local engine (port 8301)..."
    run "$FLASH_COMPOSE" up -d
    wait_for_container "$CONTAINER_FLASH" "Qwen3.8-Flash-Next-FP4-Local" "$FLASH_WAIT_SECONDS"

    if is_dry_run; then
        log_success "DRY RUN complete: no command was executed."
    else
        log_success "✓ Switched to Qwen3.8-Flash-Next-FP4-Local"
    fi
    echo ""
    echo "Access points:"
    echo "  Langfuse UI:    http://localhost:3000"
    echo "  LiteLLM API:    http://localhost:4000"
    echo "  agentgateway:   http://localhost:4100/v1"
    echo "  vLLM Engine:    http://localhost:8301/v1"
    echo "  Model:          nvidia/Qwen3.8-Flash-Next-FP4-Local"
}

# Switch to Qwen3.8-27B-NVFP4 (rollback since 2026-10-22 — see docker-compose.qwen3.8.yml)
switch_to_qwen38() {
    log_info "Switching to Qwen3.8-27B-NVFP4..."
    if is_dry_run; then
        log_info "DRY RUN: mutating commands are printed, not executed"
    fi
    warn_27b_rollback
    stop_all
    verify_stopped

    log_info "Starting Qwen3.8-27B-NVFP4 engine (port 8301)..."
    run docker compose -f "$COMPOSE_QWEN38" up -d
    wait_for_container "$CONTAINER_QWEN38" "Qwen3.8-27B-NVFP4"

    if [[ "$WAIT_HEALTHY" == "true" ]]; then
        # compose up -d, not docker start: the ai-bridge network is recreated
        # when a stack goes down, and a stopped image-gen container keeps the stale one.
        log_info "Restoring $CONTAINER_IMAGE_GEN (compose up -d in $IMAGE_GEN_DIR)..."
        (cd "$IMAGE_GEN_DIR" && run docker compose -f docker-compose.yml -f docker-compose.override.yml up -d) \
            || log_warning "Could not restore $CONTAINER_IMAGE_GEN"
        log_info "Restoring the standalone agentgateway..."
        run "$SCRIPT_DIR/agentgateway-up.sh" || log_warning "Could not restore the standalone agentgateway"
    else
        log_warning "27B engine not healthy yet; skipping image-gen and agentgateway restore. Run later:"
        echo "    (cd $IMAGE_GEN_DIR && docker compose -f docker-compose.yml -f docker-compose.override.yml up -d)"
        echo "    $SCRIPT_DIR/agentgateway-up.sh"
    fi

    if is_dry_run; then
        log_success "DRY RUN complete: no command was executed."
    else
        log_success "✓ Switched to Qwen3.8-27B-NVFP4"
    fi
    echo ""
    echo "Access points:"
    echo "  Langfuse UI:    http://localhost:3000"
    echo "  LiteLLM API:    http://localhost:4000"
    echo "  vLLM Engine:    http://localhost:8301/v1"
    echo "  Model:          nvidia/Qwen3.8-27B-NVFP4"
}

# Switch to Qwen3.6-35B-A3B-NVFP4 (retired rollback)
switch_to_qwen36() {
    log_info "Switching to Qwen3.6-35B-A3B-NVFP4..."
    stop_all
    verify_stopped

    log_info "Starting Qwen3.6-35B-A3B-NVFP4 engine (port 8301)..."
    run docker compose -f "$COMPOSE_QWEN36" up -d

    log_success "✓ Switched to Qwen3.6-35B-A3B-NVFP4"
    echo ""
    echo "Access points:"
    echo "  Langfuse UI:    http://localhost:3000"
    echo "  LiteLLM API:    http://localhost:4000"
    echo "  vLLM Engine:    http://localhost:8301/v1"
    echo "  Model:          nvidia/Qwen3.6-35B-A3B-NVFP4"
}

# Switch to Qwen3-Coder-Next-FP8
switch_to_qwen() {
    log_info "Switching to Qwen3-Coder-Next-FP8..."
    stop_all
    verify_stopped
    
    log_info "Starting Qwen3-Coder-Next-FP8 engine (port 8300)..."
    run docker compose -f "$COMPOSE_QWEN" up -d
    
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
    verify_stopped
    
    log_info "Starting Nemotron-3-Super-120B engine (port 8200)..."
    run docker compose -f "$COMPOSE_NEMOTRON" up -d
    
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
    
    local flash_running=false
    local qwen38_running=false
    local qwen36_running=false
    local qwen_running=false
    local nemotron_running=false

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-8-flash-next-fp4-engine$"; then
        flash_running=true
        echo -e "  ${GREEN}Qwen3.8-Flash-Next-FP4-Local${NC}: running (port 8301)"
    else
        echo -e "  ${RED}Qwen3.8-Flash-Next-FP4-Local${NC}: stopped (port 8301)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-8-27b-nvfp4-engine$"; then
        qwen38_running=true
        echo -e "  ${GREEN}Qwen3.8-27B-NVFP4${NC}: running (port 8301)"
    else
        echo -e "  ${RED}Qwen3.8-27B-NVFP4${NC}: stopped (port 8301)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-6-35b-nvfp4-engine$"; then
        qwen36_running=true
        echo -e "  ${GREEN}Qwen3.6-35B-A3B-NVFP4${NC}: running (port 8301)"
    else
        echo -e "  ${RED}Qwen3.6-35B-A3B-NVFP4${NC}: stopped (port 8301)"
    fi

    if docker ps --format '{{.Names}}' | grep -q "^qwen3-coder-next-engine$"; then
        qwen_running=true
        echo -e "  ${GREEN}Qwen3-Coder-Next-FP8${NC}: running (port 8300)"
    else
        echo -e "  ${RED}Qwen3-Coder-Next-FP8${NC}: stopped (port 8300)"
    fi
    
    if docker ps --format '{{.Names}}' | grep -q "^nemotron-engine$"; then
        nemotron_running=true
        echo -e "  ${GREEN}Nemotron-3-Super-120B${NC}: running (port 8200)"
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
    
    echo ""

    if $flash_running; then
        log_success "Current model: Qwen3.8-Flash-Next-FP4-Local"
    elif $qwen38_running; then
        log_success "Current model: Qwen3.8-27B-NVFP4"
    elif $qwen36_running; then
        log_success "Current model: Qwen3.6-35B-A3B-NVFP4"
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
        echo "  $0 flash    — Start Qwen3.8-Flash-Next-FP4-Local (default)"
        echo "  $0 qwen3.8  — Start Qwen3.8-27B-NVFP4 (rollback)"
        echo "  $0 qwen3.6  — Start Qwen3.6-35B-A3B-NVFP4 (retired rollback)"
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
    echo "  DRY_RUN=1 $0 <model>  — Print mutating commands instead of running them (any value but 0 counts)"
    echo ""
    echo "Models:"
    echo "  flash     — Qwen3.8-Flash-Next-FP4-Local (DEFAULT, 125B MoE ~6B active, vision-enabled;"
    echo "              aliases: qwen3.8-flash, flash-next; stops local-image-gen-mcp)"
    echo "              Memory gates: aborts (exit 2) BEFORE stopping anything if page cache >= ${FLASH_MAX_CACHE_GIB} GiB;"
    echo "              aborts (exit 3) AFTER stopping the old stack if MemFree < ${FLASH_MIN_FREE_GIB} GiB (nothing is then serving);"
    echo "              both print the sudo drop_caches command. ./scripts/restart.sh drops caches itself."
    echo "  qwen3.8   — Qwen3.8-27B-NVFP4 (rollback, 27B dense, vision-enabled;"
    echo "              restore the ROLLBACK blocks in litellm-config.yaml / agentgateway/config.yaml first)"
    echo "  qwen3.6   — Qwen3.6-35B-A3B-NVFP4 (retired rollback, 35B MoE 3B activated, vision-capable)"
    echo "  qwen      — Qwen3-Coder-Next-FP8 (80B total, FP8 quant)"
    echo "  nemotron  — Nemotron-3-Super-120B-A12B-NVFP4 (NVFP4 quant)"
    echo ""
    echo "Examples:"
    echo "  $0 flash      # Switch to Qwen3.8-Flash-Next-FP4-Local (default)"
    echo "  $0 qwen3.8    # Switch to Qwen3.8-27B-NVFP4 (rollback)"
    echo "  $0 qwen3.6    # Switch to Qwen3.6-35B-A3B-NVFP4 (retired rollback)"
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
        flash|Flash|FLASH|qwen3.8-flash|Qwen3.8-flash|flash-next|Flash-Next|FLASH-NEXT)
            check_env
            check_env_vars
            switch_to_flash
            ;;
        qwen3.8|Qwen3.8|QWEN3.8)
            check_env
            check_env_vars
            switch_to_qwen38
            ;;
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
