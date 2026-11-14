# Service image updates (2026-11) · Phase 1 — Tasks

The tasks are in order, and `→` marks a dependency. Every task obeys NFR-P1-01 – 04.

## Stage A — Prepare (nothing restarts)
- [x] **T001** Record the state and the versions. *(FR-P1-02)*
- [x] **T002** Write `battery.py` and run the full baseline battery (a)–(i). *(FR-P1-01, FR-P1-12)*
- [x] **T003** Tag the running images as `local/rollback:*`. *(FR-P1-03)*
- [x] **T004** Take the backups: `pg_dumpall`, a dump of each database, and the agentgateway SQLite backup, then verify each. *(FR-P1-04)*
- [x] **T005** Fetch cosign into the scratchpad, verify LiteLLM v1.109.1 with it, and check every image is arm64. If verification fails, hand back. *(FR-P1-05)*
- [x] **T006** → T005. Change the pins in 6 compose files, check the diff and run `config --quiet` on each. *(FR-P1-06, AS-2)*
- [x] **T007** → T006. Pull the named services only. *(FR-P1-07, AS-1)*

## Stage B — Apply, one tier at a time
- [x] **T008** → T002 – T007. Data tier: postgres, redis, clickhouse. *(FR-P1-08)*
- [x] **T009** → T008. Langfuse: the worker, then web. *(FR-P1-09)*
- [x] **T010** → T009. LiteLLM. *(FR-P1-10)*
- [x] **T011** → T010. agentgateway. *(FR-P1-11, AS-3)*

## Stage C — Verify
- [x] **T012** → T011. Run the battery after the update, check the engines weren't touched and check OOMKilled. Write `comparison.md`. *(FR-P1-12, 13, AS-4)*

## Stage D — Decide
- [x] **T013** → T012. Apply the rollback triggers to each service. Roll back only the failing services. *(FR-P1-14, 15, AS-5)*

## Stage E — Docs
- [x] **T014** Grep for the old versions, sort the hits into current and historical, and update the current ones. Add the CHANGELOG entry. *(FR-P1-16)*
- [x] **T015** Fill in R-6, the traceability table and status, and the `SPECS.md` tables. *(FR-P1-17)*
- [x] **T016** Run the secret checks by count and check `git status` against NFR-P1-03. *(AS-6)*

## Review loop (up to 5 rounds)
- [x] **R001** An independent reviewer checks the diff, the evidence, the live state and the docs. *(Sonnet. Round 1 was CHANGES REQUESTED, with F1 major (wrong leak commit) and F2–F6 minor or nit. Round 2 was APPROVE, with N1 minor.)*
- [x] **R002** For each finding, the implementer fixes it or declines it with a reason. The loop repeats until the reviewer approves, or for 5 rounds at most. *(All 7 findings were fixed and none declined. 2 of 5 rounds were used.)*

## Finish (orchestrator)
- [x] **T017** Write the summary report. *(FR-P1-18)*
- [x] **T018** Make one commit. No push. *(FR-P1-19)*
