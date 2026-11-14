# Qwen3.8-Flash-Next stack · Phase 4 — Tasks

Tasks are in order, and `→` marks a dependency. Every task obeys NFR-P4-01 – 04. **⛔** marks the human checkpoint.

## Stage A — Prepare (engine still serving)
- [x] **T001** Pull the new image by digest and record its ID, architecture, size and creation time. *(FR-P4-01)*
- [x] **T002** Record the baseline facts (`StartedAt`, ps, volumes, meminfo). *(FR-P4-03)*
- [x] **T003** → T002. Run the 3 baseline engine runs and record results, tok/s and log samples. *(FR-P4-02)*
- [x] **T004** → T001. Change the compose digest and comment, check the diff, and run `config` (scratchpad only). *(FR-P4-04, AS-1)*

## Stage B — Swap
- [x] **T005** → T003, T004. Idle check. *(FR-P4-05)*
- [x] **T006** ⛔ → T005. Stop the engine and read meminfo. If MemFree < 95 GiB, hand back for the user's cache drop. *(FR-P4-06)*
- [x] **T007** → T006. `up -d --no-deps` the engine and wait until it is healthy (60-minute limit). *(FR-P4-07)*
- [x] **T008** → T007. Record the boot facts, OOMKilled, `StartedAt` of the other services, volumes and `/v1/models`. *(FR-P4-08, 09, AS-2, AS-3)*

## Stage C — Tests
- [x] **T009** → T008. Run the 3 new engine runs, the LiteLLM run and `test-reasoning-effort.py`, with MemAvailable spot checks. *(FR-P4-10, 11)*

## Stage D — Decide
- [x] **T010** → T009. Build the comparison table and apply FR-P4-12. Record the decision. *(AS-4)*
- [x] **T011** *(only on rollback)* → T010. Carry out FR-P4-13. *(AS-6)* — not needed (KEEP)

## Stage E — Close-out
- [x] **T012** *(only on keep)* → T010. Run the check script, then update `CLAUDE.md`, `docs/architecture.md`, the R-3a note and the CHANGELOG. *(FR-P4-14, AS-5)*
- [x] **T013** Write R-15 in the shared research.md. *(FR-P4-15)*
- [x] **T014** Update the traceability table and status in spec.md and the SPECS.md index. *(FR-P4-16)*
- [x] **T015** Run the secret grep on the new reports and docs, and check that `git status` lists only NFR-P4-03 files. *(AS-7)*

## Review loop (up to 5 rounds)
- [x] **R001** An independent reviewer checks the diff, the reports, the running state and the evidence against the claims. *(Sonnet reviewer; 2 rounds, both APPROVE)*
- [x] **R002** The implementer decides on each finding: fix it, or decline with a reason. The loop repeats until the reviewer approves or 5 rounds pass. *(Round 1: F1–F5 fixed. F4 partly declined: `docs/models.md` and `docs/troubleshooting.md` are outside NFR-P4-03 and are logged as an Open item. Round 2: no new findings.)*

## Finish
- [x] **T016** → R002. Mark this file's tasks done.
- [x] **T017** Write the summary report `ai-workspace/summary-reports/flash-next-engine-image-update-2026-11-14.md`. *(FR-P4-17)*
- [x] **T018** Make one commit on `chore/engine-image-2026-11-02`, then verify that `git status` is clean. Don't push. *(FR-P4-18)*
