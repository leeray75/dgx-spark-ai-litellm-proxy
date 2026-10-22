# Qwen3.8-Flash-Next stack · Phase 3 — Tasks

Ordered. `→` marks a dependency. Every task obeys NFR-P3-01 – 04. Save the original of each file to `$S/orig/` before editing it.

> Implemented 2026-10-22. Notes: T001 provisional prices (21 decode intervals / 12,482 output tokens); T005/T006 memory gate runs after the old stack stops when an engine is running (see R-14); T010 (e) shows one script-side failure, see R-14. R001 / R002 are open.

## Measure
- [x] **T001** Check that the power logger is running and the `:8301` counters are present. Run `power_cost.py` from Flash-Next's healthy time and record the numbers and the sample size. *(FR-P3-10, 11, 12)*

## Configs
- [x] **T002** → T001. `litellm-config.yaml`: remove and rename the aliases (ROLLBACK block), add `-nothink` and the `claude-` alias, set fallbacks, add prices; validate the YAML. *(FR-P3-01 – 06, AS-1)*
- [x] **T003** `agentgateway/config.yaml`: Flash-Next provider and models, ROLLBACK block, header mapping; validate the YAML. *(FR-P3-07, AS-2)*

## Scripts
- [x] **T004** Create `scripts/flash-next-compose.sh` (executable, key guard). *(FR-P3-08, AS-3)*
- [x] **T005** → T004. `restart.sh` / `model-switch.sh`: flash target as the default, `stop_all` additions, memory gate, image-gen stop and restore, 3600 s wait, ROLLBACK warning, `status`, `DRY_RUN`. *(FR-P3-09)*
- [x] **T006** → T005. `bash -n` (and `shellcheck` if present). Capture the dry-run transcripts and the real `status` output. *(FR-P3-16g, h, AS-4)*

## Prices
- [x] **T007** → T001. Langfuse model definition `qwen3.8-flash-next` (list definitions before and after; record the id). *(FR-P3-13)*
- [x] **T008** → T007. `agentgateway-sync-costs.py`; check the overlay. *(FR-P3-14, AS-5)*

## Apply and verify
- [x] **T009** → T002, T003, T008. Idle check, record `StartedAt` for both engines, restart **only** `litellm` and `agentgateway`, wait for LiteLLM to be live. *(FR-P3-15)*
- [x] **T010** → T009. Verify FR-P3-16 (a) – (f); check `StartedAt` is unchanged. *(AS-6)*
- [x] **T011** Client inventory, report only. *(FR-P3-17, AS-8)*

## Docs
- [x] **T012** `CLAUDE.md`. *(FR-P3-18)*
- [x] **T013** `docs/*.md`, `README.md`. *(FR-P3-19)*
- [x] **T014** `CHANGELOG.md`. *(FR-P3-20)*
- [x] **T015** Comment-only headers of both qwen3.8 compose files; `compose config --quiet` for both. *(FR-P3-21, AS-7)*

## Close-out
- [x] **T016** Secret check of the outputs and docs; `git status` matches NFR-P3-03; delete any rendered configs from `$S`. *(AS-9)*
- [x] **T017** Update the traceability table here, the Phases row in `../SPECS.md` and its open items, and add `R-14 (P3)` to `../research.md` (measured prices, Langfuse id, verification results). Report to the caller.

## Review loop
- [x] **R001** Independent review (2026-10-22: changes requested, no blockers).
- [x] **R002** Fix the confirmed findings (2026-10-22; see R-14 *Review fixes*).
