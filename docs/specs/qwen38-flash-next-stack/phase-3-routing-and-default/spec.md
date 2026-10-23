# Qwen3.8-Flash-Next stack · Phase 3 — Routing, operations and default

| | |
|---|---|
| **Index** | [../SPECS.md](../SPECS.md) (all phases) |
| **Status** | Implemented 2026-10-22, reviewed and fixed (R001/R002); measured facts and review fixes in [R-14](../research.md) |
| **Date** | 2026-10-22 |
| **Depends on** | Phase 2 ✅: Flash-Next stack running, `qwen3.8-flash-next` LiteLLM alias; shared [../research.md](../research.md) R-1 – R-13 |
| **Supersedes** | P1 D-3: the friction of exporting `AGW_LANGFUSE_BASIC_AUTH` is resolved by the wrapper script (FR-P3-08), and the `:?` guard stays. CLAUDE.md's 2026-09-09 "qwen3.8-27b is the default" decision: Flash-Next becomes the default and the 27B becomes the rollback (user decision 2026-10-22). |
| **Next** | [plan.md](plan.md) → [tasks.md](tasks.md) |

## User decisions (2026-10-22)

| # | Question | Decision |
|---|---|---|
| U-1 | What happens to the `qwen3.8-27b` / `qwen3.8-27b-nothink` aliases | **Remove them; rename to Flash-Next names.** `qwen3.8-27b-nothink` becomes `qwen3.8-flash-next-nothink`. |
| U-2 | LiteLLM `default_fallbacks` | **Flash-Next only:** `["qwen3.8-flash-next"]` |
| U-3 | `local-image-gen-mcp` alongside Flash-Next | **Keep it off.** Flash-Next stays at 0.80. Image generation is only available on the 27B stack. |
| U-4 | Default stack | **Flash-Next becomes the default now.** The 27B becomes the rollback. |
| U-5 | What LiteLLM does with the removed aliases (decided 2026-10-22 after the review found it) | **Keep the current behaviour; no compat aliases, no change to `default_fallbacks`.** Removed and unknown model names, including `qwen3.8-27b` and `qwen3.8-27b-nothink`, are answered by Flash-Next through `default_fallbacks` (HTTP 200, thinking ON, the requested name echoed in `model`), so `qwen3.8-27b-nothink` callers silently lose no-think until they switch to `qwen3.8-flash-next-nothink`. agentgateway returns 404 `model_not_found`. This is intended and documented (troubleshooting 4e, `agents.md`, `CLAUDE.md`, CHANGELOG, R-14). It refines FR-P3-16(a): the aliases are absent from `/v1/models`, but requests for them are not rejected by LiteLLM. |

## Problem

Flash-Next is running, but the rest of the setup still assumes the 27B:

- LiteLLM's `qwen3.8-27b`, `-nothink` and `default_fallbacks`, and agentgateway's qwen3.8 route, point at an engine that isn't running.
- Claude Code's `/model` picker can't show Flash-Next.
- Langfuse records Flash-Next requests at $0.
- Every compose command on the Flash-Next file needs a hand-derived environment variable.
- `restart.sh` and `model-switch.sh` don't know this stack. Switching back with them silently removes its agentgateway, and their 10-minute wait is shorter than Flash-Next's first boot.
- `CLAUDE.md` and `docs/` still describe the 27B as the default.

## Goal

Flash-Next is the documented, scripted default stack. Its aliases are routed by both gateways and priced from measured energy. Switching to the 27B rollback and back is one script call.

## Scope

**In scope**
- `litellm-config.yaml`
- `agentgateway/config.yaml`
- A new compose wrapper script
- `scripts/restart.sh` and `scripts/model-switch.sh`
- The Langfuse model definition and price
- The agentgateway cost overlay
- Docs: `CLAUDE.md`, `docs/*.md`, `CHANGELOG.md`, `README.md` if it names the default, and comment-only header notes in both qwen3.8 compose files
- Restarting **only** the `litellm-proxy` and `agentgateway` containers so they load the new configs
- Verification tests

**Out of scope**
- Restarting or recreating the Flash-Next engine or the embedding engine.
- Running an actual stack switch. Switch paths are verified by dry-run; there's no planned downtime.
- Editing client configs outside this repo, such as Cline's `~/.cline/data/settings/models.json`. They are inventoried and reported (FR-P3-17).
- Changing `~/.claude` skills.
- Removing the 27B Langfuse model definition, which past observations need.
- Testing whether `seccomp=unconfined` is needed.

## Functional requirements

### LiteLLM (`litellm-config.yaml`)

- **FR-P3-01** Remove the active `qwen3.8-27b` and `qwen3.8-27b-nothink` entries (U-1). Keep their exact text, including the measured-cost comments, as a commented-out **ROLLBACK** block labelled with the steps to restore it for `docker-compose.qwen3.8.yml`. No active route may reference `qwen3-8-27b-nvfp4-engine`.
- **FR-P3-02** Add `qwen3.8-flash-next-nothink`. It uses the same `litellm_params` as `qwen3.8-flash-next`, plus `extra_body.chat_template_kwargs.enable_thinking: false`; the checkpoint's chat template honors this (R-13). Its `model_info` matches `qwen3.8-flash-next`.
- **FR-P3-03** Add a `claude`-prefixed alias `claude-qwen3.8-flash-next`, with the same `litellm_params` and `model_info` as `qwen3.8-flash-next`, so Claude Code's gateway discovery shows it in `/model` (R-13). It MUST be an explicit `model_name` entry, so it takes precedence over the `anthropic/*` wildcard.
- **FR-P3-04** Set `default_fallbacks: ["qwen3.8-flash-next"]` (U-2). Update the comment around it.
- **FR-P3-05** All three Flash-Next aliases carry measured `input_cost_per_token` / `output_cost_per_token` from FR-P3-12, with a dated comment in the file's existing style, and the same `litellm_params.model` (`openai/qwen3.8-flash-next`). Langfuse matches them through one model definition.
- **FR-P3-06** The `qwen3.6-35b-a3b` and embedding entries stay unchanged.

### agentgateway (`agentgateway/config.yaml`)

- **FR-P3-07**
  - Replace provider `vllm-qwen38` with `vllm-qwen38-flash` → `http://qwen3-8-flash-next-fp4-engine:8000/v1`. Completions only, matching the existing comment's reasoning.
  - Replace models `qwen3.8-27b` / `qwen3.8-27b-nothink` with `qwen3.8-flash-next` / `qwen3.8-flash-next-nothink`, the latter with `params.model: qwen3.8-flash-next` and `chat_template_kwargs.enable_thinking: false`.
  - Keep the 27B provider and models as a commented ROLLBACK block.
  - Update the header comment's mapping list. The `claude-*` and embedding entries stay unchanged.

### Operations

- **FR-P3-08** New `scripts/flash-next-compose.sh`:
  - It `cd`s to the repo, sources `.env` (`set -a`), and derives `AGW_LANGFUSE_BASIC_AUTH`.
  - It refuses to continue if `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` is empty, so the `Og==` case can't happen.
  - It runs `mkdir -p agentgateway/data`, then `exec docker compose -f docker-compose.qwen3.8-flash-next.yml "$@"`.
  - It never echoes secrets, and it is executable (`chmod +x`).
- **FR-P3-09** `scripts/restart.sh` and `scripts/model-switch.sh`:
  - **(a) New target.** `qwen3.8-flash`, with aliases `flash` and `flash-next`. It becomes the **default**: no-argument behavior in `restart.sh`, and the "(DEFAULT)" labels in usage and help text in both scripts. `qwen3.8` stays as the 27B rollback target.
  - **(b) `stop_all`** also brings down the Flash-Next stack through the wrapper, and the standalone agentgateway project. The standalone one needs the derived variable, so it also goes through a helper that sources `.env`. Errors are tolerated (`|| true`), as the existing calls do.
  - **(c) Flash start path:**
    - `docker stop local-image-gen-mcp` if it's running (U-3).
    - Memory gate. `restart.sh` keeps its existing sudo cache drop. `model-switch.sh` has no cache drop, so it MUST check MemFree from `/proc/meminfo`. Below 105 GiB, it aborts **before** stopping anything, and prints the exact `sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` command.
    - `up -d` through the wrapper.
    - Wait for `qwen3-8-flash-next-fp4-engine`, with a 3600 s limit for this target. Other targets keep their current limits.
  - **(d) 27B start path:** after the engine is healthy,
    - restore `local-image-gen-mcp` with its compose `up -d`, run from `~/vscode-workspace/local-image-gen-mcp/docker` with `-f docker-compose.yml -f docker-compose.override.yml`. Use this, not `docker start` (R-12 stale network).
    - run `./scripts/agentgateway-up.sh` to bring back the standalone agentgateway.
    - **Warning:** with U-1, LiteLLM has no active 27B alias. The 27B path MUST print a prominent warning that the ROLLBACK blocks in `litellm-config.yaml` and `agentgateway/config.yaml` must be uncommented first. It must not edit configs automatically.
  - **(e) `status`** shows the Flash-Next engine and agentgateway.
  - **(f) Dry run.** `DRY_RUN=1` prints every mutating command (`docker compose … up/down`, `docker stop`, `sudo …`, `agentgateway-up.sh`) instead of running it, while read-only checks still run. This is how switch paths are verified in this phase.
  - **(g)** Comments and help text are updated. Existing behavior for `qwen3.6`, `qwen` and `nemotron` is unchanged apart from (b).

### Prices

- **FR-P3-10** Check that the power logger is active and that its `qwen_*` token counters come from `:8301`, which is now the Flash-Next engine (R-13).
- **FR-P3-11** Run `python3 -I ~/.claude/skills/llm-power-cost/scripts/power_cost.py --since <Flash-Next healthy time from R-12> --rate 0.298`. Record decode J/token, $/1M output and input tokens, the sample size (decode intervals and output tokens), and the script's suggested LiteLLM values.
- **FR-P3-12** Use the measured suggested values for FR-P3-05. If the window has fewer than 30 decode intervals or fewer than 20,000 output tokens, still use them, but label them **provisional** in the comment, CHANGELOG and research, with a note to re-derive after about a day of real use.
- **FR-P3-13** Create a Langfuse model definition with `modelName: qwen3.8-flash-next`, `matchPattern: (?i)^(openai/)?(qwen3.8-flash-next)$`, and the FR-P3-12 prices, through `POST /api/public/models`. Use the keys from `docker inspect litellm-proxy` env and never print them. Don't modify or delete the 27B definition. If a `qwen3.8-flash-next` definition already exists, it is a DELETE + POST of that definition only. Record the new id.
- **FR-P3-14** Run `./scripts/agentgateway-sync-costs.py` to regenerate `agentgateway/costs/langfuse-overlay.json`, and confirm it contains `qwen3.8-flash-next`.

### Apply and verify

- **FR-P3-15** Load the configs:
  - Check that the engine is idle: no `Running: [1-9]` in the last 2 minutes, or `vllm:num_requests_running` is 0 on `:8301/metrics`.
  - Then `./scripts/flash-next-compose.sh restart litellm agentgateway`. **Only those two services.**
  - Wait until LiteLLM answers `/health/liveliness` or `/v1/models`.
- **FR-P3-16** Verify:
  - **(a)** LiteLLM `/v1/models` lists `qwen3.8-flash-next`, `qwen3.8-flash-next-nothink` and `claude-qwen3.8-flash-next`, and does **not** list `qwen3.8-27b` or `qwen3.8-27b-nothink`.
  - **(b)** One chat request per alias via LiteLLM succeeds. For `-nothink`, the response has no `reasoning_content` and the reasoning token count is 0 or absent.
  - **(c)** An Anthropic-format `POST /v1/messages` via LiteLLM with `model: claude-qwen3.8-flash-next` returns a valid Messages response. This is the Claude Code path.
  - **(d)** agentgateway `:4100` `/v1/models`, or a chat request, works for `qwen3.8-flash-next` and `-nothink`.
  - **(e)** `scripts/test-agentic-capabilities.py --base-url http://localhost:4100/v1 --model qwen3.8-flash-next` runs through agentgateway, with the report in the scratchpad.
  - **(f)** Langfuse: after the requests in (b), the newest `openai/qwen3.8-flash-next` generation has a non-zero cost. Use the API or ClickHouse read-only query from the power-cost skill.
  - **(g)** Dry runs of `restart.sh` (no argument, and `qwen3.8`), `model-switch.sh flash`, `model-switch.sh qwen3.8`, and the real `status` of both scripts all behave as specified.
  - **(h)** `bash -n` passes on all changed scripts, and `shellcheck` passes too if it's installed (R-13).
- **FR-P3-17 Client inventory, report only.** List files under `~/.cline`, `~/.config`, `~/.claude/settings*.json` and the repo that still reference `qwen3.8-27b`. Exclude session/history logs. Name the setting to change in each. Don't edit them.

### Documentation

- **FR-P3-18** `CLAUDE.md`:
  - Flash-Next is the default stack; the 27B is the rollback and qwen3.6 is retired-rollback.
  - Commands: `restart.sh` / `model-switch.sh` targets and `flash-next-compose.sh`.
  - Configuration-files table, model aliases table, key vLLM flags for Flash-Next, the vLLM image table (pinned eugr digest), and the memory budget (0.80, image-gen off, measured headroom, swap).
  - Access points: the Flash-Next engine on `:8301`.
  - Startup timing (≤ 18 m 39 s cold) and the cache-drop requirement.
- **FR-P3-19** Update `docs/models.md`, `docs/architecture.md`, `docs/setup.md`, `docs/troubleshooting.md` and `docs/agents.md` wherever they name the default model or stack, the aliases or the switch commands. Add a troubleshooting entry for the startup memory check and cache drop, and for the stale image-gen network. `README.md` the same way, if it names the default.
- **FR-P3-20** Add a `CHANGELOG.md` entry covering the default switch, the alias rename and removal, fallbacks, prices (provisional or not), the new script, the script targets and the agentgateway routes. Follow the file's existing format and versioning.
- **FR-P3-21** Comment-only header notes:
  - `docker-compose.qwen3.8.yml`: a dated note at the top saying it is now the rollback stack, and that its LiteLLM and agentgateway aliases must be restored from the ROLLBACK blocks.
  - `docker-compose.qwen3.8-flash-next.yml`: update STATUS (booted 2026-10-22, default stack) and KNOWN GAPS (remove the items Phase 3 fixes, and point to the wrapper script).

  `docker compose config --quiet` must still pass for both.

## Non-functional requirements

- **NFR-P3-01 Allowed runtime actions.**
  - Allowed: `restart` of `litellm-proxy` and `agentgateway` only; the Langfuse model-definition API calls in FR-P3-13; test requests.
  - Not allowed: any `up`, `down`, `stop` or recreate of other containers; any engine restart; prune; `-v`; sudo; apt or driver work.
  - Switch paths run only with `DRY_RUN=1`.
- **NFR-P3-02 Secrets.** Never print `.env` values, Langfuse keys, the master key or the derived auth. Don't leave rendered configs containing secrets in the scratchpad.
- **NFR-P3-03 Files.** Only the files named in this spec, plus the Phase 3 docs, `SPECS.md` and `research.md`. No commits.
- **NFR-P3-04 Style.** Bash changes match the scripts' existing structure (functions, `log_*` helpers, case dispatch). YAML changes match the existing comment style.

## Decisions

- **D-1 ROLLBACK blocks instead of deleting the 27B aliases outright.** The user chose removal (U-1). The aliases are inactive, but kept as comments, so `docker-compose.qwen3.8.yml` stays a usable rollback without reconstructing measured prices from git history.
- **D-2 No live switch test.** Phase 2 already proved the Flash-Next boot. A live round trip would cost about 20–40 minutes of downtime and need sudo. Dry-run plus a static check is enough here. The first real switch is the user's.
- **D-3 Prices from the available window, labelled provisional if it's thin.** Flash-Next has run less than an hour. An honest small-sample number beats $0 or a guess scaled from the 27B.
- **D-4 One Langfuse definition for all three aliases.** They share `litellm_params.model`, so Langfuse sees one model name.

## Acceptance scenarios

- **AS-1** The `litellm-config.yaml` diff matches FR-P3-01 – 06. YAML parses. No active `api_base` references the 27B engine. `default_fallbacks == ["qwen3.8-flash-next"]`.
- **AS-2** The `agentgateway/config.yaml` diff matches FR-P3-07, and YAML parses.
- **AS-3** `flash-next-compose.sh ps` works. It refuses to run when the Langfuse keys are empty; test this with a temporary env override, without touching `.env`.
- **AS-4** FR-P3-16(g, h): the dry-run transcripts show the right commands in the right order for each target, including the MemFree gate, the image-gen stop and restore, the 3600 s wait and the rollback warning. The defaults point to Flash-Next.
- **AS-5** FR-P3-11 – 14: prices are measured and recorded, the Langfuse definition is created, and the overlay includes Flash-Next.
- **AS-6** FR-P3-15 – 16(a – f) pass. Only `litellm-proxy` and `agentgateway` were restarted: compare engine `StartedAt` before and after.
- **AS-7** Docs updated per FR-P3-18 – 21. `docker compose config --quiet` passes for both qwen3.8 files.
- **AS-8** The client inventory is reported.
- **AS-9** No secrets in any output. `git status` shows only the allowed files.

## Traceability

| Requirement | Artifact | Verification | Status |
|---|---|---|---|
| FR-P3-01 – 06 | `litellm-config.yaml` | AS-1, AS-6 | ✅ AS-1, AS-6 |
| FR-P3-07 | `agentgateway/config.yaml` | AS-2, AS-6 | ✅ AS-2, AS-6 |
| FR-P3-08 | `scripts/flash-next-compose.sh` | AS-3 | ✅ AS-3 |
| FR-P3-09 | `restart.sh`, `model-switch.sh` | AS-4 | ⚠️ AS-4 (dry-run only; no live switch, D-2). Deviation from (c): `MemFree` before stopping a running stack includes what that stack holds, so "abort below 105 GiB before stopping anything" cannot work. `model-switch.sh flash` instead has a **pre-stop** page-cache gate (Cached+Buffers ≥ 10 GiB = MemTotal 121.7 − 105 − ~5 GiB baseline → exit 2, nothing stopped), a MemFree gate before stopping only when nothing is running, and a **post-stop** MemFree gate (exit 3, the previous stack is already stopped, prints the drop and re-run commands). The post-stop gate remains when the pre-stop estimate passes. Also added in review: any non-empty `DRY_RUN` other than `0` is a dry run, post-`stop_all` verification, richer 27B warning |
| FR-P3-10 – 14 | prices, Langfuse, overlay | AS-5 | ✅ AS-5 (prices provisional) |
| FR-P3-15 – 16 | running gateways | AS-6 | ⚠️ AS-6: (a) – (d), (f), (g), (h) met; (e) ran through agentgateway, 8 pass / 1 fail / 1 warn (script-side streaming bug, R-14) |
| FR-P3-17 | report | AS-8 | ✅ AS-8 |
| FR-P3-18 – 21 | docs, compose headers | AS-7 | ✅ AS-7 |
| NFR-P3-01 – 04 | process | AS-6, AS-9, review | ✅ AS-6, AS-9, review (R001/R002 done) |
