# Qwen3.8-Flash-Next stack · Phase 3 — Plan

Facts cited as `research.md R-n` are in the shared [../research.md](../research.md).

`$REPO=/home/leeray75/vscode-workspace/ai-litellm-proxy`, `$S=<session scratchpad>/phase3`. Save the originals of every file you edit to `$S/orig/` before editing.

## 1. Measure first (read-only)

Measure before editing configs, so FR-P3-05 has its numbers:

```bash
systemctl --user is-active power-logger.service
tail -3 ~/power-logs/power-$(date -u +%Y-%m).csv
python3 -I ~/.claude/skills/llm-power-cost/scripts/power_cost.py --since 2026-10-22T21:46:35Z --rate 0.298 > $S/power_cost.txt
```

Read the suggested LiteLLM values from the output. If the script assumes the 27B anywhere, for example a hard-coded port or model name, check that it still applies to `:8301`, and record the result in R-14.

## 2. `litellm-config.yaml`

Order of entries in `model_list`:

1. `anthropic/*` (unchanged)
2. `qwen3.8-flash-next` (gets prices and an updated header comment: now the primary chat model)
3. `qwen3.8-flash-next-nothink` (new)
4. `claude-qwen3.8-flash-next` (new)
5. The commented-out ROLLBACK block for the two 27B entries, verbatim apart from the leading `# `, with a header:

   ```yaml
   # ── ROLLBACK: nvidia/Qwen3.8-27B-NVFP4 (retired as default 2026-10-22) ─────
   # Uncomment these two entries (and set default_fallbacks to ["qwen3.8-27b"])
   # before running ./scripts/model-switch.sh qwen3.8 / restart.sh qwen3.8.
   ```
6. `qwen3.6-35b-a3b`, embedding (unchanged)

`default_fallbacks: ["qwen3.8-flash-next"]`, with its comment updated.

Validate with `python3 -I -c 'import yaml…'`. If PyYAML isn't in the venv, use `docker exec litellm-proxy python -c …` against a copy in `/tmp`. Check that no active `api_base` contains `27b`.

## 3. `agentgateway/config.yaml`

Mirror §2:

- provider `vllm-qwen38-flash`;
- models `qwen3.8-flash-next` and `qwen3.8-flash-next-nothink`;
- the commented ROLLBACK block for `vllm-qwen38` and the two 27B models;
- the mapping list in the header comment.

Parse it as YAML.

## 4. `scripts/flash-next-compose.sh`

```bash
#!/usr/bin/env bash
# Run docker compose on the Qwen3.8-Flash-Next stack with AGW_LANGFUSE_BASIC_AUTH
# derived from .env (the compose file's :? guard requires it for every command).
#   ./scripts/flash-next-compose.sh up -d | ps | logs -f qwen3-8-flash-next-fp4-engine | down
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
if [[ -z "${LANGFUSE_PUBLIC_KEY:-}" || -z "${LANGFUSE_SECRET_KEY:-}" ]]; then
    echo "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY empty in .env — refusing (agentgateway traces would fail auth)" >&2
    exit 1
fi
export AGW_LANGFUSE_BASIC_AUTH
AGW_LANGFUSE_BASIC_AUTH=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)
mkdir -p agentgateway/data
exec docker compose -f docker-compose.qwen3.8-flash-next.yml "$@"
```

**AS-3 negative test.** Sourcing `.env` would overwrite variables set in the environment, so an env override alone won't produce empty keys. Test the guard by running a copy of the script from `$S` against a temporary directory that holds a fake `.env` with empty keys and a symlinked compose file. Or, simpler: extract the guard into a function and test the function. Don't touch the real `.env`.

## 5. `restart.sh` / `model-switch.sh`

Shared shape. Keep each script's own style; the two aren't identical today.

```bash
COMPOSE_FLASH="${PROJECT_DIR}/docker-compose.qwen3.8-flash-next.yml"
FLASH_COMPOSE="${PROJECT_DIR}/scripts/flash-next-compose.sh"
CONTAINER_FLASH="qwen3-8-flash-next-fp4-engine"
IMAGE_GEN_DIR="${HOME}/vscode-workspace/local-image-gen-mcp/docker"

run() {                     # DRY_RUN=1 prints instead of executing
    if [[ "${DRY_RUN:-0}" == "1" ]]; then echo "[dry-run] $*"; else "$@"; fi
}
```

- **`stop_all`** additionally runs `run "$FLASH_COMPOSE" down --remove-orphans || true` and the standalone agentgateway down. That needs the derived variable: source `.env` in a subshell, then `run docker compose -f "$PROJECT_DIR/docker-compose.agentgateway.yml" down || true`.
- **Flash start:**
  - `docker ps` check → `run docker stop local-image-gen-mcp`.
  - Memory gate:
    - `model-switch.sh`: a read-only `awk '/MemFree/…' /proc/meminfo`. Below 105 GiB → `log_error`, print the sudo command, `exit 1`. This runs *before* `stop_all`.
    - `restart.sh`: after its existing cache drop, re-check MemFree and warn (don't abort) if it is still below 105 GiB.
  - `run "$FLASH_COMPOSE" up -d`, then `wait_for_container "$CONTAINER_FLASH" … 3600`. Make `max_wait` a parameter that defaults to 600.
- **27B start (`qwen3.8`):**
  - Print the ROLLBACK warning (FR-P3-09d) before the `up`.
  - After the engine is healthy: `(cd "$IMAGE_GEN_DIR" && run docker compose -f docker-compose.yml -f docker-compose.override.yml up -d)`, then `run "$PROJECT_DIR/scripts/agentgateway-up.sh"`.
- **Default:** `restart.sh` with no argument → flash. Both scripts' help and usage text mark flash as the default and `qwen3.8` as the 27B rollback.
- **Dry-run caveat:** in dry-run, `wait_for_container` must not loop for an hour. If `DRY_RUN=1`, print `[dry-run] wait for <container> (timeout Ns)` and return.

Capture the verification transcripts to `$S/dryrun-*.txt`:

```bash
DRY_RUN=1 ./scripts/restart.sh
DRY_RUN=1 ./scripts/restart.sh qwen3.8
DRY_RUN=1 ./scripts/model-switch.sh flash
DRY_RUN=1 ./scripts/model-switch.sh qwen3.8
./scripts/restart.sh status
./scripts/model-switch.sh status
```

`restart.sh`'s cache drop calls `sudo`. Make sure it goes through `run` too, so a dry run never prompts for a password.

## 6. Prices and Langfuse

- Put the measured per-token values in all three aliases' `model_info`. Use a comment block like the 27B's: date, window, sample, J/token, W, rate, "provisional" if FR-P3-12 applies, and the re-derive command.
- **Langfuse:**
  - Read the keys inside one Python process from `docker inspect litellm-proxy` (`Config.Env`) and never print them.
  - Use `LANGFUSE_HOST` from the same env as the base URL. If that hostname doesn't resolve from the host, use `http://localhost:3000`.
  - `GET /api/public/models?limit=100` → if a definition named `qwen3.8-flash-next` exists, `DELETE` it.
  - `POST` with `modelName`, `matchPattern`, `unit: "TOKENS"`, `inputPrice`, `outputPrice`.
  - Record the id.
- `./scripts/agentgateway-sync-costs.py`, then `grep -c qwen3.8-flash-next agentgateway/costs/langfuse-overlay.json`.

## 7. Apply

```bash
curl -s localhost:8301/metrics | grep -E '^vllm:num_requests_running'   # must be 0
docker inspect -f '{{.State.StartedAt}}' qwen3-8-flash-next-fp4-engine nemotron-embed-engine > $S/startedat_before.txt
./scripts/flash-next-compose.sh restart litellm agentgateway
```

Poll `curl -s -o /dev/null -w '%{http_code}' localhost:4000/health/liveliness` until it returns 200, with a 3-minute limit, using a background task or Monitor.

## 8. Verify (FR-P3-16)

- Use small requests (`max_tokens` 256, a "Reply with OK"-style prompt; nothink gets the same).
- `POST /v1/messages` needs the headers `x-api-key: $LITELLM_MASTER_KEY` (or Bearer) and `anthropic-version: 2023-06-01`, and a body `{"model":"claude-qwen3.8-flash-next","max_tokens":256,"messages":[{"role":"user","content":"Reply with OK"}]}`. Check that `type == "message"` and the content has a text block.
- **Langfuse check:** query the newest observation for `openai/qwen3.8-flash-next` through the public API (`GET /api/public/observations?type=GENERATION&limit=5`), or the skill's read-only ClickHouse path. Report the cost value, not the keys. Allow a few seconds for ingestion.
- Write the agentgateway test report to `$S`.

## 9. Docs

Grep the repo for `qwen3.8-27b`, `27B`, `default`, `restart.sh`, `model-switch.sh` and `8301` in `CLAUDE.md`, `README.md` and `docs/*.md`, and update every statement that names the default or the aliases. Historical statements (CHANGELOG history, dated investigation notes) stay; add a dated note where something reads as current but no longer is. Read `CHANGELOG.md`'s latest entries first to follow its version and section format.

## Risks

| Risk | Mitigation |
|---|---|
| Restarting LiteLLM cuts off an in-flight request | Idle check first (FR-P3-15) |
| `claude-` alias caught by `anthropic/*` or by LiteLLM's Anthropic auto-detection | Explicit `model_name` entry; FR-P3-16(c) proves the route |
| Dry-run implementation accidentally runs a real command | Every mutating call goes through `run`; the reviewer greps for direct `docker compose … up/down/stop` calls outside `run` |
| Thin price sample | Provisional label (FR-P3-12); re-derive later |
| Langfuse API delete hits the wrong definition | Delete only a definition named exactly `qwen3.8-flash-next`; list definitions before and after |
| Clients still configured for `qwen3.8-27b` break | Inventory and report (FR-P3-17); the user updates them |
