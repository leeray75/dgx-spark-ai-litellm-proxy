# Qwen3.8-Flash-Next-FP4-Local stack — Specifications

Spec-driven development (SDD) for running [`nvidia/Qwen3.8-Flash-Next-FP4-Local`](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) on this DGX Spark as a candidate replacement for `Qwen3.8-27B-NVFP4`. The work is delivered in phases. Each phase has its own spec, plan and tasks. All phases share one research document.

## Phases

| Phase | Folder | Scope | Status |
|---|---|---|---|
| **1** | [phase-1-compose-file/](phase-1-compose-file/spec.md) | Write `docker-compose.qwen3.8-flash-next.yml`: the qwen3.8 stack with the Flash-Next engine plus agentgateway, in one file. Static validation only. | ✅ Implemented and reviewed (2026-10-22); never booted |
| **2** | [phase-2-first-boot-and-tests/](phase-2-first-boot-and-tests/spec.md) | Pre-download the checkpoint and pull the image. Shut down the 27B stack, the standalone agentgateway and `local-image-gen-mcp`. Boot the Flash-Next stack and record boot facts. Add the `qwen3.8-flash-next` LiteLLM alias. Add vision and throughput tests to the agentic test scripts and run them against the engine directly and through LiteLLM. Roll back only on boot failure. | ✅ Implemented and reviewed 2026-10-22 (review findings fixed); Flash-Next stack running, boot and test facts in [R-12](research.md) |
| **3** | [phase-3-routing-and-default/](phase-3-routing-and-default/spec.md) | Make Flash-Next the default (user decisions U-1–U-4). Retire the 27B aliases into ROLLBACK comment blocks, add `qwen3.8-flash-next-nothink` and `claude-qwen3.8-flash-next`, set `default_fallbacks` to Flash-Next only, and update the agentgateway routes. Add the `flash-next-compose.sh` wrapper and a `flash` default target in `restart.sh` / `model-switch.sh` (memory gate, image-gen stop and restore, dry run). Measure prices and add a Langfuse definition and the agentgateway overlay. Restart only LiteLLM and agentgateway. Update the docs. | ✅ Implemented and reviewed 2026-10-22 (review findings fixed); Flash-Next is the default stack, measured prices are provisional, facts in [R-14](research.md) |

> **2026-10-22 — phase plan revised:** the user moved the first boot and testing to Phase 2. The original Phase 2 (routing) became Phase 3, except the LiteLLM alias, which Phase 2 needs for its tests. See the Phase 2 spec's *Supersedes* row.

Phase N+1 starts only after phase N's spec is ✅. A later phase may revise an earlier decision, but it must say so explicitly (see *Changing an earlier phase*).

## Documents

| Document | Scope |
|---|---|
| [research.md](research.md) | **Shared** facts: host, model card, the NVIDIA DGX Spark recipe (verbatim), the container image, the memory budget, agentgateway and repo conventions. Every phase cites it as `research.md R-n`. |
| `phase-N-*/spec.md` | WHAT and WHY for that phase: scope, requirements, decisions, acceptance scenarios, traceability. |
| `phase-N-*/plan.md` | HOW: approach, reference definitions, risks. |
| `phase-N-*/tasks.md` | Ordered tasks traced to requirements, plus the review loop (R-tasks). |
| `phase-N-*/research.md` | *Optional.* Only for facts that matter to one phase alone. Facts any later phase could need go in the shared `research.md`. |

Pipeline per phase: `spec.md` → (shared or phase `research.md`) → `plan.md` → `tasks.md` → implementation → independent review → fixes.

## Deliverables so far

| Artifact | Phase |
|---|---|
| `docker-compose.qwen3.8-flash-next.yml` | 1 |
| [`ai-workspace/summary-reports/qwen3.8-flash-next-stack-phase1-2026-10-22.md`](../../../ai-workspace/summary-reports/qwen3.8-flash-next-stack-phase1-2026-10-22.md) | 1 |
| `litellm-config.yaml`: `qwen3.8-flash-next` alias (+19 lines) | 2 |
| `scripts/test-agentic-capabilities.py` (Vision and Decode throughput tests, `--skip-vision`) and `scripts/test-agentic-capabilities-langgraph.py` (docstring) | 2 |
| `ai-workspace/reports/agentic-test-stdlib-qwen38-flash-next-{engine,litellm}-20261022.json` and `agentic-test-langgraph-qwen38-flash-next-20261022.json` | 2 |
| `litellm-config.yaml` (Flash-Next aliases, priced; 27B aliases in a ROLLBACK block; `default_fallbacks`), `agentgateway/config.yaml`, `agentgateway/costs/langfuse-overlay.json` | 3 |
| `scripts/flash-next-compose.sh`, `scripts/restart.sh` and `scripts/model-switch.sh` (`flash` default target, `DRY_RUN=1`) | 3 |
| Langfuse model definition `qwen3.8-flash-next` (`cmvk3jw270001mo07qns04r4t`) | 3 |
| `CLAUDE.md`, `README.md`, `docs/{models,architecture,setup,troubleshooting,agents}.md`, `CHANGELOG.md`, header notes in both qwen3.8 compose files | 3 |

## Conventions

- **Requirement IDs carry the phase:** `FR-P1-07` = phase 1, functional requirement 7. Non-functional requirements use `NFR-P<n>-`.
- **Phase-local IDs:** acceptance scenarios (`AS-n`), decisions (`D-n`), tasks (`T0nn`, `R0nn`) are numbered within each phase. When referencing one from another phase, prefix the phase: `P1 D-1`, `P1 AS-6`.
- **Research IDs** (`R-n`) are global. They are numbered across the shared `research.md`. New facts are appended with the next free number and tagged with the phase that added them, e.g. `## R-11 (P2) LiteLLM alias behavior`. Existing entries are never renumbered.
- **Requirement language:** MUST / MUST NOT / SHOULD / MAY (RFC 2119).
- **Status markers** in traceability tables: ✅ met · ⚠️ partially met · ❌ not met · ⏳ not yet verified on hardware.
- **Project-wide constraints** every phase inherits: the repo's `CLAUDE.md` and `~/.claude/CLAUDE.md` (DGX Spark safety rules: no ad hoc driver installs, review restart policies before reboots, `sudo` only by the user).

## Adding a phase

1. Create `phase-<n>-<short-name>/` and write `spec.md` first. Its header table has *Status*, *Date*, *Depends on* (the earlier phases and their artifacts), and *Next*.
2. Add or extend shared facts in `research.md` (new R-numbers only), then write `plan.md` and `tasks.md`.
3. Update the **Phases** table above: folder link, scope and status.
4. After implementation and review, update the phase's traceability table and this index. Add a summary report under `ai-workspace/summary-reports/`.

## Changing an earlier phase

A later phase that changes an earlier phase's artifact or decision must:

- state it in its own spec under **Supersedes**, e.g. "Supersedes P1 D-3: the `:?` guard is replaced by the launcher script";
- add a dated note next to the superseded item in the earlier phase's spec, without deleting the original text;
- keep the earlier phase's acceptance scenarios passing, or list which ones are retired and why.

## Open items carried between phases

| Item | From | Planned in |
|---|---|---|
| A `qwen3.8-flash-next` LiteLLM alias | P1 header *KNOWN GAPS* | P2 (FR-P2-03) — done |
| LiteLLM and agentgateway route `qwen3.8-27b`, `-nothink` and `default_fallbacks` to the absent 27B engine | P1 header *KNOWN GAPS* | P3 — done (aliases removed into ROLLBACK blocks, fallbacks Flash-Next only) |
| `AGW_LANGFUSE_BASIC_AUTH` must be exported for every compose command (P1 D-3) | P1 | P3 (launcher script) — done: `scripts/flash-next-compose.sh`; the `:?` guard stays |
| `restart.sh` / `model-switch.sh` switching back removes this stack's agentgateway | P1 review finding 3 | P3 — done (`stop_all` uses the wrapper; dry-run verified only, no live switch) |
| `local-image-gen-mcp` must be stopped at 0.80 (P1 D-1) | P1 | P2 — measured: headroom is tight. Idle MemAvailable 8.16 GiB when healthy and 6.81 GiB after the tests, about 3.8 GiB above the 3 GiB trigger; not sampled under load. Keep image-gen stopped and watch MemAvailable under real traffic (R-12). Restoring it is a Phase 3 decision, and needs its compose `up -d` because of the stale network |
| While this stack is up, `qwen3.8-27b`, `qwen3.8-27b-nothink` and `default_fallbacks` fail (they target the absent 27B engine) | P2 finding | P3 — done |
| curl/python3 presence, the need for `seccomp=unconfined`, `qwen3_xml` tool calling, `start_period` 3600 s | P1 *unverified* list | P2 — done: python3 present, `qwen3_xml` works, boot ≤ 18 m 39 s; `seccomp=unconfined` necessity still untested (R-12) |
| Phase 3 prices are provisional (21 decode intervals / 12,482 output tokens). After about a day of real use: re-run `power_cost.py`, update `input_cost_per_token` / `output_cost_per_token` on **all three** Flash-Next aliases in `litellm-config.yaml`, restart LiteLLM (idle check first), DELETE + POST the Langfuse `qwen3.8-flash-next` definition, and re-run `agentgateway-sync-costs.py` | P3 | after real use |
| No live switch round trip (Flash-Next ⇄ 27B) has been run; the first real one is the user's, and `model-switch.sh flash` needs `MemFree` ≥ 105 GiB (sudo cache drop) | P3 D-2 | user |
| Client configs still naming `qwen3.8-27b` (Cline `models.json`; `DEFAULT_MODEL` in the two agentic test scripts; `.env.sample` comment) | P3 inventory (R-14) | user / later |
| P1 D-3 supersession note in `phase-1-compose-file/spec.md` (a dated note next to D-3) was not added: that file was outside Phase 3's allowed list | P3 | next edit of P1 spec |
| `scripts/test-agentic-capabilities.py` line 204 raises `IndexError` on agentgateway's usage-only stream chunk (`choices: []`); one-line fix in R-14 | P3 finding | later |
| LiteLLM serves removed/unknown model names (incl. `qwen3.8-27b`, `qwen3.8-27b-nothink`) with Flash-Next via `default_fallbacks`, thinking ON: decided and documented as intended (U-5). Callers of the `-nothink` name must move to `qwen3.8-flash-next-nothink` | P3 U-5 | clients |
| Pre-existing doc inaccuracy, left alone: `README.md` and `docs/agents.md` list `qwen3-coder-next` and `nemotron-super` as LiteLLM aliases, but `litellm-config.yaml` has no such `model_name` | P3 review | later |
